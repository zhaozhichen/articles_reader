"""Xiaoyuzhou (小宇宙) podcast episode scraper."""
import re
import json
from datetime import datetime
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from app.services.scrapers.base import BaseScraper


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
