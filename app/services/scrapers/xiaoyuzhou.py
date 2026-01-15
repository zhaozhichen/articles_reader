"""Xiaoyuzhou (小宇宙) podcast episode scraper."""
import re
import json
import os
import html as html_module
from datetime import datetime
from typing import Optional, Tuple
from pathlib import Path
from bs4 import BeautifulSoup
from app.services.scrapers.base import BaseScraper, ScraperResult
from app.services.xiaoyuzhou_processor import download_xiaoyuzhou_audio, transcribe_audio_with_gemini, generate_podcast_summary, load_transcript_from_file
from app.config import AUDIO_DIR
import logging

logger = logging.getLogger(__name__)


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


class XiaoyuzhouScraper(BaseScraper):
    """Scraper for Xiaoyuzhou (小宇宙) podcast episodes."""
    
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL."""
        return 'xiaoyuzhou.fm' in url or 'xiaoyuzhou.com' in url or 'xiaoyuzhoufm.com' in url
    
    def get_source_name(self) -> str:
        """Get the name of the source this scraper handles."""
        return "小宇宙"
    
    def get_source_slug(self) -> str:
        """Get a URL-safe slug identifier for the source."""
        return "xiaoyuzhou"
    
    def extract_category(self, url: str, html: str) -> str:
        """Extract category from HTML.
        
        For Xiaoyuzhou, the category is the podcast show name.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try to find podcast show name from various sources
        # 1. Look for show name in meta tags
        og_site_name = soup.find('meta', property='og:site_name')
        if og_site_name and og_site_name.get('content'):
            site_name = og_site_name.get('content')
            if site_name and site_name != '小宇宙':
                return site_name
        
        # 2. Look for show name in script tags (JSON-LD or other structured data)
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        # Try various possible fields
                        show_name = data.get('partOfSeries', {}).get('name') or \
                                   data.get('series', {}).get('name') or \
                                   data.get('show', {}).get('name')
                        if show_name:
                            return show_name
                except (json.JSONDecodeError, AttributeError):
                    pass
        
        # 3. Try to find in page title (format: "Episode Title - Show Name")
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text().strip()
            if ' - ' in title_text:
                parts = title_text.split(' - ')
                if len(parts) > 1:
                    show_name = parts[-1].strip()
                    if show_name and show_name != '小宇宙':
                        return show_name
        
        # 4. Fallback
        return '小宇宙播客'
    
    def extract_metadata(self, html: str, url: str) -> dict:
        """Extract metadata from episode HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title = self._extract_title(soup)
        
        # Extract author (host/podcast creator)
        author = self._extract_author(soup)
        
        # Extract date
        article_date = self._extract_publish_date(soup)
        if not article_date:
            from datetime import date
            article_date = date.today()
        
        # Extract category (which is the podcast show name for Xiaoyuzhou)
        category = self.extract_category(url, html)
        
        return {
            'title': title,
            'author': author,
            'date': article_date,
            'category': category,
            'url': url
        }
    
    def extract_body(self, html: str) -> Tuple[Optional[str], Optional[BeautifulSoup]]:
        """Extract the main content (shownotes) from HTML.
        
        For Xiaoyuzhou episodes, we extract the shownotes section.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try to find shownotes in various possible locations
        # Common selectors for Xiaoyuzhou shownotes
        selectors = [
            ('div', {'class': re.compile(r'shownotes|show-notes|episode-notes|notes', re.I)}),
            ('div', {'class': re.compile(r'description|desc|content|episode.*description', re.I)}),
            ('div', {'data-testid': re.compile(r'description|shownotes', re.I)}),
            ('article', {}),
            ('section', {'class': re.compile(r'content|main|episode', re.I)}),
            ('div', {'id': re.compile(r'content|main|description|shownotes', re.I)}),
        ]
        
        for tag_name, attrs in selectors:
            if 'class' in attrs:
                body_element = soup.find(tag_name, class_=attrs['class'])
            elif 'id' in attrs:
                body_element = soup.find(tag_name, id=attrs['id'])
            elif 'data-testid' in attrs:
                body_element = soup.find(tag_name, attrs={'data-testid': re.compile(attrs['data-testid'].pattern, re.I)})
            else:
                body_element = soup.find(tag_name)
            
            if body_element:
                text_content = body_element.get_text(strip=True)
                if len(text_content) > 50:  # Has meaningful content
                    return str(body_element), body_element
        
        # Try to extract from JSON-LD structured data
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        description = data.get('description') or data.get('episode', {}).get('description')
                        if description and len(description) > 50:
                            # Create a div with the description
                            desc_div = soup.new_tag('div', class_='shownotes')
                            desc_div.string = description
                            return str(desc_div), desc_div
                except (json.JSONDecodeError, AttributeError):
                    pass
        
        # Last resort: try to find main content area
        main = soup.find('main')
        if main:
            return str(main), main
        
        # Return body if nothing else found
        body_element = soup.find('body')
        if body_element:
            return str(body_element), body_element
        
        return html, soup
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract episode title from HTML."""
        # Try og:title meta tag first
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title.get('content')
        
        # Try h1 tag
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text().strip()
            if title:
                return title
        
        # Try title tag
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()
            # Remove show name suffix if present (format: "Title - Show Name")
            title = re.sub(r'\s*-\s*[^-]+$', '', title)
            return title
        
        return 'untitled'
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract author/host name from episode HTML."""
        # Try meta name="author"
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta and author_meta.get('content'):
            author = author_meta.get('content')
            if author:
                return author
        
        # Try to find in structured data
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        author = data.get('author', {}).get('name') or \
                                data.get('creator', {}).get('name')
                        if author:
                            return author
                except (json.JSONDecodeError, AttributeError):
                    pass
        
        return 'unknown'
    
    def _extract_publish_date(self, soup: BeautifulSoup) -> Optional[datetime.date]:
        """Extract publish date from episode HTML."""
        # Try article:published_time meta tag
        meta_tag = soup.find('meta', property='article:published_time')
        if meta_tag and meta_tag.get('content'):
            date_str = meta_tag['content']
            try:
                date_str = date_str.replace('Z', '+00:00')
                if '+' not in date_str and len(date_str) > 10:
                    date_str = date_str + '+08:00'
                dt = datetime.fromisoformat(date_str)
                return dt.date()
            except (ValueError, AttributeError):
                pass
        
        # Try datePublished in structured data
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            if script.string:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        date_str = data.get('datePublished') or data.get('datePublished')
                        if date_str:
                            try:
                                date_str = date_str.replace('Z', '+00:00')
                                if '+' not in date_str and len(date_str) > 10:
                                    date_str = date_str + '+08:00'
                                dt = datetime.fromisoformat(date_str)
                                return dt.date()
                            except (ValueError, AttributeError):
                                pass
                except (json.JSONDecodeError, AttributeError):
                    pass
        
        return None
    
    def save_article(self, url: str, result: ScraperResult, date_str: str, output_dir: str, 
                     zh_dir: str = None, gemini_api_key: str = None, **kwargs) -> Tuple[Optional[str], Optional[str]]:
        """Save Xiaoyuzhou episode: download audio, transcribe, generate summary, and save HTML.
        
        This method handles the special processing required for Xiaoyuzhou episodes:
        - Downloads audio file
        - Transcribes audio using Gemini
        - Generates summary from shownotes and transcript
        - Creates HTML with shownotes, summary, and transcript
        
        Args:
            url: Episode URL
            result: ScraperResult from scraping the episode page
            date_str: Date string for filename (YYYY-MM-DD)
            output_dir: Output directory for HTML files
            zh_dir: Directory for Chinese files (ignored for Xiaoyuzhou, same as output_dir)
            gemini_api_key: Gemini API key for transcription and summary
            **kwargs: Additional arguments (ignored)
            
        Returns:
            Tuple of (original_filepath, translated_filepath) where translated_filepath is None
        """
        logger.info("=" * 80)
        logger.info("Processing Xiaoyuzhou episode...")
        logger.info(f"URL: {url}")
        logger.info("=" * 80)
        
        # Extract shownotes from body
        shownotes_html = result.body_html or ""
        soup = BeautifulSoup(shownotes_html, 'html.parser')
        shownotes_text = soup.get_text(separator='\n', strip=True)
        
        if not shownotes_text or len(shownotes_text.strip()) < 10:
            logger.warning("Could not extract shownotes, using placeholder")
            shownotes_text = "（未找到节目简介）"
        
        logger.info(f"Extracted shownotes: {len(shownotes_text)} characters")
        
        # Extract episode ID from URL
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
            logger.info("-" * 80)
            logger.info("Step 1: Downloading audio file...")
            logger.info(f"Episode URL: {url}")
            logger.info(f"Audio directory: {AUDIO_DIR}")
            logger.info("-" * 80)
            audio_file, downloaded_episode_id = download_xiaoyuzhou_audio(url, AUDIO_DIR)
            
            # Use episode_id from download if we didn't have it before
            if not episode_id and downloaded_episode_id:
                episode_id = downloaded_episode_id
                transcript_file = AUDIO_DIR / f"episode_{episode_id}.txt"
            
            if audio_file:
                logger.info(f"✓ Audio downloaded successfully: {audio_file}")
                file_size_mb = audio_file.stat().st_size / (1024 * 1024) if audio_file.exists() else 0
                logger.info(f"  Audio file size: {file_size_mb:.1f} MB")
                # Transcribe audio and save to file
                logger.info("-" * 80)
                logger.info("Step 2: Transcribing audio with Gemini...")
                logger.info(f"Audio file: {audio_file}")
                logger.info("This may take several minutes depending on audio length...")
                logger.info("-" * 80)
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
            logger.info("-" * 80)
            logger.info("Step 3: Generating summary from shownotes and transcript...")
            logger.info(f"Shownotes length: {len(shownotes_text)} characters")
            logger.info(f"Transcript length: {len(transcript)} characters")
            logger.info("This may take a few minutes...")
            logger.info("-" * 80)
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
        def format_shownotes(text):
            """Format shownotes text with proper paragraph breaks."""
            if not text:
                return ""
            # Escape HTML first
            text = html_module.escape(text)
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
            text = html_module.escape(text)
            
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
                    section_escaped = html_module.escape(section)
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
                            quote_escaped = html_module.escape(quote)
                            formatted_parts.append(f'<li style="margin-bottom: 10px;">{quote_escaped}</li>')
                        formatted_parts.append('</ol>')
                        in_quotes_section = False
                        continue
                    
                    # If no quotes found, escape and format as paragraph
                    section_escaped = html_module.escape(section)
                    formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{section_escaped}</p>')
                    in_quotes_section = False
                    continue
                
                # Escape HTML for content sections
                section_escaped = html_module.escape(section)
                
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
                        content_escaped = html_module.escape(content)
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
                                    para_text_escaped = html_module.escape(para_text)
                                    formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para_text_escaped}</p>')
                                current_para = []
                            
                            # Get list item content
                            if i + 1 < len(parts):
                                item_content = parts[i + 1].strip()
                                if item_content:
                                    # Escape HTML for list items
                                    item_content_escaped = html_module.escape(item_content)
                                    if part == '*':
                                        # Unordered list
                                        if not in_unordered_list:
                                            if in_ordered_list and current_list:
                                                formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                                                for item in current_list:
                                                    formatted_parts.append(f'<li style="margin-bottom: 10px;">{html_module.escape(item)}</li>')
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
                                                    formatted_parts.append(f'<li style="margin-bottom: 10px;">{html_module.escape(item)}</li>')
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
                            para_text_escaped = html_module.escape(para_text)
                            formatted_parts.append(f'<p style="margin-bottom: 15px; line-height: 1.8;">{para_text_escaped}</p>')
            
            # Handle list at end (escape HTML)
            if in_ordered_list and current_list:
                formatted_parts.append('<ol style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                for item in current_list:
                    formatted_parts.append(f'<li style="margin-bottom: 10px;">{html_module.escape(item)}</li>')
                formatted_parts.append('</ol>')
            elif in_unordered_list and current_list:
                formatted_parts.append('<ul style="margin-bottom: 15px; padding-left: 25px; line-height: 1.8;">')
                for item in current_list:
                    formatted_parts.append(f'<li style="margin-bottom: 10px;">{html_module.escape(item)}</li>')
                formatted_parts.append('</ul>')
            
            return ''.join(formatted_parts)
        
        title_escaped = html_module.escape(result.title)
        # For Xiaoyuzhou: author is the podcast show name (result.category), category is "播客"
        author_escaped = html_module.escape(result.category)  # Podcast show name (e.g., "商业就是这样")
        category_escaped = html_module.escape("播客")  # Unified category
        url_escaped = html_module.escape(url)
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
        # For Xiaoyuzhou: author is the podcast show name (result.category), category is "播客"
        podcast_name_safe = sanitize_filename(result.category)  # Podcast show name (e.g., "商业就是这样")
        category_safe = sanitize_filename("播客")  # Unified category
        title_safe = sanitize_filename(result.title)
        
        # Build filename: use podcast name as author field in filename
        filename = f"{date_str}_xiaoyuzhou_{category_safe}_{podcast_name_safe}_{title_safe}.html"
        filepath = os.path.join(output_dir, filename)
        
        # Save HTML (only save to output_dir, like WeChat articles - no translation needed)
        try:
            logger.info("-" * 80)
            logger.info("Step 4: Saving HTML file...")
            logger.info(f"Output file: {filepath}")
            logger.info("-" * 80)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(html_content)
            logger.info(f"✓ Saved Xiaoyuzhou episode to: {filepath}")
            
            # Create and save metadata JSON file (same as other articles)
            # For Xiaoyuzhou: author should be the podcast show name (category), category should be "播客"
            metadata = {
                "date": date_str,
                "category": "播客",  # Unified category for all Xiaoyuzhou podcasts
                "author": result.category,  # Podcast show name (e.g., "商业就是这样")
                "source": self.get_source_name(),
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