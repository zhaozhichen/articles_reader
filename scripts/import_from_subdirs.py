#!/usr/bin/env python3
"""
Import articles from HTML files in /en and /zh subdirectories.

Files with the same name in both directories are treated as translations.
"""
import sys
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Article
from app.config import HTML_DIR, HTML_DIR_EN, HTML_DIR_ZH

def parse_filename(filename):
    """
    Parse metadata from filename.
    
    Format: [zh_]YYYY-MM-DD_category_author_title.html
    Or: YYYY-MM-DD_category_author_title.html (same name in both dirs)
    
    Returns:
        dict with: date, category, author, title
    """
    filename = Path(filename).name
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
        'author': author.replace('_', ' '),
        'title': title.replace('_', ' '),
        'filename': filename
    }

def extract_metadata_from_html(html_path):
    """Extract additional metadata from HTML content."""
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
            canonical = soup.find('link', rel='canonical')
            if canonical and canonical.get('href'):
                metadata['url'] = canonical.get('href')
        
        # Extract title
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            metadata['title'] = og_title.get('content')
        else:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text().strip()
                title = re.sub(r'\s*\|\s*The New Yorker\s*$', '', title)
                metadata['title'] = title
        
        # Extract author
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            metadata['author'] = author_meta.get('content')
        
        return metadata
    except Exception as e:
        print(f"  Warning: Error reading {html_path}: {e}", file=sys.stderr)
        return {}

def import_articles_from_subdirs():
    """Import articles from /en and /zh subdirectories."""
    en_dir = HTML_DIR_EN
    zh_dir = HTML_DIR_ZH
    
    if not en_dir.exists():
        print(f"Error: English directory {en_dir} does not exist", file=sys.stderr)
        return
    
    # Find all HTML files in en directory
    en_files = list(en_dir.glob("*.html"))
    
    if not en_files:
        print(f"No HTML files found in {en_dir}", file=sys.stderr)
        return
    
    print(f"Found {len(en_files)} English HTML files", file=sys.stderr)
    
    db = SessionLocal()
    imported_count = 0
    updated_count = 0
    
    try:
        for en_file in en_files:
            parsed = parse_filename(en_file.name)
            if not parsed:
                print(f"  Skipping {en_file.name} (cannot parse filename)", file=sys.stderr)
                continue
            
            # Extract metadata from English file
            en_metadata = extract_metadata_from_html(en_file)
            title_en = en_metadata.get('title') or parsed['title']
            author = en_metadata.get('author') or parsed['author']
            url = en_metadata.get('url') or ''
            
            # Check for corresponding Chinese file
            zh_file = zh_dir / en_file.name
            title_zh = None
            zh_path = None
            
            if zh_file.exists():
                zh_metadata = extract_metadata_from_html(zh_file)
                title_zh = zh_metadata.get('title')
                zh_path = f"zh/{en_file.name}"
            
            # File path relative to HTML_DIR (for en file)
            en_path = f"en/{en_file.name}"
            
            # Check if article already exists
            existing = None
            if url:
                existing = db.query(Article).filter(Article.original_url == url).first()
            
            if not existing:
                # Try to find by filename
                existing = db.query(Article).filter(
                    Article.html_file_en == en_path
                ).first()
            
            if existing:
                # Update existing article
                existing.title = title_en
                existing.title_zh = title_zh
                existing.date = parsed['date']
                existing.category = parsed['category']
                existing.author = author
                existing.source = "New Yorker"
                existing.html_file_en = en_path
                existing.html_file_zh = zh_path
                existing.updated_at = datetime.utcnow()
                if url and not existing.original_url:
                    existing.original_url = url
                updated_count += 1
                print(f"  Updated: {title_en[:50]}...", file=sys.stderr)
            else:
                # Create new article
                article = Article(
                    title=title_en,
                    title_zh=title_zh,
                    date=parsed['date'],
                    category=parsed['category'],
                    author=author,
                    source="New Yorker",
                    original_url=url,
                    html_file_en=en_path,
                    html_file_zh=zh_path
                )
                db.add(article)
                imported_count += 1
                print(f"  Imported: {title_en[:50]}...", file=sys.stderr)
        
        db.commit()
        print(f"\n✅ Successfully imported {imported_count} new articles and updated {updated_count} existing articles", file=sys.stderr)
        
    except Exception as e:
        print(f"❌ Error importing articles: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()
    
    return imported_count + updated_count

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Import articles from /en and /zh subdirectories'
    )
    
    args = parser.parse_args()
    
    print(f"Importing articles from {HTML_DIR_EN} and {HTML_DIR_ZH}...", file=sys.stderr)
    count = import_articles_from_subdirs()
    print(f"Total processed: {count} articles", file=sys.stderr)
    sys.exit(0)

if __name__ == '__main__':
    main()

