#!/usr/bin/env python3
"""
Script to extract article URLs from The New Yorker's /latest pages
that match a given publish date.

process all articles by date, and translate them to Simplified Chinese:
python extract_articles_by_date.py --date "2025-12-17" --translate --output-dir ./articles

translate single article to Simplified Chinese:
python extract_artidsfacles_by_date.py --url "https://www.newyorker.com/culture/postscript/rob-reiner-made-a-new-kind-of-fairy-tale" --translate --output-dir ./articles
"""

import re
import json
import sys
import os
import argparse
import time
import random
from datetime import datetime
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional, will use system env vars if not available

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


def fetch_page(url, max_retries=3):
    """Fetch a page with retries and random delays to reduce IP ban risk."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Random delay after successful request (3-7 seconds) to reduce IP ban risk
            delay = random.uniform(3, 7)
            print(f"    Waiting {delay:.1f}s before next request...", file=sys.stderr)
            time.sleep(delay)
            
            return response.text
        except requests.RequestException as e:
            if attempt == max_retries - 1:
                print(f"Error fetching {url}: {e}", file=sys.stderr)
                return None
            # Wait before retry
            delay = random.uniform(3, 7)
            print(f"    Retry after {delay:.1f}s...", file=sys.stderr)
            time.sleep(delay)
            continue
    return None


def extract_article_urls_from_page(html_content):
    """Extract article URLs from a /latest page using JSON-LD data."""
    urls = []
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find JSON-LD script tag
    json_ld_script = soup.find('script', type='application/ld+json')
    if json_ld_script:
        try:
            data = json.loads(json_ld_script.string)
            if data.get('@type') == 'ItemList' and 'itemListElement' in data:
                for item in data['itemListElement']:
                    if isinstance(item, dict) and 'url' in item:
                        url = item['url']
                        # Only include actual article URLs, not other pages
                        if url.startswith('https://www.newyorker.com/') and \
                           not url.endswith('/latest') and \
                           '/latest?' not in url:
                            urls.append(url)
        except json.JSONDecodeError:
            pass
    
    return urls


def extract_publish_date(article_html):
    """Extract publish date from article HTML.
    
    Returns a tuple of (publish_date, modified_date) where either may be None.
    This allows the caller to check both dates when matching.
    """
    soup = BeautifulSoup(article_html, 'html.parser')
    
    # Get publish date
    publish_date = None
    meta_tag = soup.find('meta', property='article:published_time')
    if meta_tag and meta_tag.get('content'):
        date_str = meta_tag['content']
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            publish_date = dt.date()
        except (ValueError, AttributeError):
            pass
    
    # Get modified date
    modified_date = None
    modified_tag = soup.find('meta', property='article:modified_time')
    if modified_tag and modified_tag.get('content'):
        date_str = modified_tag['content']
        try:
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            modified_date = dt.date()
        except (ValueError, AttributeError):
            pass
    
    return (publish_date, modified_date)


def get_article_date(url):
    """Fetch an article and return its publish and modified dates.
    
    Returns a tuple of (publish_date, modified_date) where either may be None.
    """
    html = fetch_page(url)
    if html:
        return extract_publish_date(html)
    return (None, None)


def extract_category_from_url(url):
    """Extract category from URL path.
    
    Examples:
    - https://www.newyorker.com/books/book-currents/... -> 'books'
    - https://www.newyorker.com/culture/postscript/... -> 'culture'
    - https://www.newyorker.com/best-books-2025 -> 'The New Yorker'
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')
    
    # Common categories to look for
    categories = ['news', 'books', 'culture', 'magazine', 'humor', 'cartoons', 'archive', 'crossword-puzzles-and-games', 'goings-on', 
                  'puzzles-and-games-dept', 'newsletter', 'video', 'fiction-and-poetry', 'podcasts', 'podcast']
    
    for category in categories:
        if path.startswith(f'{category}/') or path == category:
            return category
    
    # If no category found, return 'The New Yorker'
    return 'The New Yorker'


