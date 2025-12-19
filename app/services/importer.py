"""Service for importing articles from JSON metadata files or from /en and /zh subdirectories."""
import logging
import json
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup
from app.database import SessionLocal
from app.models import Article
from app.config import HTML_DIR_EN, HTML_DIR_ZH

logger = logging.getLogger(__name__)

def extract_category_from_url(url):
    """Extract category from URL path.
    
    Examples:
    - https://www.newyorker.com/books/book-currents/... -> 'books'
    - https://www.newyorker.com/culture/postscript/... -> 'culture'
    - https://www.newyorker.com/podcast/critics-at-large/... -> 'podcast'
    - https://www.newyorker.com/best-books-2025 -> 'The New Yorker'
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    
    # Common categories to look for
    categories = ['news', 'books', 'culture', 'magazine', 'humor', 'cartoons', 
                  'puzzles-and-games-dept', 'newsletter', 'video', 'podcast', 'podcasts']
    
    for category in categories:
        if path.startswith(f'{category}/') or path == category:
            return category
    
    # If no category found, return 'The New Yorker'
    return 'The New Yorker'

def parse_filename_for_import(filename):
    """Parse metadata from filename."""
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

def extract_metadata_from_html_for_import(html_path, prefer_h1=False):
    """
    Extract metadata from HTML content.
    
    Args:
        html_path: Path to HTML file
        prefer_h1: If True, prefer h1 tag over meta tags for title (useful for Chinese translations)
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        soup = BeautifulSoup(html_content, 'html.parser')
        metadata = {}
        
        og_url = soup.find('meta', property='og:url')
        if og_url and og_url.get('content'):
            metadata['url'] = og_url.get('content')
        else:
            canonical = soup.find('link', rel='canonical')
            if canonical and canonical.get('href'):
                metadata['url'] = canonical.get('href')
        
        # Extract title - prefer h1 for translated content
        if prefer_h1:
            h1 = soup.find('h1')
            if h1:
                title = h1.get_text().strip()
                if title and len(title) >= 1:  # Valid title (allow short Chinese titles)
                    metadata['title'] = title
        
        # Fallback to meta tags if h1 not found or not preferred
        if 'title' not in metadata:
            og_title = soup.find('meta', property='og:title')
            if og_title and og_title.get('content'):
                metadata['title'] = og_title.get('content')
            else:
                title_tag = soup.find('title')
                if title_tag:
                    title = title_tag.get_text().strip()
                    title = re.sub(r'\s*\|\s*The New Yorker\s*$', '', title)
                    metadata['title'] = title
        
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            metadata['author'] = author_meta.get('content')
        
        return metadata
    except Exception as e:
        return {}

