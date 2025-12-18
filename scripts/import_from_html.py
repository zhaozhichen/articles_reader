#!/usr/bin/env python3
"""
Import articles from HTML files in a directory.

This script scans HTML files and extracts metadata from:
1. Filename (date, category, author, title)
2. HTML content (original URL, title, etc.)

Files starting with 'zh_' are treated as Chinese translations.
"""
import sys
import re
import json
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Article
from app.config import HTML_DIR

def parse_filename(filename):
    """
    Parse metadata from filename.
    
    Format: [zh_]YYYY-MM-DD_category_author_title.html
    
    Returns:
        dict with: is_zh, date, category, author, title, original_filename
    """
    filename = Path(filename).name
    is_zh = filename.startswith('zh_')
    
    if is_zh:
        base_name = filename[3:]  # Remove 'zh_' prefix
    else:
        base_name = filename
    
    # Remove .html extension
    base_name = base_name.replace('.html', '')
    
    # Split by underscore
    parts = base_name.split('_')
    
    if len(parts) < 4:
        return None
    
    # First part is date
    date_str = parts[0]
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None
    
    # Second part is category
    category = parts[1]
    
    # Last part(s) is title, everything in between is author
    # Author might have underscores, so we need to be smart
    # Typically: date_category_author_title
    # But author and title might both have underscores
    
    # Try to find where author ends and title begins
    # Common pattern: author is usually shorter, title is longer
    # We'll take the second-to-last part as author, rest as title
    if len(parts) >= 4:
        author = parts[2] if len(parts) > 3 else 'unknown'
        title = '_'.join(parts[3:]) if len(parts) > 3 else 'untitled'
    else:
        author = 'unknown'
        title = '_'.join(parts[2:]) if len(parts) > 2 else 'untitled'
    
    return {
        'is_zh': is_zh,
        'date': date_obj,
        'category': category,
        'author': author.replace('_', ' '),
        'title': title.replace('_', ' '),
        'original_filename': filename
    }

