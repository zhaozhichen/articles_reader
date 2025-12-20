"""New York Times article scraper."""
import json
import re
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from app.services.scrapers.base import BaseScraper


class NewYorkTimesScraper(BaseScraper):
    """Scraper for New York Times articles."""
    
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL."""
        return 'nytimes.com' in url
    
    def get_source_name(self) -> str:
        """Get the name of the source this scraper handles."""
        return "New York Times"
    
    def get_source_slug(self) -> str:
        """Get a URL-safe slug identifier for the source."""
        return "nytimes"
    
    def extract_category(self, url: str, html: str) -> str:
        """Extract category from URL path or HTML.
        
        Examples:
        - https://www.nytimes.com/interactive/2025/06/30/science/... -> 'science'
        - https://www.nytimes.com/2025/06/30/politics/... -> 'politics'
        """
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Common NYT sections
        sections = [
            'science', 'politics', 'business', 'technology', 'sports', 
            'arts', 'style', 'health', 'world', 'us', 'opinion', 
            'books', 'food', 'travel', 'magazine', 't-magazine',
            'interactive', 'well', 'climate', 'realestate'
        ]
        
        # Check URL path for section
        path_parts = path.split('/')
        for part in path_parts:
            if part in sections:
                return part
        
        # Try to extract from HTML meta tags
        try:
            soup = BeautifulSoup(html, 'html.parser')
            # Check for section meta tag
            section_meta = soup.find('meta', property='article:section')
            if section_meta and section_meta.get('content'):
                section = section_meta.get('content').lower()
                # Map common section names
                section_mapping = {
                    'science': 'science',
                    'politics': 'politics',
                    'business': 'business',
                    'technology': 'technology',
                    'sports': 'sports',
                    'arts': 'arts',
                    'style': 'style',
                    'health': 'health',
                    'world': 'world',
                    'u.s.': 'us',
                    'opinion': 'opinion',
                    'books': 'books',
                    'food': 'food',
                    'travel': 'travel',
                    'magazine': 'magazine',
                    'well': 'well',
                    'climate': 'climate',
                    'real estate': 'realestate'
                }
                if section in section_mapping:
                    return section_mapping[section]
                return section
        except Exception:
            pass
        
        # Default fallback
        return 'New York Times'
    
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
        
        # Try NYT-specific selectors for article body
        body_element = None
        
        # NYT uses various selectors depending on article type
        selectors = [
            ('article', {}),
            ('section[name="articleBody"]', {}),
            ('.StoryBodyCompanionColumn', {}),
            ('.css-53u6y8', {}),  # Common NYT body class
            ('[data-module="ArticleBody"]', {}),
            ('[class*="StoryBody"]', {}),
            ('[class*="articleBody"]', {}),
            ('main', {}),
        ]
        
        for selector, attrs in selectors:
            if selector.startswith('['):
                # Attribute selector
                body_element = soup.select_one(selector)
            elif '[' in selector:
                # Tag with attribute selector
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
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title from HTML."""
        # Try h1 tag first (NYT often uses this)
        h1 = soup.find('h1')
        if h1:
            title = h1.get_text().strip()
            if title:
                return title
        
        # Try og:title meta tag
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title.get('content')
        
        # Try JSON-LD
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if 'headline' in data:
                        return data['headline']
                    elif '@type' in data and data.get('@type') == 'NewsArticle' and 'headline' in data:
                        return data['headline']
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Try title tag
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()
            # Remove " - The New York Times" suffix if present
            title = re.sub(r'\s*-\s*The New York Times\s*$', '', title)
            return title
        
        return 'untitled'
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract author name from article HTML."""
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
                        if isinstance(author, dict):
                            if 'name' in author:
                                return author['name']
                            elif '@type' in author and author.get('@type') == 'Person' and 'name' in author:
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
        
        # Try to find author in byline
        byline = soup.find('span', class_=re.compile(r'byline', re.I))
        if byline:
            author_text = byline.get_text().strip()
            # Remove "By " prefix if present
            author_text = re.sub(r'^By\s+', '', author_text, flags=re.I)
            if author_text:
                return author_text
        
        return 'unknown'
    
    def _extract_publish_date(self, soup: BeautifulSoup) -> Optional[datetime.date]:
        """Extract publish date from article HTML."""
        # Try article:published_time meta tag
        meta_tag = soup.find('meta', property='article:published_time')
        if meta_tag and meta_tag.get('content'):
            date_str = meta_tag['content']
            try:
                dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                return dt.date()
            except (ValueError, AttributeError):
                pass
        
        # Try datePublished in JSON-LD
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    if 'datePublished' in data:
                        date_str = data['datePublished']
                        try:
                            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                            return dt.date()
                        except (ValueError, AttributeError):
                            pass
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Try to extract from URL (NYT URLs often contain dates)
        # Format: /YYYY/MM/DD/section/...
        # This is handled by the caller if needed
        
        return None

