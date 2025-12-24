#!/usr/bin/env python3
"""
Script to find and remove duplicate articles from the database.

Duplicate detection strategies:
1. Same title + author + date (most reliable)
2. Same URL (shouldn't happen due to unique constraint, but check anyway)
3. Same html_file_en (shouldn't happen, but check anyway)

For duplicates, keep the most complete record (has URL, has Chinese translation, most recent).
"""
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Article
from app.config import DATABASE_URL

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def normalize_url(url):
    """Normalize URL by removing query parameters and fragments."""
    if not url:
        return None
    from urllib.parse import urlparse, urlunparse
    parsed = urlparse(url)
    # Remove query and fragment
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        '',  # params
        '',  # query
        ''   # fragment
    ))
    # Remove trailing slash
    if normalized.endswith('/'):
        normalized = normalized[:-1]
    return normalized

def find_duplicates_by_title_author_date(db):
    """Find duplicates by title + author + date."""
    duplicates = defaultdict(list)
    
    # Query all articles
    articles = db.query(Article).all()
    
    for article in articles:
        # Create a key from title, author, and date
        key = (
            article.title.strip().lower() if article.title else '',
            article.author.strip().lower() if article.author else '',
            article.date.date() if article.date else None
        )
        duplicates[key].append(article)
    
    # Filter to only groups with more than one article
    return {k: v for k, v in duplicates.items() if len(v) > 1}

def find_duplicates_by_url(db):
    """Find duplicates by normalized URL."""
    duplicates = defaultdict(list)
    
    articles = db.query(Article).filter(Article.original_url != '').all()
    
    for article in articles:
        normalized_url = normalize_url(article.original_url)
        if normalized_url:
            duplicates[normalized_url].append(article)
    
    # Filter to only groups with more than one article
    return {k: v for k, v in duplicates.items() if len(v) > 1}

def find_duplicates_by_filename(db):
    """Find duplicates by html_file_en."""
    duplicates = defaultdict(list)
    
    articles = db.query(Article).all()
    
    for article in articles:
        if article.html_file_en:
            duplicates[article.html_file_en].append(article)
    
    # Filter to only groups with more than one article
    return {k: v for k, v in duplicates.items() if len(v) > 1}

def score_article(article):
    """Score an article - higher score means keep this one."""
    score = 0
    
    # Has URL: +10
    if article.original_url:
        score += 10
    
    # Has Chinese translation: +5
    if article.html_file_zh:
        score += 5
    
    # Has Chinese title: +3
    if article.title_zh:
        score += 3
    
    # More recent: +1 per day (normalized)
    if article.updated_at:
        days_ago = (datetime.utcnow() - article.updated_at).days
        score += max(0, 30 - days_ago) / 30  # Decay over 30 days
    
    return score

def deduplicate_group(articles):
    """Deduplicate a group of articles, keeping the best one."""
    if len(articles) <= 1:
        return [], []
    
    # Score each article
    scored = [(score_article(a), a) for a in articles]
    scored.sort(reverse=True, key=lambda x: x[0])
    
    # Keep the highest scored article
    keep = scored[0][1]
    remove = [a for _, a in scored[1:]]
    
    return keep, remove

def main():
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    
    try:
        print("=" * 80)
        print("Article Deduplication Script")
        print("=" * 80)
        
        # Strategy 1: Find duplicates by title + author + date
        print("\n[Strategy 1] Checking for duplicates by title + author + date...")
        dupes_by_title = find_duplicates_by_title_author_date(db)
        print(f"Found {len(dupes_by_title)} groups of duplicates by title+author+date")
        
        # Strategy 2: Find duplicates by normalized URL
        print("\n[Strategy 2] Checking for duplicates by normalized URL...")
        dupes_by_url = find_duplicates_by_url(db)
        print(f"Found {len(dupes_by_url)} groups of duplicates by URL")
        
        # Strategy 3: Find duplicates by filename
        print("\n[Strategy 3] Checking for duplicates by filename...")
        dupes_by_filename = find_duplicates_by_filename(db)
        print(f"Found {len(dupes_by_filename)} groups of duplicates by filename")
        
        # Strategy 4: Find duplicates by normalized URL (more comprehensive check)
        print("\n[Strategy 4] Checking for duplicates by normalized URL (comprehensive)...")
        all_articles = db.query(Article).filter(Article.original_url != '').all()
        normalized_groups = defaultdict(list)
        for article in all_articles:
            norm_url = normalize_url(article.original_url)
            if norm_url:
                normalized_groups[norm_url].append(article)
        dupes_by_normalized_url = {k: v for k, v in normalized_groups.items() if len(v) > 1}
        print(f"Found {len(dupes_by_normalized_url)} groups of duplicates by normalized URL")
        
        # Combine all duplicate groups
        all_duplicates = {}
        
        # Add title+author+date duplicates
        for key, articles in dupes_by_title.items():
            title, author, date = key
            group_key = f"title+author+date: {title[:50]}..."
            all_duplicates[group_key] = articles
        
        # Add URL duplicates
        for url, articles in dupes_by_url.items():
            group_key = f"URL: {url[:70]}..."
            all_duplicates[group_key] = articles
        
        # Add filename duplicates
        for filename, articles in dupes_by_filename.items():
            group_key = f"filename: {filename}"
            all_duplicates[group_key] = articles
        
        # Add normalized URL duplicates
        for url, articles in dupes_by_normalized_url.items():
            group_key = f"normalized URL: {url[:70]}..."
            all_duplicates[group_key] = articles
        
        if not all_duplicates:
            print("\n✅ No duplicates found!")
            return 0
        
        print(f"\n{'=' * 80}")
        print(f"Found {len(all_duplicates)} duplicate groups")
        print(f"{'=' * 80}\n")
        
        # Show duplicates
        total_duplicates = 0
        to_remove = []
        to_keep = []
        
        for group_key, articles in all_duplicates.items():
            print(f"\n{group_key}")
            print(f"  Found {len(articles)} duplicate(s):")
            
            keep, remove = deduplicate_group(articles)
            
            print(f"  ✅ KEEP: {keep.id}")
            print(f"     Title: {keep.title}")
            print(f"     URL: {keep.original_url or '(none)'}")
            print(f"     Has Chinese: {bool(keep.html_file_zh)}")
            
            for article in remove:
                print(f"  ❌ REMOVE: {article.id}")
                print(f"     Title: {article.title}")
                print(f"     URL: {article.original_url or '(none)'}")
                print(f"     Has Chinese: {bool(article.html_file_zh)}")
                to_remove.append(article)
                total_duplicates += 1
            
            to_keep.append(keep)
        
        print(f"\n{'=' * 80}")
        print(f"Summary:")
        print(f"  Total duplicate groups: {len(all_duplicates)}")
        print(f"  Total articles to remove: {total_duplicates}")
        print(f"  Total articles to keep: {len(to_keep)}")
        print(f"{'=' * 80}\n")
        
        if total_duplicates == 0:
            print("No duplicates to remove.")
            return 0
        
        # Ask for confirmation
        response = input(f"Remove {total_duplicates} duplicate article(s)? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled.")
            return 0
        
        # Remove duplicates
        print("\nRemoving duplicates...")
        removed_count = 0
        for article in to_remove:
            try:
                db.delete(article)
                removed_count += 1
                print(f"  Removed: {article.id} - {article.title[:60]}...")
            except Exception as e:
                print(f"  Error removing {article.id}: {e}")
        
        db.commit()
        print(f"\n✅ Successfully removed {removed_count} duplicate article(s)")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        db.rollback()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())