def extract_author_from_html(html_content):
    """Extract author name from article HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Try meta tag first
    author_meta = soup.find('meta', property='article:author')
    if author_meta and author_meta.get('content'):
        return author_meta.get('content')
    
    # Try meta name="author"
    author_meta = soup.find('meta', attrs={'name': 'author'})
    if author_meta and author_meta.get('content'):
        return author_meta.get('content')
    
    # Try JSON-LD
    json_ld_scripts = soup.find_all('script', type='application/ld+json')
    for script in json_ld_scripts:
        try:
            data = json.loads(script.string)
            if isinstance(data, dict):
                # Check for author in various formats
                if 'author' in data:
                    author = data['author']
                    if isinstance(author, dict) and 'name' in author:
                        return author['name']
                    elif isinstance(author, list) and len(author) > 0:
                        if isinstance(author[0], dict) and 'name' in author[0]:
                            return author[0]['name']
                        elif isinstance(author[0], str):
                            return author[0]
                    elif isinstance(author, str):
                        return author
        except (json.JSONDecodeError, KeyError):
            continue
    
    return 'unknown'


def extract_title_from_html(html_content):
    """Extract article title from HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Try og:title meta tag first
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        return og_title.get('content')
    
    # Try title tag
    title_tag = soup.find('title')
    if title_tag:
        title = title_tag.get_text().strip()
        # Remove " | The New Yorker" suffix if present
        title = re.sub(r'\s*\|\s*The New Yorker\s*$', '', title)
        return title
    
    return 'untitled'


def sanitize_filename(text):
    """Sanitize text for use in filenames."""
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


