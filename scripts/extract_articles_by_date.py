#!/usr/bin/env python3
"""
Script to extract article URLs from New Yorker's /latest pages
that match a given publish date, or process a single article URL from any supported source.

process all articles by date, and translate them to Simplified Chinese:
python extract_articles_by_date.py --date "2025-12-17" --translate --output-dir ./articles

translate single article to Simplified Chinese:
python extract_articles_by_date.py --url "https://www.newyorker.com/culture/postscript/rob-reiner-made-a-new-kind-of-fairy-tale" --translate --output-dir ./articles

process single article from New York Times:
python extract_articles_by_date.py --url "https://www.nytimes.com/..." --translate --output-dir ./articles
"""

import re
import json
import sys
import os
import argparse
import time
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from bs4 import BeautifulSoup
import requests

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.scrapers import get_scraper_for_url, NewYorkerScraper, AtlanticScraper, AeonScraper, NautilusScraper, WeChatScraper
from app.services.translator import translate_html_with_gemini_retry
from app.services.xiaoyuzhou_processor import download_xiaoyuzhou_audio, transcribe_audio_with_gemini, generate_podcast_summary, load_transcript_from_file
from app.utils.logger import setup_script_logger
from app.config import AUDIO_DIR

# Setup unified logger for this script
logger = setup_script_logger("extract_articles")

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional, will use system env vars if not available


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


# Image processing functions removed - images are no longer downloaded locally


# Removed: save_xiaoyuzhou_episode function moved to app/services/scrapers/xiaoyuzhou.py as save_article method
# The function is now implemented as save_article method in XiaoyuzhouScraper class


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
    # Get the appropriate scraper for this URL
    scraper = get_scraper_for_url(url)
    if not scraper:
        logger.error(f"  Error: No scraper available for URL: {url}")
        return (None, None)
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Scrape the article
    result = scraper.scrape(url, verbose=True)
    if not result:
        logger.error(f"  Failed to scrape article from {url}")
        return (None, None)
    
    # Extract metadata from result
    title = result.title
    author = result.author
    category = result.category
    article_date = result.date
    
    # Get date - use provided date or extract from article
    if target_date is None:
        if article_date:
            date_str = article_date.strftime('%Y-%m-%d')
        else:
            # Fallback to today's date if no date found
            date_str = datetime.now().date().strftime('%Y-%m-%d')
    else:
        date_str = target_date.strftime('%Y-%m-%d')
    
    # Get source slug
    source_slug = scraper.get_source_slug()
    
    # Check if scraper has custom save_article method (e.g., Xiaoyuzhou with audio processing)
    if hasattr(scraper, 'save_article') and callable(getattr(scraper, 'save_article')):
        try:
            return scraper.save_article(
                url, result, date_str, output_dir, zh_dir, gemini_api_key
            )
        except NotImplementedError:
            # Scraper has save_article but it's not implemented, fall through to default
            pass
    
    # Sanitize components
    category_safe = sanitize_filename(category)
    author_safe = sanitize_filename(author)
    title_safe = sanitize_filename(title)
    
    # Build filename: date_source_category_author_article_title.html
    filename = f"{date_str}_{source_slug}_{category_safe}_{author_safe}_{title_safe}.html"
    filepath = os.path.join(output_dir, filename)
    
    # Save the original HTML
    translated_filepath = None
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(result.html)
        
        # Translate if requested (with retry mechanism)
        if translate:
            logger.info(f"    Translating to Simplified Chinese...")
            # Translate with retry mechanism
            # Note: translate_html_with_gemini will extract body internally
            try:
                logger.info(f"    [DEBUG] About to call translate_html_with_gemini_retry for {filename}")
                logger.info(f"    [DEBUG] HTML content length: {len(result.html)} chars")
                translated_html = translate_html_with_gemini_retry(
                    result.html, 
                    gemini_api_key, 
                    max_retries=2,
                    filename=filename
                )
                logger.info(f"    [DEBUG] translate_html_with_gemini_retry returned: {type(translated_html)}, length: {len(translated_html) if translated_html else 0}")
            except Exception as e:
                logger.error(f"    [DEBUG] Exception calling translate_html_with_gemini_retry: {e}", exc_info=True)
                translated_html = None
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
                logger.info(f"    Saved translation to: {translated_filepath}")
            else:
                logger.warning(f"    Translation failed, skipping")
        
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
            "source": scraper.get_source_name(),
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
        logger.info(f"    Saved metadata to: {metadata_filepath}")
        
        return (filepath, translated_filepath)
    except Exception as e:
        logger.error(f"  Error saving {url}: {e}", exc_info=True)
        return (None, None)


