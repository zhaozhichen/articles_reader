"""Service for importing articles from JSON metadata files or from /en and /zh subdirectories."""
import logging
import json
import re
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup
from app.database import SessionLocal
from app.models import Article
from app.config import HTML_DIR_EN, HTML_DIR_ZH
from app.services.scrapers import get_scraper_for_url

logger = logging.getLogger(__name__)

def is_url(text: str) -> bool:
    """Check if text is a URL."""
    if not text:
        return False
    text = text.strip()
    return (text.startswith('http://') or 
            text.startswith('https://') or 
            text.startswith('www.') or
            'facebook.com' in text.lower() or
            'twitter.com' in text.lower() or
            'linkedin.com' in text.lower() or
            'instagram.com' in text.lower() or
)

def clean_author_from_meta(author: str) -> str:
    """Clean and extract author name from meta tag content (which might be a URL).
    
    Note: This is a fallback function. Import logic now prioritizes JSON metadata
    which already contains cleaned author names. This is only used when JSON is unavailable.
    """
    if not author:
        return None
    author = author.strip()
    
    # If it's a URL, try to extract name from common patterns
    if is_url(author):
        # Try common URL patterns
        patterns = [
            (r'facebook\.com/([^/?]+)', 'facebook'),  # Facebook
        ]
        
        for pattern, source in patterns:
            match = re.search(pattern, author, re.I)
            if match:
                name = match.group(1)
                # For Facebook, remove trailing numbers
                if source == 'facebook':
                    name = re.sub(r'-\d+$', '', name)
                # Convert to readable format
                author_name = name.replace('-', ' ').replace('_', ' ').title()
                if 3 <= len(author_name) < 100:
                    return author_name
        
        return None  # Can't extract from URL
    
    # Basic validation for non-URL strings
    if (author.startswith('/') or 
        (author.count('/') > 2 and 'http' not in author) or
        len(author) < 2 or 
        author.lower() in ['unknown', 'none', 'n/a', '']):
        return None
    
    # Remove any URL patterns that might slip through
    author = re.sub(r'https?://[^\s]+', '', author).strip()
    return author if author and not is_url(author) else None

def normalize_url(url):
    """Normalize URL by removing query parameters, fragments, and trailing slashes.
    
    Args:
        url: URL string to normalize
        
    Returns:
        Normalized URL string, or None if input is empty/invalid
    """
    if not url or not url.strip():
        return None
    
    try:
        parsed = urlparse(url.strip())
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
        if normalized.endswith('/') and len(normalized) > len(parsed.scheme) + 3:  # Keep single /
            normalized = normalized[:-1]
        return normalized
    except Exception:
        return url.strip() if url else None

def extract_category_from_url(url, html=None):
    """Extract category from URL path or HTML using appropriate scraper.
    
    Examples:
    - https://aeon.co/essays/... -> 'essays'
    - https://nautil.us/... -> category from page
    
    Args:
        url: Article URL
        html: Optional HTML content (for better extraction)
    
    Returns:
        Category name as string
    """
    # Try to use scraper if available
    scraper = get_scraper_for_url(url)
    if scraper:
        if html:
            return scraper.extract_category(url, html)
        else:
            # Fallback to URL-only extraction
            return scraper.extract_category(url, '')
    
    # Fallback: basic URL parsing for unknown sources
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    
    # Common categories (fallback for unknown sources)
    categories = ['essays', 'articles', 'features', 'science', 'philosophy', 'culture']
    
    for category in categories:
        if path.startswith(f'{category}/') or path == category:
            return category
    
    # If no category found, return domain name or default
    domain = parsed.netloc.replace('www.', '')
    return domain if domain else 'Unknown'

