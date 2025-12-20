#!/usr/bin/env python3
"""
Script to rename existing article files to include source identifier in filename.

Old format: {date}_{category}_{author}_{title}.html
New format: {date}_{source}_{category}_{author}_{title}.html

This script:
1. Scans existing HTML files in data/html/en/ and data/html/zh/
2. Determines source from URL in metadata JSON or by scraping
3. Renames files to include source slug
4. Updates database records with new filenames
"""
import os
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.scrapers import get_scraper_for_url
from app.database import SessionLocal
from app.models import Article
from app.config import HTML_DIR_EN, HTML_DIR_ZH

def sanitize_filename(text):
    """Sanitize text for use in filenames."""
    import re
    # Replace invalid filename characters with underscores
    text = re.sub(r'[<>:"/\\|?*]', '_', text)
    # Replace multiple spaces/underscores with single underscore
    text = re.sub(r'[\s_]+', '_', text)
    # Remove leading/trailing underscores
    text = text.strip('_')
    # Limit length
    if len(text) > 100:
        text = text[:100]
    return text

def get_source_from_metadata(json_file):
    """Get source from metadata JSON file."""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        url = metadata.get('url', '')
        source = metadata.get('source', '')
        
        if url:
            scraper = get_scraper_for_url(url)
            if scraper:
                return scraper.get_source_slug()
        
        # Fallback: convert source name to slug
        if source:
            source_lower = source.lower().replace(' ', '')
            if 'newyorker' in source_lower or source_lower == 'newyorker':
                return 'newyorker'
            elif 'newyorktimes' in source_lower or source_lower == 'nytimes' or 'nytimes' in source_lower:
                return 'nytimes'
        
        return None
    except Exception as e:
        print(f"  Error reading metadata {json_file}: {e}", file=sys.stderr)
        return None

def parse_old_filename(filename):
    """Parse old format filename: date_category_author_title.html"""
    base_name = filename.replace('.html', '')
    parts = base_name.split('_')
    
    if len(parts) < 4:
        return None
    
    try:
        date_obj = datetime.strptime(parts[0], '%Y-%m-%d')
    except ValueError:
        return None
    
    category = parts[1]
    author = parts[2] if len(parts) > 3 else 'unknown'
    title = '_'.join(parts[3:]) if len(parts) > 3 else 'untitled'
    
    return {
        'date': date_obj,
        'category': category,
        'author': author,
        'title': title
    }

def rename_articles(dry_run=True):
    """Rename articles to include source identifier."""
    en_dir = Path(HTML_DIR_EN)
    zh_dir = Path(HTML_DIR_ZH)
    
    if not en_dir.exists():
        print(f"Error: English directory not found: {en_dir}", file=sys.stderr)
        return
    
    en_files = list(en_dir.glob("*.html"))
    print(f"Found {len(en_files)} HTML files in {en_dir}", file=sys.stderr)
    
    renamed_count = 0
    skipped_count = 0
    error_count = 0
    
    db = SessionLocal()
    
    try:
        for en_file in en_files:
            filename = en_file.name
            
            # Skip if already in new format (contains known source slug)
            if '_newyorker_' in filename or '_nytimes_' in filename:
                print(f"  Skipping {filename} (already in new format)", file=sys.stderr)
                skipped_count += 1
                continue
            
            # Parse old filename
            parsed = parse_old_filename(filename)
            if not parsed:
                print(f"  Skipping {filename} (cannot parse)", file=sys.stderr)
                skipped_count += 1
                continue
            
            # Get source from metadata JSON
            json_file = en_dir / filename.replace('.html', '.json')
            source_slug = None
            
            if json_file.exists():
                source_slug = get_source_from_metadata(json_file)
            
            if not source_slug:
                # Try to get from database
                try:
                    # Try to find article by old filename
                    article = db.query(Article).filter(
                        Article.html_file_en == f"en/{filename}"
                    ).first()
                    
                    if article and article.original_url:
                        scraper = get_scraper_for_url(article.original_url)
                        if scraper:
                            source_slug = scraper.get_source_slug()
                except Exception as e:
                    print(f"  Error querying database for {filename}: {e}", file=sys.stderr)
            
            if not source_slug:
                print(f"  Warning: Cannot determine source for {filename}, skipping", file=sys.stderr)
                skipped_count += 1
                continue
            
            # Build new filename
            date_str = parsed['date'].strftime('%Y-%m-%d')
            category_safe = sanitize_filename(parsed['category'])
            author_safe = sanitize_filename(parsed['author'])
            title_safe = sanitize_filename(parsed['title'])
            
            new_filename = f"{date_str}_{source_slug}_{category_safe}_{author_safe}_{title_safe}.html"
            
            if new_filename == filename:
                print(f"  Skipping {filename} (no change needed)", file=sys.stderr)
                skipped_count += 1
                continue
            
            print(f"  {filename} -> {new_filename}", file=sys.stderr)
            
            if not dry_run:
                # Rename English file
                new_en_file = en_dir / new_filename
                if new_en_file.exists():
                    print(f"    Warning: Target file already exists: {new_filename}", file=sys.stderr)
                    error_count += 1
                    continue
                
                shutil.move(str(en_file), str(new_en_file))
                
                # Rename Chinese file if exists
                zh_file = zh_dir / filename
                if zh_file.exists():
                    new_zh_file = zh_dir / new_filename
                    if not new_zh_file.exists():
                        shutil.move(str(zh_file), str(new_zh_file))
                    else:
                        print(f"    Warning: Chinese target file already exists: {new_filename}", file=sys.stderr)
                
                # Rename JSON metadata file
                if json_file.exists():
                    new_json_file = en_dir / new_filename.replace('.html', '.json')
                    if not new_json_file.exists():
                        shutil.move(str(json_file), str(new_json_file))
                
                # Update database
                try:
                    article = db.query(Article).filter(
                        Article.html_file_en == f"en/{filename}"
                    ).first()
                    
                    if article:
                        article.html_file_en = f"en/{new_filename}"
                        if zh_file.exists():
                            article.html_file_zh = f"zh/{new_filename}"
                        db.commit()
                        print(f"    Updated database record", file=sys.stderr)
                except Exception as e:
                    print(f"    Error updating database: {e}", file=sys.stderr)
                    db.rollback()
            
            renamed_count += 1
        
        if dry_run:
            print(f"\nDry run complete:", file=sys.stderr)
            print(f"  Would rename: {renamed_count} files", file=sys.stderr)
            print(f"  Would skip: {skipped_count} files", file=sys.stderr)
            print(f"\nRun with --execute to actually rename files", file=sys.stderr)
        else:
            print(f"\nRename complete:", file=sys.stderr)
            print(f"  Renamed: {renamed_count} files", file=sys.stderr)
            print(f"  Skipped: {skipped_count} files", file=sys.stderr)
            if error_count > 0:
                print(f"  Errors: {error_count} files", file=sys.stderr)
    
    finally:
        db.close()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Rename article files to include source identifier')
    parser.add_argument('--execute', action='store_true', help='Actually rename files (default is dry run)')
    args = parser.parse_args()
    
    rename_articles(dry_run=not args.execute)