def find_articles_by_date(target_date, source='newyorker', max_pages=100, max_workers=10):
    """
    Find all articles published on the target date.
    
    Supports New Yorker, Atlantic, Aeon, and Nautilus sources.
    
    Args:
        target_date: datetime.date object for the target date
        source: Source to search ('newyorker', 'atlantic', 'aeon', or 'nautilus')
        max_pages: Maximum number of pages to check (only used for New Yorker)
        max_workers: Number of concurrent workers for fetching articles
    
    Returns:
        List of article URLs matching the date
    """
    if source.lower() == 'atlantic':
        scraper = AtlanticScraper()
        return scraper.find_articles_by_date(target_date, max_workers=max_workers)
    elif source.lower() == 'aeon':
        scraper = AeonScraper()
        return scraper.find_articles_by_date(target_date, max_workers=max_workers)
    elif source.lower() == 'nautilus':
        scraper = NautilusScraper()
        return scraper.find_articles_by_date(target_date, max_workers=max_workers)
    else:
        # Default to New Yorker
        scraper = NewYorkerScraper()
        return scraper.find_articles_by_date(target_date, max_pages=max_pages, max_workers=max_workers)


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
    logger.info(f"Processing article: {url}")
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    if translate:
        logger.info(f"Translation enabled: Will create Simplified Chinese version")
    
    # Save and translate the article
    original_path, translated_path = save_article_html(
        url, target_date=None, output_dir=output_dir,
        translate=translate,
        gemini_api_key=gemini_api_key,
        zh_dir=zh_dir
    )
    
    if original_path:
        logger.info(f"Successfully saved to: {original_path}")
        if translated_path:
            logger.info(f"Successfully translated to: {translated_path}")
        return 0
    else:
        logger.error(f"Failed to save article")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description='Extract article URLs from New Yorker /latest pages by publish date and save HTML files, or process a single URL'
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
        # Check if we have a scraper for this URL
        scraper = get_scraper_for_url(args.url)
        if not scraper:
            logger.error(f"Error: No scraper available for URL: {args.url}")
            logger.error(f"Supported sources: New Yorker, New York Times, Atlantic, Aeon, Nautilus, 公众号, 小宇宙")
            sys.exit(1)
        # For WeChat articles, do not translate (Xiaoyuzhou is handled by scraper's save_article method)
        should_translate = args.translate and scraper.get_source_slug() not in ['wechat']
        return process_single_url(
            args.url,
            output_dir=args.output_dir,
            translate=should_translate,
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
        logger.error(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD format.")
        sys.exit(1)
    
    # Create output directory if it doesn't exist
    os.makedirs(args.output_dir, exist_ok=True)
    
    # Find matching articles from all sources
    logger.info(f"\nSearching for articles from New Yorker...")
    newyorker_urls = find_articles_by_date(
        target_date,
        source='newyorker',
        max_pages=args.max_pages,
        max_workers=args.max_workers
    )
    
    logger.info(f"\nSearching for articles from Atlantic...")
    atlantic_urls = find_articles_by_date(
        target_date,
        source='atlantic',
        max_workers=args.max_workers
    )
    
    logger.info(f"\nSearching for articles from Aeon...")
    aeon_urls = find_articles_by_date(
        target_date,
        source='aeon',
        max_workers=args.max_workers
    )
    
    logger.info(f"\nSearching for articles from Nautilus...")
    nautilus_urls = find_articles_by_date(
        target_date,
        source='nautilus',
        max_workers=args.max_workers
    )
    
    # Combine URLs from all sources
    matching_urls = newyorker_urls + atlantic_urls + aeon_urls + nautilus_urls
    
    # Save HTML files for each matching article
    if matching_urls:
        logger.info(f"\nFound {len(matching_urls)} articles published on {target_date}")
        
        # Step 1: Download all English articles first
        logger.info(f"\nStep 1: Downloading {len(matching_urls)} English articles...")
        saved_files = []
        failed_urls = []
        skipped_files = []
        for i, url in enumerate(matching_urls, 1):
            logger.info(f"  [{i}/{len(matching_urls)}] Processing {url}...")
            
            # Check if file already exists by fetching metadata first
            # We need to get the article to determine the filename
            scraper = get_scraper_for_url(url)
            if not scraper:
                failed_urls.append(url)
                logger.error(f"    No scraper available for URL")
                continue
            
            result = scraper.scrape(url, verbose=False)
            if not result:
                failed_urls.append(url)
                logger.error(f"    Failed to fetch HTML")
                continue
            
            # Extract metadata to determine filename
            title = result.title
            source_slug = scraper.get_source_slug()
            author = result.author
            category = result.category
            
            # Build expected filename
            category_safe = sanitize_filename(category)
            author_safe = sanitize_filename(author)
            title_safe = sanitize_filename(title)
            date_str = target_date.strftime('%Y-%m-%d')
            filename = f"{date_str}_{source_slug}_{category_safe}_{author_safe}_{title_safe}.html"
            expected_filepath = os.path.join(args.output_dir, filename)
            
            # Check if file already exists
            if os.path.exists(expected_filepath):
                skip_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"  [{i}/{len(matching_urls)}] [{skip_time_str}] SKIP download (already exists): {filename} ({url})")
                skipped_files.append(expected_filepath)
                saved_files.append(expected_filepath)  # Still add to saved_files for translation step
                continue
            
            # File doesn't exist, proceed with download
            download_start_time = time.time()
            download_start_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f"  [{i}/{len(matching_urls)}] [{download_start_str}] START downloading {filename} ({url})")
            original_path, _ = save_article_html(
                url, target_date, args.output_dir, 
                translate=False,  # Don't translate yet
                gemini_api_key=args.gemini_api_key,
                zh_dir=args.zh_dir
            )
            if original_path:
                saved_files.append(original_path)
                download_elapsed = time.time() - download_start_time
                download_end_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logger.info(f"  [{i}/{len(matching_urls)}] [{download_end_str}] SUCCESS download (took {download_elapsed:.1f}s): {original_path}")
            else:
                failed_urls.append(url)
                download_elapsed = time.time() - download_start_time
                download_end_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                logger.error(f"  [{i}/{len(matching_urls)}] [{download_end_str}] FAILED download (took {download_elapsed:.1f}s): {filename} ({url})")
            
            # Add delay between downloads (except for the last one)
            if i < len(matching_urls):
                delay = random.uniform(3, 7)
                logger.info(f"    Waiting {delay:.1f}s before next download...")
                time.sleep(delay)
        
        logger.info(f"\nStep 1 complete: Successfully downloaded {len(saved_files)} articles")
        if failed_urls:
            logger.warning(f"  Failed to download {len(failed_urls)} articles")
        if skipped_files:
            logger.info(f"  Skipped {len(skipped_files)} articles (already exist)")
        
        # Step 2: Translate all downloaded articles
        translated_files = []
        skipped_translations = []
        if args.translate and saved_files:
            logger.info(f"\nStep 2: Translating {len(saved_files)} articles to Simplified Chinese...")
            for i, filepath in enumerate(saved_files, 1):
                # Extract filename from path
                filename = os.path.basename(filepath)
                
                # Get article URL from metadata for better logging
                article_url = None
                metadata_filepath = filepath.replace('.html', '.json')
                if os.path.exists(metadata_filepath):
                    try:
                        with open(metadata_filepath, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                            article_url = metadata.get('url', '')
                    except Exception:
                        pass
                
                # Log translation start with timestamp
                start_time = time.time()
                start_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                url_info = f" ({article_url})" if article_url else ""
                logger.info(f"  [{i}/{len(saved_files)}] [{start_time_str}] START translating {filename}{url_info}")
                
                # Check if translation already exists
                if args.zh_dir:
                    translated_filepath = os.path.join(args.zh_dir, filename)
                else:
                    translated_filename = f"zh_{filename}"
                    translated_filepath = os.path.join(args.output_dir, translated_filename)
                
                if os.path.exists(translated_filepath):
                    elapsed = time.time() - start_time
                    end_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    logger.info(f"  [{i}/{len(saved_files)}] [{end_time_str}] SKIP translation (already exists, took {elapsed:.1f}s): {translated_filepath}{url_info}")
                    skipped_translations.append(translated_filepath)
                    # Still add to translated_files for summary
                    translated_files.append(translated_filepath)
                    continue
                
                # Read the English HTML
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        html = f.read()
                    
                    html_size = len(html)
                    logger.info(f"    Reading HTML file: {html_size:,} characters")
                    
                    # Translate with retry mechanism (max 2 retries = 3 total attempts)
                    # Note: translate_html_with_gemini will extract body internally
                    translated_html = translate_html_with_gemini_retry(
                        html, 
                        args.gemini_api_key, 
                        max_retries=2, 
                        filename=filename
                    )
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
                        
                        # Log translation completion with timestamp and duration
                        end_time = time.time()
                        elapsed = end_time - start_time
                        end_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        logger.info(f"    [{end_time_str}] SUCCESS (took {elapsed:.1f}s, {elapsed/60:.1f}min): Saved translation to {translated_filepath}")
                        
                        # Update metadata JSON file to include translated file path
                        if os.path.exists(metadata_filepath):
                            try:
                                with open(metadata_filepath, 'r', encoding='utf-8') as f:
                                    metadata = json.load(f)
                                metadata['translated_file'] = translated_file_rel
                                with open(metadata_filepath, 'w', encoding='utf-8') as f:
                                    json.dump(metadata, f, ensure_ascii=False, indent=2)
                            except Exception as e:
                                logger.warning(f"    Warning: Could not update metadata file: {e}")
                        
                        # Import this article immediately so it appears on the page
                        try:
                            from app.services.importer import import_from_subdirs_inline
                            from app.config import HTML_DIR_EN, HTML_DIR_ZH
                            logger.info(f"    Importing article to database...")
                            # Import just this one article by importing from the directory
                            # The import function will update existing or create new
                            import_count = import_from_subdirs_inline(HTML_DIR_EN, HTML_DIR_ZH)
                            logger.info(f"    ✅ Article imported/updated in database (will appear on page after refresh)")
                        except Exception as e:
                            logger.warning(f"    Warning: Could not import article immediately: {e}")
                    else:
                        # Log translation failure with timestamp and duration
                        end_time = time.time()
                        elapsed = end_time - start_time
                        end_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        logger.error(f"    [{end_time_str}] FAILED (took {elapsed:.1f}s, {elapsed/60:.1f}min): Translation failed after all retries")
                except Exception as e:
                    # Log error with timestamp and duration
                    end_time = time.time()
                    elapsed = end_time - start_time
                    end_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    logger.error(f"    [{end_time_str}] ERROR (took {elapsed:.1f}s, {elapsed/60:.1f}min): Error translating {filename}: {e}", exc_info=True)
                
                # Add delay between translations (except for the last one)
                if i < len(saved_files):
                    delay = random.uniform(3, 7)
                    logger.info(f"    Waiting {delay:.1f}s before next translation...")
                    time.sleep(delay)
            
            logger.info(f"\nStep 2 complete: Successfully translated {len(translated_files)} articles")
            if skipped_translations:
                logger.info(f"  Skipped {len(skipped_translations)} translations (already exist)")
        
        logger.info(f"\nSummary:")
        logger.info(f"  Downloaded: {len(saved_files)} articles")
        if args.translate:
            logger.info(f"  Translated: {len(translated_files)} articles")
        logger.info(f"\nAll articles published on {target_date}:")
        for url in matching_urls:
            logger.info(url)
    else:
        logger.warning(f"\nNo articles found published on {target_date}")
    
    return 0 if matching_urls else 1


if __name__ == '__main__':
    sys.exit(main())

