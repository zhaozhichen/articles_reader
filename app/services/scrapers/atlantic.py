"""Atlantic article scraper."""
import json
import re
import logging
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class AtlanticScraper(BaseScraper):
    """Scraper for Atlantic articles."""
    
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL."""
        return url.startswith('https://www.theatlantic.com/')
    
    def get_source_name(self) -> str:
        """Get the name of the source this scraper handles."""
        return "Atlantic"
    
    def get_source_slug(self) -> str:
        """Get a URL-safe slug identifier for the source."""
        return "atlantic"
    
    def extract_category(self, url: str, html: str) -> str:
        """Extract category from URL path.
        
        Examples:
        - https://www.theatlantic.com/science/2025/12/... -> 'science'
        - https://www.theatlantic.com/politics/2025/12/... -> 'politics'
        """
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Extract first path segment as category
        path_parts = path.split('/')
        if len(path_parts) > 0:
            category = path_parts[0]
            # Common Atlantic categories
            categories = [
                'science', 'politics', 'business', 'technology', 'sports',
                'culture', 'ideas', 'fiction', 'photo', 'economy', 'global',
                'books', 'ai-watchdog', 'health', 'education', 'projects',
                'features', 'family', 'events', 'washington-week', 'progress',
                'national-security', 'magazine'
            ]
            if category in categories:
                return category
        
        # Try to extract from JSON-LD articleSection
        try:
            soup = BeautifulSoup(html, 'html.parser')
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                        article_section = data.get('articleSection')
                        if article_section:
                            return article_section.lower()
                except (json.JSONDecodeError, KeyError):
                    continue
        except Exception:
            pass
        
        # Default fallback
        return 'Atlantic'
    
    def extract_metadata(self, html: str, url: str) -> dict:
        """Extract metadata from article HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title = self._extract_title(soup)
        
        # Extract author
        author = self._extract_author(soup)
        
        # Extract date
        article_date = self._extract_publish_date(soup)
        if not article_date:
            # Fallback to today's date if no date found
            from datetime import date
            article_date = date.today()
        
        # Extract category
        category = self.extract_category(url, html)
        
        return {
            'title': title,
            'author': author,
            'date': article_date,
            'category': category,
            'url': url
        }
    
    def extract_body(self, html: str) -> Tuple[Optional[str], Optional[BeautifulSoup]]:
        """Extract the main article body content from HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check if this is a paywall page
        verification_text = soup.get_text()
        if 'keep reading' in verification_text.lower() or 'subscribe' in verification_text.lower():
            # Try to extract content from JSON-LD or other data sources
            body_element = self._extract_from_json_ld(soup)
            if body_element:
                return str(body_element), body_element
        
        # Try Atlantic-specific selectors for article body
        body_element = None
        
        # Atlantic uses various selectors depending on article type
        selectors = [
            ('article', {}),
            ('[class*="article-content"]', {}),
            ('[class*="article-content-body"]', {}),
            ('[class*="body"]', {}),
            ('[class*="content"]', {}),
            ('main', {}),
        ]
        
        for selector, attrs in selectors:
            if selector.startswith('['):
                # Attribute selector
                body_element = soup.select_one(selector)
            else:
                tag_name = selector.split('.')[-1] if '.' in selector else selector
                body_element = soup.find(tag_name, attrs)
            
            if body_element:
                # Check if it has substantial text content
                text_content = body_element.get_text(strip=True)
                if len(text_content) > 200:  # Has meaningful content
                    break
        
        if not body_element:
            # Fallback: find the largest text-containing element
            all_elements = soup.find_all(['article', 'section', 'div', 'main'])
            max_text_length = 0
            for elem in all_elements:
                text = elem.get_text(strip=True)
                if len(text) > max_text_length:
                    max_text_length = len(text)
                    body_element = elem
            
            if max_text_length < 200:
                return None, None
        
        return str(body_element), body_element
    
    def _extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Try to extract article content from JSON-LD structured data."""
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # Check for articleBody or text content
                    if 'articleBody' in data:
                        article_body = data['articleBody']
                        if isinstance(article_body, str) and len(article_body) > 200:
                            # Create a simple HTML structure from the text
                            body_soup = BeautifulSoup(f'<div class="extracted-body">{article_body}</div>', 'html.parser')
                            return body_soup.find('div')
                    # Check for nested articleBody
                    if '@graph' in data and isinstance(data['@graph'], list):
                        for item in data['@graph']:
                            if isinstance(item, dict) and 'articleBody' in item:
                                article_body = item['articleBody']
                                if isinstance(article_body, str) and len(article_body) > 200:
                                    body_soup = BeautifulSoup(f'<div class="extracted-body">{article_body}</div>', 'html.parser')
                                    return body_soup.find('div')
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        return None
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title from HTML."""
        # Try JSON-LD first (most reliable)
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                    headline = data.get('headline')
                    if headline:
                        return headline
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Try og:title meta tag
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
            # Remove " - The Atlantic" suffix if present
            title = re.sub(r'\s*-\s*The Atlantic\s*$', '', title)
            return title
        
        return 'untitled'
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract author name from article HTML."""
        # Try JSON-LD first
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                    author = data.get('author')
                    if author:
                        if isinstance(author, list) and len(author) > 0:
                            # Get first author
                            first_author = author[0]
                            if isinstance(first_author, dict) and 'name' in first_author:
                                return first_author['name']
                            elif isinstance(first_author, str):
                                return first_author
                        elif isinstance(author, dict) and 'name' in author:
                            return author['name']
                        elif isinstance(author, str):
                            return author
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Try meta tag
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            return author_meta.get('content')
        
        # Try meta name="author"
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta and author_meta.get('content'):
            return author_meta.get('content')
        
        # Try to find author in byline
        byline = soup.find('a', href=re.compile(r'/author/'))
        if byline:
            author_text = byline.get_text().strip()
            if author_text:
                return author_text
        
        return 'unknown'
    
    def _extract_publish_date(self, soup: BeautifulSoup) -> Optional[datetime.date]:
        """Extract publish date from article HTML."""
        # Try JSON-LD first
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'NewsArticle':
                    date_published = data.get('datePublished')
                    if date_published:
                        try:
                            dt = datetime.fromisoformat(date_published.replace('Z', '+00:00'))
                            return dt.date()
                        except (ValueError, AttributeError):
                            pass
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Try article:published_time meta tag
        meta_tag = soup.find('meta', property='article:published_time')
        if meta_tag and meta_tag.get('content'):
            date_str = meta_tag['content']
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.date()
            except (ValueError, AttributeError):
                pass
        
        # Try time tag
        time_tag = soup.find('time')
        if time_tag:
            datetime_attr = time_tag.get('datetime')
            if datetime_attr:
                try:
                    dt = datetime.fromisoformat(datetime_attr.replace('Z', '+00:00'))
                    return dt.date()
                except (ValueError, AttributeError):
                    pass
        
        return None