def extract_metadata_from_html(html_path):
    """
    Extract additional metadata from HTML content.
    
    Returns:
        dict with: url, title, author (if found in HTML)
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        metadata = {}
        
        # Extract URL
        og_url = soup.find('meta', property='og:url')
        if og_url and og_url.get('content'):
            metadata['url'] = og_url.get('content')
        else:
            # Try canonical link
            canonical = soup.find('link', rel='canonical')
            if canonical and canonical.get('href'):
                metadata['url'] = canonical.get('href')
        
        # Extract title from HTML (might be more accurate)
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            metadata['title'] = og_title.get('content')
        else:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text().strip()
                # Remove " | The New Yorker" suffix if present
                title = re.sub(r'\s*\|\s*The New Yorker\s*$', '', title)
                metadata['title'] = title
        
        # Extract author from HTML
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            metadata['author'] = author_meta.get('content')
        else:
            author_meta = soup.find('meta', attrs={'name': 'author'})
            if author_meta and author_meta.get('content'):
                metadata['author'] = author_meta.get('content')
        
        return metadata
        
    except Exception as e:
        print(f"  Warning: Error reading {html_path}: {e}", file=sys.stderr)
        return {}

def import_articles_from_directory(directory):
    """
    Import articles from HTML files in the directory.
    
    Args:
        directory: Path to directory containing HTML files
    """
    directory = Path(directory)
    if not directory.exists():
        print(f"Error: Directory {directory} does not exist", file=sys.stderr)
        return
    
    # Find all HTML files
    html_files = list(directory.rglob("*.html"))
    
    if not html_files:
        print(f"No HTML files found in {directory}", file=sys.stderr)
        return
    
    print(f"Found {len(html_files)} HTML files", file=sys.stderr)
    
    # Separate English and Chinese files
    en_files = {}
    zh_files = {}
    
    for html_file in html_files:
        parsed = parse_filename(html_file.name)
        if not parsed:
            print(f"  Skipping {html_file.name} (cannot parse filename)", file=sys.stderr)
            continue
        
        # Get relative path from directory
        rel_path = html_file.relative_to(directory)
        
        if parsed['is_zh']:
            # This is a Chinese translation
            # Find matching English file
            base_name = parsed['original_filename'][3:]  # Remove 'zh_' prefix
            key = (parsed['date'], parsed['category'], parsed['author'])
            zh_files[key] = {
                'path': str(rel_path),
                'parsed': parsed,
                'html_metadata': extract_metadata_from_html(html_file)
            }
        else:
            # This is an English file
            key = (parsed['date'], parsed['category'], parsed['author'])
            en_files[key] = {
                'path': str(rel_path),
                'parsed': parsed,
                'html_metadata': extract_metadata_from_html(html_file)
            }
    
    print(f"Found {len(en_files)} English articles and {len(zh_files)} Chinese translations", file=sys.stderr)
    
    # Import to database
    db = SessionLocal()
    imported_count = 0
    updated_count = 0
    
    try:
        for key, en_data in en_files.items():
            parsed = en_data['parsed']
            html_meta = en_data['html_metadata']
            
            # Merge metadata: HTML content takes precedence for title/author/url
            title = html_meta.get('title') or parsed['title']
            author = html_meta.get('author') or parsed['author']
            url = html_meta.get('url') or ''
            
            # Find matching Chinese file
            zh_data = zh_files.get(key)
            zh_path = None
            if zh_data:
                zh_path = zh_data['path']
                # Use Chinese title if available
                zh_title = zh_data['html_metadata'].get('title')
            
            # Check if article already exists
            existing = None
            if url:
                existing = db.query(Article).filter(Article.original_url == url).first()
            
            # If not found by URL, try by filename
            if not existing:
                existing = db.query(Article).filter(
                    Article.html_file_en == en_data['path']
                ).first()
            
            if existing:
                # Update existing article
                existing.title = title
                existing.title_zh = zh_data['html_metadata'].get('title') if zh_data else None
                existing.date = parsed['date']
                existing.category = parsed['category']
                existing.author = author
                existing.source = "New Yorker"
                existing.html_file_en = en_data['path']
                existing.html_file_zh = zh_path
                existing.updated_at = datetime.utcnow()
                if url and not existing.original_url:
                    existing.original_url = url
                updated_count += 1
                print(f"  Updated: {title[:50]}...", file=sys.stderr)
            else:
                # Create new article
                article = Article(
                    title=title,
                    title_zh=zh_data['html_metadata'].get('title') if zh_data else None,
                    date=parsed['date'],
                    category=parsed['category'],
                    author=author,
                    source="New Yorker",
                    original_url=url,
                    html_file_en=en_data['path'],
                    html_file_zh=zh_path
                )
                db.add(article)
                imported_count += 1
                print(f"  Imported: {title[:50]}...", file=sys.stderr)
        
        db.commit()
        print(f"\nSuccessfully imported {imported_count} new articles and updated {updated_count} existing articles", file=sys.stderr)
        
    except Exception as e:
        print(f"Error importing articles: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()
    
    return imported_count + updated_count

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Import articles from HTML files in a directory'
    )
    parser.add_argument(
        '--directory',
        type=str,
        default=None,
        help=f'Directory containing HTML files (default: {HTML_DIR})'
    )
    
    args = parser.parse_args()
    
    directory = Path(args.directory) if args.directory else HTML_DIR
    
    if not directory.exists():
        print(f"Error: Directory {directory} does not exist", file=sys.stderr)
        sys.exit(1)
    
    print(f"Importing articles from {directory}...", file=sys.stderr)
    count = import_articles_from_directory(directory)
    print(f"Total processed: {count} articles", file=sys.stderr)
    sys.exit(0)

if __name__ == '__main__':
    main()