def extract_article_body(html_content):
    """Extract the main article body content from HTML.
    
    Returns a tuple of (body_html, body_element) where body_html is the HTML
    of the body section and body_element is the BeautifulSoup element.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Try to find article body using common selectors
    body_element = None
    
    # Try different selectors for article body
    selectors = [
        ('article', {}),
        ('.body__container', {}),
        ('.container--body-inner', {}),
        ('main', {}),
        ('[class*="body"]', {}),
        ('[class*="article"]', {}),
        ('[class*="content"]', {}),
    ]
    
    for selector, attrs in selectors:
        if selector.startswith('['):
            # Attribute selector
            body_element = soup.select_one(selector)
        else:
            body_element = soup.find(selector.split('.')[-1] if '.' in selector else selector, attrs)
        
        if body_element:
            # Check if it has substantial text content
            text_content = body_element.get_text(strip=True)
            if len(text_content) > 200:  # Has meaningful content
                break
    
    if not body_element:
        # Fallback: find the largest text-containing div
        all_divs = soup.find_all(['div', 'section', 'article'])
        max_text_length = 0
        for div in all_divs:
            text = div.get_text(strip=True)
            if len(text) > max_text_length:
                max_text_length = len(text)
                body_element = div
        
        if max_text_length < 200:
            return None, None
    
    return str(body_element), body_element


def translate_html_with_gemini_retry(html_content, api_key=None, max_retries=2):
    """Translate HTML with retry mechanism.
    
    Args:
        html_content: Original HTML content
        api_key: Gemini API key (if None, uses GEMINI_API_KEY env var)
        max_retries: Maximum number of retries (default: 2, total attempts: 3)
    
    Returns:
        Translated HTML content, or None if all attempts fail
    """
    for attempt in range(max_retries + 1):  # 0, 1, 2 = 3 attempts total
        if attempt > 0:
            delay = random.uniform(5, 15)  # Wait 5-15 seconds before retry
            print(f"    Retry attempt {attempt}/{max_retries} after {delay:.1f}s delay...", file=sys.stderr)
            time.sleep(delay)
        
        result = translate_html_with_gemini(html_content, api_key)
        if result is not None:
            if attempt > 0:
                print(f"    Translation succeeded on attempt {attempt + 1}", file=sys.stderr)
            return result
        else:
            if attempt < max_retries:
                print(f"    Translation failed on attempt {attempt + 1}/{max_retries + 1}, will retry...", file=sys.stderr)
            else:
                print(f"    Translation failed after {max_retries + 1} attempts, giving up", file=sys.stderr)
    
    return None


def translate_html_with_gemini(html_content, api_key=None):
    """Translate only the article body content to Simplified Chinese using Gemini 3 Pro.
    
    Only translates the main article body, keeping navigation, scripts, styles, etc. in English.
    
    Args:
        html_content: Original HTML content
        api_key: Gemini API key (if None, uses GEMINI_API_KEY env var)
    
    Returns:
        Translated HTML content with only body translated, or None if translation fails
    """
    if not GEMINI_AVAILABLE:
        print("  Warning: google.genai not installed. Install with: pip install google-genai", file=sys.stderr)
        return None
    
    # Get API key (the client gets it from GEMINI_API_KEY env var automatically)
    # But we can check if it's set
    if api_key is None:
        api_key = os.getenv('GEMINI_API_KEY')
    
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set. Skipping translation.", file=sys.stderr)
        return None
    
    try:
        # Extract article body
        print("    Extracting article body content...", file=sys.stderr)
        body_html, body_element = extract_article_body(html_content)
        
        if not body_html or not body_element:
            print("  Warning: Could not find article body content", file=sys.stderr)
            return None
        
        body_size = len(body_html)
        print(f"    Found article body (size: {body_size} chars)", file=sys.stderr)
        
        # Maximum size for single translation
        MAX_SINGLE_TRANSLATION = 200000
        
        # Check if body is too long to translate
        if body_size > MAX_SINGLE_TRANSLATION:
            print(f"    Article body is too long ({body_size:,} chars), skipping translation and showing placeholder", file=sys.stderr)
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find the body element to replace
            original_body = None
            for selector in [('article', {}), ('.body__container', {}), ('.container--body-inner', {}), ('main', {})]:
                if selector[0].startswith('.'):
                    original_body = soup.select_one(selector[0])
                else:
                    tag_name = selector[0].split('.')[-1] if '.' in selector[0] else selector[0]
                    original_body = soup.find(tag_name, selector[1])
                if original_body:
                    break
            
            if original_body:
                # Create placeholder message with size information
                placeholder_html = f'<div style="padding: 2rem; text-align: center; font-family: Arial, sans-serif;"><p style="font-size: 18px; color: #666;">文章过长，无法翻译</p><p style="font-size: 14px; color: #999; margin-top: 1rem;">Article too long to translate, size: {body_size:,} characters</p></div>'
                placeholder_soup = BeautifulSoup(placeholder_html, 'html.parser')
                
                # Replace body content with placeholder
                original_body.clear()
                original_body.append(placeholder_soup.find('div'))
                
                return str(soup)
            else:
                # If we can't find the body, return original HTML with a note
                print("  Warning: Could not locate body element for placeholder insertion", file=sys.stderr)
                return html_content
        
        # The client gets the API key from the environment variable `GEMINI_API_KEY`
        client = genai.Client()
        
        # Create prompt for translation
        prompt = """请将以下HTML内容翻译成简体中文。

翻译流程：
第一步：仔细阅读全文
- 先完整阅读整篇文章，理解文章的主题、内容和结构
- 分析文章的行文风格（正式、轻松、学术、新闻等）
- 识别文章的语气和语调（严肃、幽默、批判、客观等）
- 注意文章的文体特征（叙述、议论、描写等）
- 理解文章的语境和背景

第二步：进行翻译
- 基于对文章风格和语气的理解，进行翻译
- 确保翻译非常流畅，完全符合现代汉语的写作习惯
- 使用自然、地道的现代汉语表达
- 避免生硬的直译，要意译为主，确保可读性
- 保持原文的风格和语气特征
- 专业术语要准确，但表达要符合中文习惯

技术性要求：
1. 只翻译文本内容，保留所有HTML标签、属性和结构完全不变
2. 保持所有图片URL、资源路径和链接不变
3. 保持所有CSS类、ID和数据属性不变
4. 不翻译代码、URL或技术属性
5. 保持HTML结构和格式完全不变
6. 返回完整的翻译后的HTML（只包含这个body部分的HTML）

请开始翻译：