def parse_filename_for_import(filename):
    """Parse metadata from filename.
    
    Supports two formats:
    1. New format: {date}_{source}_{category}_{author}_{title}.html
    2. Old format: {date}_{category}_{author}_{title}.html (for backward compatibility)
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
    
    # Check if it's new format (with source) or old format
    # New format has 5+ parts: date_source_category_author_title
    # Old format has 4+ parts: date_category_author_title
    
    # Known source slugs for detection
    known_sources = ['aeon', 'nautilus', 'xiaoyuzhou', 'wechat']
    
    if len(parts) >= 5 and parts[1] in known_sources:
        # New format: date_source_category_author_title
        source_slug = parts[1]
        category = parts[2]
        author = parts[3] if len(parts) > 4 else 'unknown'
        title = '_'.join(parts[4:]) if len(parts) > 4 else 'untitled'
    else:
        # Old format: date_category_author_title (backward compatibility)
        category = parts[1]
        author = parts[2] if len(parts) > 3 else 'unknown'
        title = '_'.join(parts[3:]) if len(parts) > 3 else 'untitled'
        source_slug = None  # Will be determined from URL or metadata
    
    return {
        'date': date_obj,
        'source_slug': source_slug,
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
            else:
                # Try to find URL in metadata section (for Xiaoyuzhou and other custom HTML)
                metadata_div = soup.find('div', class_='metadata')
                if metadata_div:
                    link = metadata_div.find('a')
                    if link and link.get('href'):
                        metadata['url'] = link.get('href')
        
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
                    title = re.sub(r'\s*\|\s*New Yorker\s*$', '', title)
                    metadata['title'] = title
        
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            author_name = author_meta.get('content')
            # Clean author name - handle URLs
            author_name = clean_author_from_meta(author_name)
            if author_name:
                metadata['author'] = author_name
        
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
            try:
                parsed = parse_filename_for_import(en_file.name)
                if not parsed:
                    logger.warning(f"Skipping {en_file.name} (cannot parse filename)")
                    continue
                
                # Try to read from JSON metadata file first (more reliable)
                json_file = en_dir / en_file.name.replace('.html', '.json')
                author = None
                title_en = None
                url = ''
                
                if json_file.exists():
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            json_metadata = json.load(f)
                        author = json_metadata.get('author')
                        title_en = json_metadata.get('title')
                        url = json_metadata.get('url', '')
                    except Exception as e:
                        logger.warning(f"Could not read JSON metadata from {json_file.name}: {e}")
                
                # Fallback to HTML extraction if JSON not available
                if not author or not title_en or not url:
                    en_metadata = extract_metadata_from_html_for_import(en_file)
                    title_en = title_en or en_metadata.get('title') or parsed['title']
                    author = author or en_metadata.get('author') or parsed['author']
                    url = url or en_metadata.get('url') or ''
                
                zh_file = zh_dir / en_file.name
                title_zh = None
                zh_path = None
                
                if zh_file.exists():
                    # For Chinese files, prefer h1 tag which contains the translated title
                    zh_metadata = extract_metadata_from_html_for_import(zh_file, prefer_h1=True)
                    title_zh = zh_metadata.get('title')
                    zh_path = f"zh/{en_file.name}"
                
                en_path = f"en/{en_file.name}"
                
                # Extract category and source from URL if available, otherwise use filename
                source = "Unknown"  # Default
                source_slug = parsed.get('source_slug')  # May be None for old format files
                
                if url:
                    scraper = get_scraper_for_url(url)
                    if scraper:
                        source = scraper.get_source_name()
                        source_slug = scraper.get_source_slug()
                        # Try to read HTML to get better category extraction
                        try:
                            with open(en_file, 'r', encoding='utf-8') as f:
                                html_content = f.read()
                            category = scraper.extract_category(url, html_content)
                        except Exception:
                            category = scraper.extract_category(url, '')
                    else:
                        category = extract_category_from_url(url)
                else:
                    category = parsed['category']
                    # If we have source_slug from filename but no URL, try to determine source
                    if source_slug:
                        if source_slug == 'aeon':
                            source = "Aeon"
                        elif source_slug == 'nautilus':
                            source = "Nautilus"
                        elif source_slug == 'xiaoyuzhou':
                            source = "小宇宙"
                        elif source_slug == 'wechat':
                            source = "公众号"
                        # Backward compatibility for old sources
                        elif source_slug == 'newyorker':
                            source = "New Yorker"
                        elif source_slug == 'nytimes':
                            source = "New York Times"
                        elif source_slug == 'atlantic':
                            source = "Atlantic"
                
                # Convert 'na' category to source name
                if category == 'na':
                    category = source
                
                # Check for duplicates using multiple strategies
                existing = None
                
                # Strategy 1: Exact URL match
                if url:
                    existing = db.query(Article).filter(Article.original_url == url).first()
                
                # Strategy 2: Normalized URL match (handles query params, fragments, etc.)
                if not existing and url:
                    normalized_url = normalize_url(url)
                    if normalized_url:
                        # Check against normalized versions of existing URLs
                        all_articles = db.query(Article).filter(Article.original_url != '').all()
                        for article in all_articles:
                            if normalize_url(article.original_url) == normalized_url:
                                existing = article
                                break
                
                # Strategy 3: Same filename (handles re-imports)
                if not existing:
                    existing = db.query(Article).filter(Article.html_file_en == en_path).first()
                
                # Strategy 4: Same title + author + date (handles URL variations)
                if not existing:
                    existing = db.query(Article).filter(
                        Article.title == title_en,
                        Article.author == author,
                        Article.date == parsed['date']
                    ).first()
                
                if existing:
                    existing.title = title_en
                    # Only update title_zh if:
                    # 1. We extracted a title AND it's different from English title (likely Chinese)
                    # 2. OR existing title_zh is None and we have a valid extraction
                    if title_zh and title_zh != title_en:
                        # Successfully extracted Chinese title
                        existing.title_zh = title_zh
                    elif title_zh is None and zh_file.exists() and existing.title_zh is None:
                        # Extraction failed but file exists, try fallback
                        zh_metadata_fallback = extract_metadata_from_html_for_import(zh_file, prefer_h1=False)
                        title_zh_fallback = zh_metadata_fallback.get('title')
                        if title_zh_fallback and title_zh_fallback != title_en:
                            existing.title_zh = title_zh_fallback
                    # If title_zh == title_en, extraction failed (fell back to English), preserve existing
                    existing.date = parsed['date']
                    existing.category = category
                    existing.author = author
                    existing.source = source
                    existing.html_file_en = en_path
                    # Only update html_file_zh if Chinese file exists
                    if zh_path:
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
                        source=source,
                        original_url=url,
                        html_file_en=en_path,
                        html_file_zh=zh_path
                    )
                    db.add(article)
                    imported_count += 1
                
                # Commit after each article to avoid batch failures
                db.commit()
            except Exception as e:
                # Rollback this article's transaction and continue with next
                db.rollback()
                logger.error(f"Error importing {en_file.name}: {e}", exc_info=True)
                continue
        
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
                    existing.category = metadata.get('category', 'Unknown')
                    existing.author = metadata.get('author', 'unknown')
                    existing.source = metadata.get('source', 'Unknown')
                    existing.html_file_en = metadata.get('original_file', '')
                    existing.html_file_zh = metadata.get('translated_file')
                    existing.updated_at = datetime.utcnow()
                    logger.info(f"Updated existing article: {metadata.get('url')}")
                else:
                    # Create new article
                    article = Article(
                        title=metadata.get('title', 'untitled'),
                        date=article_date,
                        category=metadata.get('category', 'Unknown'),
                        author=metadata.get('author', 'unknown'),
                        source=metadata.get('source', 'Unknown'),
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