def import_from_subdirs_inline(en_dir, zh_dir):
    """Import articles from en/ and zh/ subdirectories."""
    en_files = list(en_dir.glob("*.html"))
    
    if not en_files:
        logger.info("No HTML files found in English directory")
        return 0
    
    logger.info(f"Found {len(en_files)} English HTML files")
    
    db = SessionLocal()
    imported_count = 0
    updated_count = 0
    
    try:
        for en_file in en_files:
            parsed = parse_filename_for_import(en_file.name)
            if not parsed:
                logger.warning(f"Skipping {en_file.name} (cannot parse filename)")
                continue
            
            en_metadata = extract_metadata_from_html_for_import(en_file)
            title_en = en_metadata.get('title') or parsed['title']
            author = en_metadata.get('author') or parsed['author']
            url = en_metadata.get('url') or ''
            
            zh_file = zh_dir / en_file.name
            title_zh = None
            zh_path = None
            
            if zh_file.exists():
                # For Chinese files, prefer h1 tag which contains the translated title
                zh_metadata = extract_metadata_from_html_for_import(zh_file, prefer_h1=True)
                title_zh = zh_metadata.get('title')
                zh_path = f"zh/{en_file.name}"
            
            en_path = f"en/{en_file.name}"
            
            # Extract category from URL if available, otherwise use filename
            if url:
                category = extract_category_from_url(url)
            else:
                category = parsed['category']
            
            # Convert 'na' category to 'The New Yorker'
            if category == 'na':
                category = 'The New Yorker'
            
            existing = None
            if url:
                existing = db.query(Article).filter(Article.original_url == url).first()
            
            if not existing:
                existing = db.query(Article).filter(Article.html_file_en == en_path).first()
            
            if existing:
                existing.title = title_en
                existing.title_zh = title_zh
                existing.date = parsed['date']
                existing.category = category
                existing.author = author
                existing.html_file_en = en_path
                existing.html_file_zh = zh_path
                existing.updated_at = datetime.utcnow()
                if url and not existing.original_url:
                    existing.original_url = url
                updated_count += 1
            else:
                article = Article(
                    title=title_en,
                    title_zh=title_zh,
                    date=parsed['date'],
                    category=category,
                    author=author,
                    source="The New Yorker",
                    original_url=url,
                    html_file_en=en_path,
                    html_file_zh=zh_path
                )
                db.add(article)
                imported_count += 1
        
        db.commit()
        logger.info(f"Successfully imported {imported_count} new articles and updated {updated_count} existing articles")
        
    except Exception as e:
        logger.error(f"Error importing articles: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()
    
    return imported_count + updated_count

def import_articles_from_directory(directory: Path) -> int:
    """
    Import articles from JSON metadata files or from /en and /zh subdirectories.
    
    Args:
        directory: Directory containing HTML files (if None, uses HTML_DIR_EN)
        
    Returns:
        Number of articles imported
    """
    if directory is None:
        directory = HTML_DIR_EN
    
    db = SessionLocal()
    imported_count = 0
    
    try:
        # Check if we're using subdirectory structure (en/zh)
        en_dir = directory if directory.name == 'en' else HTML_DIR_EN
        zh_dir = en_dir.parent / 'zh' if en_dir.name == 'en' else HTML_DIR_ZH
        
        # Check if we're using subdirectory structure (en/zh)
        # If en_dir exists and is a directory, use subdirectory import logic
        if en_dir.exists() and en_dir.is_dir():
            # Import from subdirectories - files with same name in en/ and zh/
            en_files = list(en_dir.glob("*.html"))
            if en_files:
                # Use subdirectory import logic inline
                return import_from_subdirs_inline(en_dir, zh_dir)
        
        # Fallback: Find all JSON metadata files (old structure)
        json_files = list(directory.glob("*.json"))
        
        logger.info(f"Found {len(json_files)} JSON metadata files")
        
        for json_file in json_files:
            try:
                # Skip translated file metadata (zh_ prefix)
                if json_file.name.startswith('zh_'):
                    continue
                
                # Read metadata
                with open(json_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # Parse date - convert to datetime for database
                try:
                    date_str = metadata['date']
                    # Parse as date first, then convert to datetime
                    article_date = datetime.strptime(date_str, '%Y-%m-%d')
                except (ValueError, KeyError):
                    logger.warning(f"Invalid date in {json_file.name}, skipping")
                    continue
                
                # Check if article already exists (by original_url)
                existing = db.query(Article).filter(
                    Article.original_url == metadata.get('url')
                ).first()
                
                if existing:
                    # Update existing article
                    existing.title = metadata.get('title', 'untitled')
                    existing.date = article_date
                    existing.category = metadata.get('category', 'The New Yorker')
                    existing.author = metadata.get('author', 'unknown')
                    existing.source = metadata.get('source', 'The New Yorker')
                    existing.html_file_en = metadata.get('original_file', '')
                    existing.html_file_zh = metadata.get('translated_file')
                    existing.updated_at = datetime.utcnow()
                    logger.info(f"Updated existing article: {metadata.get('url')}")
                else:
                    # Create new article
                    article = Article(
                        title=metadata.get('title', 'untitled'),
                        date=article_date,
                        category=metadata.get('category', 'The New Yorker'),
                        author=metadata.get('author', 'unknown'),
                        source=metadata.get('source', 'The New Yorker'),
                        original_url=metadata.get('url', ''),
                        html_file_en=metadata.get('original_file', ''),
                        html_file_zh=metadata.get('translated_file')
                    )
                    db.add(article)
                    logger.info(f"Created new article: {metadata.get('url')}")
                    imported_count += 1
                
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {json_file.name}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error processing {json_file.name}: {e}", exc_info=True)
                continue
        
        # Commit all changes
        db.commit()
        logger.info(f"Successfully imported {imported_count} new articles")
        
    except Exception as e:
        logger.error(f"Error importing articles: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()
    
    return imported_count

