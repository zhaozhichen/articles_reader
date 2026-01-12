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

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.scrapers import get_scraper_for_url, NewYorkerScraper, AtlanticScraper, WeChatScraper
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


def save_xiaoyuzhou_episode(url, result, scraper, date_str, output_dir, zh_dir, gemini_api_key):
    """Special handler for Xiaoyuzhou episodes: download audio, transcribe, generate summary.
    
    Args:
        url: Episode URL
        result: ScraperResult from scraping the episode page
        scraper: XiaoyuzhouScraper instance
        date_str: Date string for filename
        output_dir: Output directory for HTML files
        zh_dir: Directory for Chinese files (same as output_dir for Xiaoyuzhou)
        gemini_api_key: Gemini API key
        
    Returns:
        Tuple of (original_filepath, translated_filepath) where translated_filepath is same as original
    """
    logger.info("Processing Xiaoyuzhou episode...")
    
    # Extract shownotes from body
    shownotes_html = result.body_html or ""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(shownotes_html, 'html.parser')
    shownotes_text = soup.get_text(separator='\n', strip=True)
    
    if not shownotes_text or len(shownotes_text.strip()) < 10:
        logger.warning("Could not extract shownotes, using placeholder")
        shownotes_text = "（未找到节目简介）"
    
    logger.info(f"Extracted shownotes: {len(shownotes_text)} characters")
    
    # Extract episode ID from URL
    import re
    episode_id = None
    episode_id_match = re.search(r'/episode/([a-f0-9]+)', url)
    if episode_id_match:
        episode_id = episode_id_match.group(1)
        logger.info(f"Extracted episode ID: {episode_id}")
    
    # Check if transcript file already exists
    transcript = None
    transcript_file = None
    if episode_id:
        transcript_file = AUDIO_DIR / f"episode_{episode_id}.txt"
        if transcript_file.exists():
            logger.info(f"Transcript file already exists: {transcript_file}, loading from file")
            transcript = load_transcript_from_file(transcript_file)
            if transcript:
                logger.info(f"Loaded transcript from file: {len(transcript)} characters")
    
    # Download audio and transcribe if transcript doesn't exist
    audio_file = None
    if not transcript:
        logger.info("Downloading audio file...")
        audio_file, downloaded_episode_id = download_xiaoyuzhou_audio(url, AUDIO_DIR)
        
        # Use episode_id from download if we didn't have it before
        if not episode_id and downloaded_episode_id:
            episode_id = downloaded_episode_id
            transcript_file = AUDIO_DIR / f"episode_{episode_id}.txt"
        
        if audio_file:
            logger.info(f"Audio downloaded: {audio_file}")
            # Transcribe audio and save to file
            logger.info("Transcribing audio...")
            transcript = transcribe_audio_with_gemini(audio_file, transcript_file, gemini_api_key)
            if transcript:
                logger.info(f"Transcription completed: {len(transcript)} characters")
            else:
                logger.error("Transcription failed")
                transcript = "（转录失败）"
        else:
            logger.error("Audio download failed")
            transcript = "（音频下载失败，无法转录）"
    else:
        logger.info("Skipping audio download and transcription (transcript file exists)")
    
    # Generate summary
    summary = None
    if transcript and transcript != "（转录失败）" and transcript != "（音频下载失败，无法转录）":
        logger.info("Generating summary...")
        summary = generate_podcast_summary(shownotes_text, transcript, gemini_api_key)
        if summary:
            logger.info(f"Summary generated: {len(summary)} characters")
        else:
            logger.error("Summary generation failed")
            summary = "（总结生成失败）"
    else:
        logger.warning("Skipping summary generation (no transcript)")
        summary = "（无转录内容，无法生成总结）"
    
    # Format shownotes: convert line breaks to paragraphs
    import html
    import re
    
    def format_shownotes(text):
        """Format shownotes text with proper paragraph breaks."""
        if not text:
            return ""
        # Escape HTML first
        text = html.escape(text)
        # Split by double newlines or special markers
        # First, handle special sections like 【聊了什么】, 【时间轴】, etc.
        sections = re.split(r'(【[^】]+】)', text)
        formatted_parts = []
        for i, section in enumerate(sections):
            if re.match(r'【[^】]+】', section):
                # This is a section header
                formatted_parts.append(f'<h3 style="font-size: 18px; margin-top: 20px; margin-bottom: 10px; color: #667eea;">{section}</h3>')
            else:
                # Regular content - split by newlines and convert to paragraphs
                paragraphs = section.split('\n\n')
                for para in paragraphs:
                    para = para.strip()
                    if para:
                        # Check if it's a list item (starts with * or -)
                        if para.startswith('*') or para.startswith('-'):
                            # Format as list
                            lines = para.split('\n')
                            formatted_parts.append('<ul style="margin-bottom: 15px;">')
                            for line in lines:
                                line = line.strip()
                                if line.startswith('*') or line.startswith('-'):
                                    content = line[1:].strip()
                                    if content:
                                        formatted_parts.append(f'<li style="margin-bottom: 8px;">{content}</li>')
                            formatted_parts.append('</ul>')
                        else:
                            # Regular paragraph
                            # Replace single newlines with <br> for line breaks within paragraphs
                            para = para.replace('\n', '<br>')
                            formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para}</p>')
        return ''.join(formatted_parts)
    
    def format_transcript(text):
        """Format transcript text with proper paragraph breaks."""
        if not text:
            return ""
        # Escape HTML first
        text = html.escape(text)
        
        # Split by double newlines first
        paragraphs = text.split('\n\n')
        formatted_parts = []
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # Also split by time markers like [00:00 - 03:21] or [00:00]
            # This helps break up long transcripts
            time_markers = re.split(r'(\[[\d:]+\s*[-–]\s*[\d:]+\]|\[\d+:\d+\])', para)
            current_section = []
            
            for part in time_markers:
                part = part.strip()
                if not part:
                    continue
                
                # Check if this is a time marker
                if re.match(r'\[[\d:]+\s*[-–]\s*[\d:]+\]|\[\d+:\d+\]', part):
                    # End current section if any
                    if current_section:
                        section_text = ' '.join(current_section).strip()
                        if section_text:
                            # Replace single newlines with <br>
                            section_text = section_text.replace('\n', '<br>')
                            formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{section_text}</p>')
                        current_section = []
                    # Add time marker as a paragraph with special styling
                    formatted_parts.append(f'<p style="margin-bottom: 10px; margin-top: 20px; font-weight: bold; color: #667eea;">{part}</p>')
                else:
                    current_section.append(part)
            
            # Add remaining section
            if current_section:
                section_text = ' '.join(current_section).strip()
                if section_text:
                    # Replace single newlines with <br>
                    section_text = section_text.replace('\n', '<br>')
                    formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{section_text}</p>')
        
        return ''.join(formatted_parts)
    
    def format_summary_text(text):
        """Format summary text with proper HTML structure - handles both HTML and plain text."""
        if not text:
            return ""
        
        # Check if already HTML formatted
        if '<' in text and '>' in text and ('<p' in text or '<h3' in text or '<ol' in text or '<ul' in text):
            # Already HTML, use as-is
            return text
        
        # Plain text - format it properly
        # Split by section markers 【...】 first (BEFORE HTML escape)
        sections = re.split(r'(【[^】]+】)', text)
        formatted_parts = []
        current_list = []
        in_ordered_list = False
        in_unordered_list = False
        in_quotes_section = False
        
        for i, section in enumerate(sections):
            section = section.strip()
            if not section:
                continue
            
            # Check if this is a section header 【...】
            if section.startswith('【') and section.endswith('】'):
                # End any current list
                if in_ordered_list and current_list:
                    formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                    for item in current_list:
                        formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                    formatted_parts.append('</ol>')
                    current_list = []
                    in_ordered_list = False
                elif in_unordered_list and current_list:
                    formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                    for item in current_list:
                        formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                    formatted_parts.append('</ul>')
                    current_list = []
                    in_unordered_list = False
                # Add header (escape HTML)
                section_escaped = html.escape(section)
                formatted_parts.append(f'<h3 style="font-size: 18px; margin-top: 20px; margin-bottom: 10px; color: #667eea;"><strong>{section_escaped}</strong></h3>')
                # Check if this is 高光金句库 header
                if '高光金句库' in section:
                    in_quotes_section = True
                else:
                    in_quotes_section = False
                continue
            
            # Special handling for "高光金句库" section - quotes should be list items
            if in_quotes_section:
                # Split by Chinese quotes and process as ordered list
                # Match pattern: "content"——author or "content"（note）
                # Each quote ends with —— or （, and next quote starts with "
                # Process BEFORE HTML escape to match Chinese quotes correctly
                quotes = re.findall(r'"[^"]+"[^"】]*?(?="|【|$)', section)
                if quotes:
                    formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                    for quote in quotes:
                        quote_escaped = html.escape(quote)
                        formatted_parts.append(f'<li style="margin-bottom: 10px;">{quote_escaped}</li>')
                    formatted_parts.append('</ol>')
                    in_quotes_section = False
                    continue
                
                # If no quotes found, escape and format as paragraph
                section_escaped = html.escape(section)
                formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{section_escaped}</p>')
                in_quotes_section = False
                continue
            
            # Escape HTML for content sections
            section_escaped = html.escape(section)
            
            # Process content section - split by "专题" markers
            content_sections = re.split(r'(专题[^：]*：)', section_escaped)
            for content in content_sections:
                content = content.strip()
                if not content:
                    continue
                
                # Check if this is a topic header (专题...：)
                if content.startswith('专题') and '：' in content:
                    # End any current list
                    if in_ordered_list and current_list:
                        formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                        for item in current_list:
                            formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                        formatted_parts.append('</ol>')
                        current_list = []
                        in_ordered_list = False
                    elif in_unordered_list and current_list:
                        formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                        for item in current_list:
                            formatted_parts.append(f'<li style="margin-bottom: 10px;">{item}</li>')
                        formatted_parts.append('</ul>')
                        current_list = []
                        in_unordered_list = False
                    # Add h4 header (escape HTML)
                    content_escaped = html.escape(content)
                    formatted_parts.append(f'<h4 style="font-size: 16px; margin-top: 15px; margin-bottom: 8px; color: #555;"><strong>{content_escaped}</strong></h4>')
                    continue
                
                # Process content - look for list items and regular text
                # Split by list markers (* or numbered)
                parts = re.split(r'(\*|\d+\.)', content)
                current_para = []
                
                i = 0
                while i < len(parts):
                    part = parts[i].strip()
                    if not part:
                        i += 1
                        continue
                    
                    # Check for list marker
                    if part == '*' or (part and part[-1] == '.' and part[:-1].isdigit()):
                        # End current paragraph if any
                        if current_para:
                            para_text = ' '.join(current_para).strip()
                            if para_text:
                                para_text_escaped = html.escape(para_text)
                                formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para_text_escaped}</p>')
                            current_para = []
                        
                        # Get list item content
                        if i + 1 < len(parts):
                            item_content = parts[i + 1].strip()
                            if item_content:
                                # Escape HTML for list items
                                item_content_escaped = html.escape(item_content)
                                if part == '*':
                                    # Unordered list
                                    if not in_unordered_list:
                                        if in_ordered_list and current_list:
                                            formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                                            for item in current_list:
                                                formatted_parts.append(f'<li style="margin-bottom: 10px;">{html.escape(item)}</li>')
                                            formatted_parts.append('</ol>')
                                            current_list = []
                                            in_ordered_list = False
                                        in_unordered_list = True
                                    current_list.append(item_content_escaped)
                                else:
                                    # Ordered list
                                    if not in_ordered_list:
                                        if in_unordered_list and current_list:
                                            formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                                            for item in current_list:
                                                formatted_parts.append(f'<li style="margin-bottom: 10px;">{html.escape(item)}</li>')
                                            formatted_parts.append('</ul>')
                                            current_list = []
                                            in_unordered_list = False
                                        in_ordered_list = True
                                    current_list.append(item_content_escaped)
                            i += 2
                            continue
                    
                    # Regular text
                    current_para.append(part)
                    i += 1
                
                # End current paragraph (escape HTML)
                if current_para:
                    para_text = ' '.join(current_para).strip()
                    if para_text:
                        para_text_escaped = html.escape(para_text)
                        formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para_text_escaped}</p>')
        
        # Handle list at end (escape HTML)
        if in_ordered_list and current_list:
            formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
            for item in current_list:
                formatted_parts.append(f'<li style="margin-bottom: 10px;">{html.escape(item)}</li>')
            formatted_parts.append('</ol>')
        elif in_unordered_list and current_list:
            formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
            for item in current_list:
                formatted_parts.append(f'<li style="margin-bottom: 10px;">{html.escape(item)}</li>')
            formatted_parts.append('</ul>')
        
        return ''.join(formatted_parts)
    
    title_escaped = html.escape(result.title)
    author_escaped = html.escape(result.author)
    category_escaped = html.escape(result.category)
    url_escaped = html.escape(url)
    shownotes_formatted = format_shownotes(shownotes_text)
    
    # Format summary - handle both HTML and plain text
    summary_formatted = format_summary_text(summary or "（总结生成失败）")
    
    # Load transcript from file if available, otherwise use in-memory transcript
    final_transcript = transcript
    if episode_id and not final_transcript:
        # Try to load from file as fallback
        transcript_file = AUDIO_DIR / f"episode_{episode_id}.txt"
        if transcript_file.exists():
            logger.info(f"Loading transcript from file for HTML generation: {transcript_file}")
            final_transcript = load_transcript_from_file(transcript_file)
    
    # Transcript is plain text, format simply
    transcript_formatted = format_transcript(final_transcript or "（转录失败）")
    
    # Create HTML content in order: shownotes, summary, transcript
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title_escaped}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            color: #333;
        }}
        h1 {{
            font-size: 24px;
            margin-bottom: 10px;
        }}
        h2 {{
            font-size: 20px;
            margin-top: 30px;
            margin-bottom: 15px;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
        }}
        h3 {{
            font-size: 18px;
            margin-top: 20px;
            margin-bottom: 10px;
            color: #667eea;
        }}
        h4 {{
            font-size: 16px;
            margin-top: 15px;
            margin-bottom: 8px;
            color: #555;
        }}
        .metadata {{
            color: #666;
            font-size: 14px;
            margin-bottom: 30px;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .shownotes {{
            line-height: 1.8;
        }}
        .shownotes p {{
            margin-bottom: 15px;
        }}
        .shownotes ul {{
            margin-bottom: 15px;
            padding-left: 20px;
        }}
        .shownotes li {{
            margin-bottom: 8px;
        }}
        .summary-content, .transcript-content {{
            line-height: 1.8;
            background: #f9f9f9;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }}
        .summary-content p, .transcript-content p {{
            margin-bottom: 15px;
        }}
        .summary-content h3, .transcript-content h3 {{
            margin-top: 20px;
            margin-bottom: 10px;
        }}
        .summary-content h4, .transcript-content h4 {{
            margin-top: 15px;
            margin-bottom: 8px;
        }}
        .summary-content hr, .transcript-content hr {{
            margin: 20px 0;
            border: none;
            border-top: 1px solid #ddd;
        }}
        .summary-content strong, .transcript-content strong {{
            font-weight: 600;
            color: #333;
        }}
        .summary-content em, .transcript-content em {{
            font-style: italic;
        }}
        p {{
            margin-bottom: 15px;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }}
    </style>
</head>
<body>
    <h1>{title_escaped}</h1>
    <div class="metadata">
        <p>作者: {author_escaped} | 分类: {category_escaped} | 日期: {date_str}</p>
        <p>来源: <a href="{url_escaped}">{url_escaped}</a></p>
    </div>
    
    <div class="section">
        <h2>节目简介 (Show Notes)</h2>
        <div class="shownotes">{shownotes_formatted}</div>
    </div>
    
    <div class="section">
        <h2>内容总结 (Summary)</h2>
        <div class="summary-content">{summary_formatted}</div>
    </div>
    
    <div class="section">
        <h2>完整转录 (Transcript)</h2>
        <div class="transcript-content">{transcript_formatted}</div>
    </div>
</body>
</html>"""
    
    # Sanitize components for filename
    category_safe = sanitize_filename(result.category)
    author_safe = sanitize_filename(result.author)
    title_safe = sanitize_filename(result.title)
    
    # Build filename
    filename = f"{date_str}_xiaoyuzhou_{category_safe}_{author_safe}_{title_safe}.html"
    filepath = os.path.join(output_dir, filename)
    
    # Save HTML (only save to output_dir, like WeChat articles - no translation needed)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"Saved Xiaoyuzhou episode to: {filepath}")
        
        # Create and save metadata JSON file (same as other articles)
        metadata = {
            "date": date_str,
            "category": result.category,
            "author": result.author,
            "source": scraper.get_source_name(),
            "title": result.title,
            "url": url,
            "original_file": filename,
            "translated_file": None  # Xiaoyuzhou articles don't have translations
        }
        
        # Save metadata to JSON file (same name as HTML but with .json extension)
        metadata_filename = filename.replace('.html', '.json')
        metadata_filepath = os.path.join(output_dir, metadata_filename)
        with open(metadata_filepath, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved metadata to: {metadata_filepath}")
        
        # For Xiaoyuzhou, only save to output_dir (like WeChat), not to zh_dir
        # Return same path for both en and zh to indicate no separate translation
        return (filepath, None)
            
    except Exception as e:
        logger.error(f"Error saving Xiaoyuzhou episode: {e}", exc_info=True)
        return (None, None)


def save_article_html(url, target_date=None, output_dir='.', translate=False, gemini_api_key=None, zh_dir=None):
    """Translate only the article body content to Simplified Chinese using Gemini 3 Pro.
    
    Only translates the main article body, keeping navigation, scripts, styles, etc. in English.
    
    Args:
        html_content: Original HTML content
        api_key: Gemini API key (if None, uses GEMINI_API_KEY env var)
    
    Returns:
        Translated HTML content with only body translated, or None if translation fails
    """
    if not GEMINI_AVAILABLE:
        logger.warning("  Warning: google.genai not installed. Install with: pip install google-genai")
        return None
    
    # Get API key (the client gets it from GEMINI_API_KEY env var automatically)
    # But we can check if it's set
    if api_key is None:
        api_key = os.getenv('GEMINI_API_KEY')
    
    if not api_key:
        logger.warning("  Warning: GEMINI_API_KEY not set. Skipping translation.")
        return None
    
    try:
        # Extract article body
        logger.info("    Extracting article body content...")
        body_html, body_element = extract_article_body(html_content)
        
        if not body_html or not body_element:
            logger.warning("  Warning: Could not find article body content")
            return None
        
        body_size = len(body_html)
        logger.info(f"    Found article body (size: {body_size} chars)")
        
        # Maximum size for single translation
        MAX_SINGLE_TRANSLATION = 200000
        
        # Check if body is too long to translate
        if body_size > MAX_SINGLE_TRANSLATION:
            logger.warning(f"    Article body is too long ({body_size:,} chars), skipping translation and showing placeholder")
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
                logger.warning("  Warning: Could not locate body element for placeholder insertion")
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
        
        # Generate translation using gemini-3-flash-preview
        logger.info(f"    Sending article body to Gemini (size: {len(body_html)} chars)...")
        
        response = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt
        )
        
        # Check if response is valid
        if not response:
            logger.error("  Error: Empty response from Gemini API")
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
            logger.error(f"  Error extracting text from response: {e}")
            logger.error(f"  Response type: {type(response)}")
            if hasattr(response, '__dict__'):
                logger.error(f"  Response attributes: {list(response.__dict__.keys())}")
            return None
        
        if not translated_html or len(translated_html.strip()) == 0:
            logger.error("  Error: Translation result is empty")
            return None
        
        logger.info(f"    Received translation (size: {len(translated_html)} chars)")
        
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
            logger.warning(f"  Warning: Translation seems too short ({len(translated_html)} vs original {len(html_content)} chars)")
            logger.warning(f"  This might indicate the translation was truncated or incomplete")
        
        # Verify basic HTML structure
        if not translated_html or len(translated_html.strip()) < 100:
            logger.warning(f"  Warning: Translation result seems too short")
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
            
            logger.info(f"    Replaced article body with translated version")
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
                logger.warning("  Warning: Could not locate body element for replacement")
                return None
        
    except Exception as e:
        logger.error(f"  Error translating with Gemini: {e}", exc_info=True)
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
    
    # Special handling for Xiaoyuzhou: download audio, transcribe, generate summary
    if source_slug == 'xiaoyuzhou':
        return save_xiaoyuzhou_episode(
            url, result, scraper, date_str, output_dir, zh_dir, gemini_api_key
        )
    
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
    
    Supports New Yorker and Atlantic sources.
    
    Args:
        target_date: datetime.date object for the target date
        source: Source to search ('newyorker' or 'atlantic')
        max_pages: Maximum number of pages to check (only used for New Yorker)
        max_workers: Number of concurrent workers for fetching articles
    
    Returns:
        List of article URLs matching the date
    """
    if source.lower() == 'atlantic':
        scraper = AtlanticScraper()
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
            logger.error(f"Supported sources: New Yorker, New York Times, Atlantic, 公众号, 小宇宙")
            sys.exit(1)
        # For WeChat and Xiaoyuzhou articles, do not translate
        should_translate = args.translate and scraper.get_source_slug() not in ['wechat', 'xiaoyuzhou']
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
    
    # Find matching articles from both sources
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
    
    # Combine URLs from both sources
    matching_urls = newyorker_urls + atlantic_urls
    
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
            author = result.author
            title = result.title
            category = result.category
            source_slug = scraper.get_source_slug()
            
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