HTML内容：
""" + body_html
        
        # Generate translation using gemini-3-pro-preview
        print(f"    Sending article body to Gemini (size: {len(body_html)} chars)...", file=sys.stderr)
        
        response = client.models.generate_content(
            model="gemini-3-pro-preview",
            contents=prompt
        )
        
        # Check if response is valid
        if not response:
            print("  Error: Empty response from Gemini API", file=sys.stderr)
            return None
        
        # Get text from response - handle different response formats
        translated_html = None
        try:
            if hasattr(response, 'text') and response.text:
                translated_html = response.text
            elif hasattr(response, 'candidates') and len(response.candidates) > 0:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content'):
                    if hasattr(candidate.content, 'parts') and len(candidate.content.parts) > 0:
                        translated_html = candidate.content.parts[0].text
                    elif hasattr(candidate.content, 'text'):
                        translated_html = candidate.content.text
            else:
                # Try to convert response to string
                translated_html = str(response)
        except Exception as e:
            print(f"  Error extracting text from response: {e}", file=sys.stderr)
            print(f"  Response type: {type(response)}", file=sys.stderr)
            if hasattr(response, '__dict__'):
                print(f"  Response attributes: {list(response.__dict__.keys())}", file=sys.stderr)
            return None
        
        if not translated_html or len(translated_html.strip()) == 0:
            print("  Error: Translation result is empty", file=sys.stderr)
            return None
        
        print(f"    Received translation (size: {len(translated_html)} chars)", file=sys.stderr)
        
        # Clean up the response (sometimes Gemini adds markdown formatting)
        # Remove markdown code blocks if present
        if translated_html.startswith('```html'):
            translated_html = translated_html[7:]
        elif translated_html.startswith('```'):
            translated_html = translated_html[3:]
        if translated_html.endswith('```'):
            translated_html = translated_html[:-3]
        translated_html = translated_html.strip()
        
        # Verify we got substantial HTML content
        if len(translated_html) < len(html_content) * 0.1:
            print(f"  Warning: Translation seems too short ({len(translated_html)} vs original {len(html_content)} chars)", file=sys.stderr)
            print(f"  This might indicate the translation was truncated or incomplete", file=sys.stderr)
        
        # Verify basic HTML structure
        if not translated_html or len(translated_html.strip()) < 100:
            print(f"  Warning: Translation result seems too short", file=sys.stderr)
            return None
        
        # Replace the original body with translated body in the full HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        translated_body_soup = BeautifulSoup(translated_html, 'html.parser')
        
        # Use the body_element we found earlier (passed as a reference)
        # We need to find it again in the soup since we created a new soup object
        original_body = None
        for selector in [('article', {}), ('.body__container', {}), ('.container--body-inner', {}), ('main', {})]:
            if selector[0].startswith('.'):
                original_body = soup.select_one(selector[0])
            else:
                tag_name = selector[0].split('.')[-1] if '.' in selector[0] else selector[0]
                original_body = soup.find(tag_name, selector[1])
            if original_body:
                break
        
        if original_body:
            # Replace the original body content with translated content
            original_body.clear()
            # Get the translated body's root element
            translated_root = translated_body_soup.find()
            if translated_root:
                # Copy all children from translated root to original body
                for child in list(translated_root.children):
                    original_body.append(child)
            else:
                # If no root element found, append the whole translated soup
                for child in list(translated_body_soup.children):
                    original_body.append(child)
            
            print(f"    Replaced article body with translated version", file=sys.stderr)
            # Return the modified full HTML
            return str(soup)
        else:
            # If we can't find the body element, try to use body_element directly
            if body_element:
                # Create a new soup from original and replace
                soup = BeautifulSoup(html_content, 'html.parser')
                # Find the element by its position or attributes
                body_element.clear()
                translated_root = translated_body_soup.find()
                if translated_root:
                    for child in list(translated_root.children):
                        body_element.append(child)
                return str(soup)
            else:
                print("  Warning: Could not locate body element for replacement", file=sys.stderr)
                return None
        
    except Exception as e:
        print(f"  Error translating with Gemini: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return None


def save_article_html(url, target_date=None, output_dir='.', translate=False, gemini_api_key=None, zh_dir=None):
    """Save article HTML to a file with proper naming.
    
    Args:
        url: Article URL
        target_date: Target date for filename (if None, will extract from article)
        output_dir: Output directory for English files (default: current directory)
        translate: Whether to also create a Chinese translation
        gemini_api_key: Gemini API key for translation
        zh_dir: Directory for Chinese translations (if None, uses output_dir with zh_ prefix)
    
    Returns:
        Tuple of (original_filepath, translated_filepath) where translated_filepath may be None
    """
    # Extract category from URL (still used in filename)
    category = extract_category_from_url(url)
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Fetch the HTML
    html = fetch_page(url)
    if not html:
        print(f"  Failed to fetch HTML for {url}", file=sys.stderr)
        return (None, None)
    
    # Extract metadata
    author = extract_author_from_html(html)
    title = extract_title_from_html(html)
    
    # Get date - use provided date or extract from article
    if target_date is None:
        publish_date, modified_date = extract_publish_date(html)
        # Use modified date if available, otherwise publish date
        article_date = modified_date if modified_date else publish_date
        if article_date:
            date_str = article_date.strftime('%Y-%m-%d')
        else:
            # Fallback to today's date if no date found
            date_str = datetime.now().date().strftime('%Y-%m-%d')
    else:
        date_str = target_date.strftime('%Y-%m-%d')
    
    # Sanitize components
    category_safe = sanitize_filename(category)
    author_safe = sanitize_filename(author)
    title_safe = sanitize_filename(title)
    
    # Build filename: date_category_author_article_title.html
    filename = f"{date_str}_{category_safe}_{author_safe}_{title_safe}.html"
    filepath = os.path.join(output_dir, filename)
    
    # Save the original HTML
    translated_filepath = None
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html)
        
        # Translate if requested (with retry mechanism)
        if translate:
            print(f"    Translating to Simplified Chinese...", file=sys.stderr)
            translated_html = translate_html_with_gemini_retry(html, gemini_api_key, max_retries=2)
            if translated_html:
                # If zh_dir is specified, save to that directory with same filename
                # Otherwise, use zh_ prefix in same directory (backward compatibility)
                if zh_dir:
                    os.makedirs(zh_dir, exist_ok=True)
                    translated_filepath = os.path.join(zh_dir, filename)  # Same filename, different dir
                else:
                    translated_filename = f"zh_{filename}"
                    translated_filepath = os.path.join(output_dir, translated_filename)
                with open(translated_filepath, 'w', encoding='utf-8') as f:
                    f.write(translated_html)
                print(f"    Saved translation to: {translated_filepath}", file=sys.stderr)
            else:
                print(f"    Translation failed, skipping", file=sys.stderr)
        
        # Create and save metadata JSON file
        # For translated file path, use relative path if zh_dir is specified
        if translated_filepath and zh_dir:
            translated_file_rel = os.path.relpath(translated_filepath, output_dir)
        elif translated_filepath:
            translated_file_rel = os.path.basename(translated_filepath)
        else:
            translated_file_rel = None
        
        metadata = {
            "date": date_str,
            "category": category,
            "author": author,
            "source": "The New Yorker",  # Fixed value, can be extended in the future
            "title": title,
            "url": url,
            "original_file": filename,
            "translated_file": translated_file_rel
        }
        
        # Save metadata to JSON file (same name as HTML but with .json extension)
        metadata_filename = filename.replace('.html', '.json')
        metadata_filepath = os.path.join(output_dir, metadata_filename)
        with open(metadata_filepath, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"    Saved metadata to: {metadata_filepath}", file=sys.stderr)
        
        return (filepath, translated_filepath)
    except Exception as e:
        print(f"  Error saving {url}: {e}", file=sys.stderr)
        return (None, None)


def find_articles_by_date(target_date, max_pages=100, max_workers=10):
    """
    Find all articles published on the target date.
    
    Since articles are in reverse chronological order, we can stop early
    when we find a page where all articles are older than the target date.
    
    Args:
        target_date: datetime.date object for the target date
        max_pages: Maximum number of pages to check
        max_workers: Number of concurrent workers for fetching articles
    
    Returns:
        List of article URLs matching the date
    """
    matching_urls = []
    page = 1
    
    print(f"Searching for articles published on {target_date}...", file=sys.stderr)
    print(f"Scanning /latest pages (will stop early if all articles are older)...", file=sys.stderr)
    
    # Process pages one by one, checking dates as we go
    while page <= max_pages:
        url = f"https://www.newyorker.com/latest?page={page}"
        print(f"\nFetching page {page}...", file=sys.stderr)
        
        html = fetch_page(url)
        if not html:
            print(f"Failed to fetch page {page}, stopping.", file=sys.stderr)
            break
        
        article_urls = extract_article_urls_from_page(html)
        
        if not article_urls:
            print(f"No articles found on page {page}, stopping.", file=sys.stderr)
            break
        
        print(f"Found {len(article_urls)} articles on page {page}. Checking dates...", file=sys.stderr)
        
        # Check publish dates for articles on this page
        page_article_dates = {}
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {
                executor.submit(get_article_date, url): url 
                for url in article_urls
            }
            
            completed = 0
            for future in as_completed(future_to_url):
                article_url = future_to_url[future]
                completed += 1
                try:
                    publish_date, modified_date = future.result()
                    page_article_dates[article_url] = (publish_date, modified_date)
                    
                    # Check if either publish or modified date matches target
                    matches = False
                    date_str = ""
                    if publish_date == target_date:
                        matches = True
                        date_str = f"publish: {publish_date}"
                    elif modified_date == target_date:
                        matches = True
                        date_str = f"modified: {modified_date}"
                    elif publish_date and modified_date:
                        date_str = f"publish: {publish_date}, modified: {modified_date}"
                    elif publish_date:
                        date_str = f"publish: {publish_date}"
                    elif modified_date:
                        date_str = f"modified: {modified_date}"
                    
                    if matches:
                        matching_urls.append(article_url)
                        print(f"  [{completed}/{len(article_urls)}] ✓ {article_url} ({date_str})", file=sys.stderr)
                    elif publish_date or modified_date:
                        # Determine if article is newer or older
                        check_date = modified_date if modified_date else publish_date
                        if check_date > target_date:
                            print(f"  [{completed}/{len(article_urls)}] ✗ {article_url} ({date_str}, newer)", file=sys.stderr)
                        else:
                            print(f"  [{completed}/{len(article_urls)}] ✗ {article_url} ({date_str}, older)", file=sys.stderr)
                    else:
                        # Couldn't determine date
                        print(f"  [{completed}/{len(article_urls)}] ✗ {article_url} (date: not found)", file=sys.stderr)
                except Exception as e:
                    print(f"  [{completed}/{len(article_urls)}] Error processing {article_url}: {e}", file=sys.stderr)
        
        # Check if all articles on this page are older than target date
        # Only stop if we have dates for all articles AND all are older
        dates_found = []
        for publish_date, modified_date in page_article_dates.values():
            # Use modified date if available, otherwise publish date
            check_date = modified_date if modified_date else publish_date
            if check_date:
                dates_found.append(check_date)
        
        if len(dates_found) == len(article_urls) and len(dates_found) > 0:
            # All articles have dates, check if all are older
            all_older = all(date < target_date for date in dates_found)
            if all_older:
                print(f"\nAll articles on page {page} are older than {target_date}. Stopping early.", file=sys.stderr)
                break
        
        page += 1
    
    return matching_urls


def process_single_url(url, output_dir='.', translate=False, gemini_api_key=None, zh_dir=None):
    """Process a single article URL: save and optionally translate it.
    
    Args:
        url: Article URL to process
        output_dir: Output directory for saved HTML files
        translate: Whether to also create a Chinese translation
        gemini_api_key: Gemini API key for translation
        zh_dir: Directory for Chinese translations
    
    Returns:
        0 on success, 1 on failure
    """
    print(f"Processing article: {url}", file=sys.stderr)
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    if translate:
        print(f"Translation enabled: Will create Simplified Chinese version", file=sys.stderr)
    
    # Save and translate the article
    original_path, translated_path = save_article_html(
        url, target_date=None, output_dir=output_dir,
        translate=translate,
        gemini_api_key=gemini_api_key,
        zh_dir=zh_dir
    )
    
    if original_path:
        print(f"Successfully saved to: {original_path}", file=sys.stderr)
        if translated_path:
            print(f"Successfully translated to: {translated_path}", file=sys.stderr)
        return 0
    else:
        print(f"Failed to save article", file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description='Extract article URLs from The New Yorker /latest pages by publish date and save HTML files, or process a single URL'
    )
    parser.add_argument(
        'date',
        type=str,
        nargs='?',
        help='Target date in YYYY-MM-DD format (e.g., 2025-12-15). Omit if using --url'
    )
    parser.add_argument(
        '--url',
        type=str,
        default=None,
        help='Process a single article URL instead of searching by date'
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        default=100,
        help='Maximum number of /latest pages to check (default: 100, only used with date search)'
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=10,
        help='Number of concurrent workers for fetching articles (default: 10, only used with date search)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='.',
        help='Output directory for saved HTML files (default: current directory)'
    )
    parser.add_argument(
        '--translate',
        action='store_true',
        help='Also create Simplified Chinese translations using Gemini 3 Pro'
    )
    parser.add_argument(
        '--gemini-api-key',
        type=str,
        default=None,
        help='Gemini API key (or set GEMINI_API_KEY environment variable)'
    )
    parser.add_argument(
        '--zh-dir',
        type=str,
        default=None,
        help='Directory for Chinese translations (if not specified, uses zh_ prefix in output_dir)'
    )
    
    args = parser.parse_args()
    
    # If --url is provided, process single URL
    if args.url:
        if not args.url.startswith('https://www.newyorker.com/'):
            print(f"Error: URL must be from www.newyorker.com", file=sys.stderr)
            sys.exit(1)
        return process_single_url(
            args.url,
            output_dir=args.output_dir,
            translate=args.translate,
            gemini_api_key=args.gemini_api_key,
            zh_dir=args.zh_dir
        )
    
    # Otherwise, require date for date-based search
    if not args.date:
        parser.error("Either provide a date or use --url to process a single article")
    
    # Parse the date
    try:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    except ValueError:
        print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD format.", file=sys.stderr)
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Find matching articles
    matching_urls = find_articles_by_date(
        target_date,
        max_pages=args.max_pages,
        max_workers=args.max_workers
    )
    
    # Save HTML files for each matching article
    if matching_urls:
        print(f"\nFound {len(matching_urls)} articles published on {target_date}", file=sys.stderr)
        
        # Step 1: Download all English articles first
        print(f"\nStep 1: Downloading {len(matching_urls)} English articles...", file=sys.stderr)
        saved_files = []
        failed_urls = []
        skipped_files = []
        for i, url in enumerate(matching_urls, 1):
            print(f"  [{i}/{len(matching_urls)}] Processing {url}...", file=sys.stderr)
            
            # Check if file already exists by fetching metadata first
            # We need to get the article to determine the filename
            html = fetch_page(url)
            if not html:
                failed_urls.append(url)
                print(f"    Failed to fetch HTML", file=sys.stderr)
                continue
            
            # Extract metadata to determine filename
            author = extract_author_from_html(html)
            title = extract_title_from_html(html)
            category = extract_category_from_url(url)
            
            # Build expected filename
            category_safe = sanitize_filename(category)
            author_safe = sanitize_filename(author)
            title_safe = sanitize_filename(title)
            date_str = target_date.strftime('%Y-%m-%d')
            filename = f"{date_str}_{category_safe}_{author_safe}_{title_safe}.html"
            expected_filepath = os.path.join(args.output_dir, filename)
            
            # Check if file already exists
            if os.path.exists(expected_filepath):
                print(f"    File already exists, skipping download: {filename}", file=sys.stderr)
                skipped_files.append(expected_filepath)
                saved_files.append(expected_filepath)  # Still add to saved_files for translation step
                continue
            
            # File doesn't exist, proceed with download
            print(f"    Downloading...", file=sys.stderr)
            original_path, _ = save_article_html(
                url, target_date, args.output_dir, 
                translate=False,  # Don't translate yet
                gemini_api_key=args.gemini_api_key,
                zh_dir=args.zh_dir
            )
            if original_path:
                saved_files.append(original_path)
                print(f"    Saved to: {original_path}", file=sys.stderr)
            else:
                failed_urls.append(url)
                print(f"    Failed to save", file=sys.stderr)
            
            # Add delay between downloads (except for the last one)
            if i < len(matching_urls):
                delay = random.uniform(3, 7)
                print(f"    Waiting {delay:.1f}s before next download...", file=sys.stderr)
                time.sleep(delay)
        
        print(f"\nStep 1 complete: Successfully downloaded {len(saved_files)} articles", file=sys.stderr)
        if failed_urls:
            print(f"  Failed to download {len(failed_urls)} articles", file=sys.stderr)
        if skipped_files:
            print(f"  Skipped {len(skipped_files)} articles (already exist)", file=sys.stderr)
        
        # Step 2: Translate all downloaded articles
        translated_files = []
        skipped_translations = []
        if args.translate and saved_files:
            print(f"\nStep 2: Translating {len(saved_files)} articles to Simplified Chinese...", file=sys.stderr)
            for i, filepath in enumerate(saved_files, 1):
                # Extract filename from path
                filename = os.path.basename(filepath)
                print(f"  [{i}/{len(saved_files)}] Translating {filename}...", file=sys.stderr)
                
                # Check if translation already exists
                if args.zh_dir:
                    translated_filepath = os.path.join(args.zh_dir, filename)
                else:
                    translated_filename = f"zh_{filename}"
                    translated_filepath = os.path.join(args.output_dir, translated_filename)
                
                if os.path.exists(translated_filepath):
                    print(f"    Translation already exists, skipping: {translated_filepath}", file=sys.stderr)
                    skipped_translations.append(translated_filepath)
                    # Still add to translated_files for summary
                    translated_files.append(translated_filepath)
                    continue
                
                # Read the English HTML
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        html = f.read()
                    
                    # Translate with retry mechanism (max 2 retries = 3 total attempts)
                    translated_html = translate_html_with_gemini_retry(html, args.gemini_api_key, max_retries=2)
                    if translated_html:
                        # Save translated version
                        if args.zh_dir:
                            os.makedirs(args.zh_dir, exist_ok=True)
                            translated_file_rel = os.path.relpath(translated_filepath, args.output_dir)
                        else:
                            translated_file_rel = translated_filename
                        
                        with open(translated_filepath, 'w', encoding='utf-8') as f:
                            f.write(translated_html)
                        translated_files.append(translated_filepath)
                        print(f"    Saved translation to: {translated_filepath}", file=sys.stderr)
                        
                        # Update metadata JSON file to include translated file path
                        metadata_filepath = filepath.replace('.html', '.json')
                        if os.path.exists(metadata_filepath):
                            try:
                                with open(metadata_filepath, 'r', encoding='utf-8') as f:
                                    metadata = json.load(f)
                                metadata['translated_file'] = translated_file_rel
                                with open(metadata_filepath, 'w', encoding='utf-8') as f:
                                    json.dump(metadata, f, ensure_ascii=False, indent=2)
                            except Exception as e:
                                print(f"    Warning: Could not update metadata file: {e}", file=sys.stderr)
                    else:
                        print(f"    Translation failed, skipping", file=sys.stderr)
                except Exception as e:
                    print(f"    Error translating {filename}: {e}", file=sys.stderr)
                
                # Add delay between translations (except for the last one)
                if i < len(saved_files):
                    delay = random.uniform(3, 7)
                    print(f"    Waiting {delay:.1f}s before next translation...", file=sys.stderr)
                    time.sleep(delay)
            
            print(f"\nStep 2 complete: Successfully translated {len(translated_files)} articles", file=sys.stderr)
            if skipped_translations:
                print(f"  Skipped {len(skipped_translations)} translations (already exist)", file=sys.stderr)
        
        print(f"\nSummary:", file=sys.stderr)
        print(f"  Downloaded: {len(saved_files)} articles", file=sys.stderr)
        if args.translate:
            print(f"  Translated: {len(translated_files)} articles", file=sys.stderr)
        print(f"\nAll articles published on {target_date}:", file=sys.stderr)
        for url in matching_urls:
            print(url)
    else:
        print(f"\nNo articles found published on {target_date}", file=sys.stderr)
    
    return 0 if matching_urls else 1


if __name__ == '__main__':
    sys.exit(main())

