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
        
        # Check if this is a verification/paywall page
        verification_text = soup.get_text()
        if 'verify access' in verification_text.lower() or 'please exit and log' in verification_text.lower():
            # Try to extract content from JSON-LD or other data sources
            body_element = self._extract_from_json_ld(soup)
            if body_element:
                return str(body_element), body_element
            
            # Try to extract from JavaScript data
            body_element = self._extract_from_javascript(html)
            if body_element:
                return str(body_element), body_element
        
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
    
    def _extract_from_javascript(self, html: str) -> Optional[BeautifulSoup]:
        """Try to extract article content from JavaScript variables in the page."""
        import re
        
        # Try to find window.__INITIAL_STATE__ or similar
        patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.+?});',
            r'window\.__PRELOADED_STATE__\s*=\s*({.+?});',
            r'"articleBody":\s*"([^"]+)"',
            r'"articleBody":\s*\'([^\']+)\'',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html, re.DOTALL)
            for match in matches:
                try:
                    if match.startswith('{'):
                        # It's a JSON object
                        data = json.loads(match)
                        if isinstance(data, dict):
                            # Recursively search for articleBody
                            article_body = self._find_article_body_in_dict(data)
                            if article_body and len(article_body) > 200:
                                body_soup = BeautifulSoup(f'<div class="extracted-body">{article_body}</div>', 'html.parser')
                                return body_soup.find('div')
                    else:
                        # It's a string (articleBody content)
                        if len(match) > 200:
                            # Unescape HTML entities
                            import html as html_module
                            match = html_module.unescape(match)
                            body_soup = BeautifulSoup(f'<div class="extracted-body">{match}</div>', 'html.parser')
                            return body_soup.find('div')
                except (json.JSONDecodeError, AttributeError):
                    continue
        
        return None
    
    def _find_article_body_in_dict(self, data: dict, depth: int = 0) -> Optional[str]:
        """Recursively search for articleBody in a nested dictionary."""
        if depth > 10:  # Prevent infinite recursion
            return None
        
        if 'articleBody' in data:
            body = data['articleBody']
            if isinstance(body, str) and len(body) > 200:
                return body
        
        for key, value in data.items():
            if isinstance(value, dict):
                result = self._find_article_body_in_dict(value, depth + 1)
                if result:
                    return result
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        result = self._find_article_body_in_dict(item, depth + 1)
                        if result:
                            return result
        
        return None
    
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
    
    def _is_url(self, text: str) -> bool:
        """Check if text is a URL."""
        if not text:
            return False
        text = text.strip()
        # Check for common URL patterns
        return (text.startswith('http://') or 
                text.startswith('https://') or 
                text.startswith('www.') or
                'facebook.com' in text.lower() or
                'twitter.com' in text.lower() or
                'linkedin.com' in text.lower() or
                'instagram.com' in text.lower() or
                'nytimes.com' in text.lower())
    
    def _clean_author(self, author: str) -> Optional[str]:
        """Clean and validate author name."""
        if not author:
            return None
        author = author.strip()
        
        # Skip if it's a URL
        if self._is_url(author):
            return None
        
        # Skip if it looks like a URL path
        if author.startswith('/') or (author.count('/') > 2 and 'http' not in author):
            return None
        
        # Skip if it's too short or looks invalid
        if len(author) < 2 or author.lower() in ['unknown', 'none', 'n/a', '']:
            return None
        
        # Remove common URL patterns that might slip through
        author = re.sub(r'https?://[^\s]+', '', author).strip()
        if not author or self._is_url(author):
            return None
        
        return author
    
    def _extract_author_from_link(self, link_element) -> Optional[str]:
        """Extract author name from a link element, preferring text over URL."""
        if not link_element:
            return None
        
        # First try to get text from the link
        author_text = link_element.get_text().strip()
        if author_text:
            cleaned = self._clean_author(author_text)
            if cleaned:
                return cleaned
        
        # If no text, try to extract from href
        href = link_element.get('href', '')
        if href:
            # Extract name from NYTimes author URLs like /by/author-name or /writers/author-name
            match = re.search(r'/(?:by|writers|authors?)/([^/?]+)', href)
            if match:
                author_text = match.group(1).replace('-', ' ').title()
                cleaned = self._clean_author(author_text)
                if cleaned:
                    return cleaned
        
        return None
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract author name from article HTML."""
        # Try JSON-LD first (most reliable)
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict):
                    # Check for author in various formats
                    if 'author' in data:
                        author = data['author']
                        author_name = None
                        if isinstance(author, dict):
                            # Prefer 'name' field
                            if 'name' in author:
                                author_name = author['name']
                                # If name is a URL, try to extract from it
                                if self._is_url(author_name):
                                    match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', author_name)
                                    if match:
                                        author_name = match.group(1).replace('-', ' ').title()
                                    else:
                                        # Can't extract from URL, try url field instead
                                        author_name = None
                            elif '@type' in author and author.get('@type') == 'Person' and 'name' in author:
                                author_name = author['name']
                                # If name is a URL, try to extract from it
                                if self._is_url(author_name):
                                    match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', author_name)
                                    if match:
                                        author_name = match.group(1).replace('-', ' ').title()
                                    else:
                                        author_name = None
                            # If no name but has url, try to extract from url
                            if not author_name and 'url' in author:
                                url = author['url']
                                if isinstance(url, str) and self._is_url(url):
                                    match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', url)
                                    if match:
                                        author_name = match.group(1).replace('-', ' ').title()
                        elif isinstance(author, list) and len(author) > 0:
                            first_author = author[0]
                            if isinstance(first_author, dict):
                                if 'name' in first_author:
                                    author_name = first_author['name']
                                    # If name is a URL, try to extract from it
                                    if self._is_url(author_name):
                                        match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', author_name)
                                        if match:
                                            author_name = match.group(1).replace('-', ' ').title()
                                        else:
                                            author_name = None
                                # If no name but has url, try to extract from url
                                if not author_name and 'url' in first_author:
                                    url = first_author['url']
                                    if isinstance(url, str) and self._is_url(url):
                                        match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', url)
                                        if match:
                                            author_name = match.group(1).replace('-', ' ').title()
                            elif isinstance(first_author, str):
                                author_name = first_author
                        elif isinstance(author, str):
                            author_name = author
                        
                        if author_name:
                            # Try cleaning first (handles non-URL cases)
                            cleaned = self._clean_author(author_name)
                            if cleaned:
                                return cleaned
                            # If cleaning failed and it's a URL, try to extract name from it
                            if self._is_url(author_name):
                                match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', author_name)
                                if match:
                                    extracted = match.group(1).replace('-', ' ').title()
                                    cleaned = self._clean_author(extracted)
                                    if cleaned:
                                        return cleaned
                            # Skip this source and continue
                            continue
            except (json.JSONDecodeError, KeyError):
                continue
        
        # Try meta tag
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            author_name = author_meta.get('content')
            # Always try _clean_author first (it handles URLs)
            cleaned = self._clean_author(author_name)
            if cleaned:
                return cleaned
            # If _clean_author failed and it's a URL, try NYTimes-specific URL pattern
            if self._is_url(author_name):
                # Extract name from NYTimes author URL like https://www.nytimes.com/by/elaine-sciolino
                match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', author_name)
                if match:
                    author_name = match.group(1).replace('-', ' ').title()
                    cleaned = self._clean_author(author_name)
                    if cleaned:
                        return cleaned
                # If we can't extract from URL, skip this source
        
        # Try meta name="author"
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta and author_meta.get('content'):
            author_name = author_meta.get('content')
            # Always try _clean_author first (it handles URLs)
            cleaned = self._clean_author(author_name)
            if cleaned:
                return cleaned
            # If _clean_author failed and it's a URL, try NYTimes-specific URL pattern
            if self._is_url(author_name):
                # Extract name from NYTimes author URL
                match = re.search(r'/(?:by|writers|authors?|columnists)/([^/?]+)', author_name)
                if match:
                    author_name = match.group(1).replace('-', ' ').title()
                    cleaned = self._clean_author(author_name)
                    if cleaned:
                        return cleaned
                # If we can't extract from URL, skip this source
        
        # Try to find author in byline links (NYTimes often uses links)
        byline_links = soup.find_all('a', href=re.compile(r'/by/|/writers/|/authors?/|/columnists/'))
        for link in byline_links:
            author_name = self._extract_author_from_link(link)
            if author_name:
                return author_name
        
        # Try to find author in byline text
        byline_elements = soup.find_all(['span', 'div', 'p'], class_=re.compile(r'byline|author', re.I))
        for byline in byline_elements:
            # Check if byline contains a link - prefer link text
            link = byline.find('a', href=re.compile(r'/by/|/writers/|/authors?/|/columnists/'))
            if link:
                author_name = self._extract_author_from_link(link)
                if author_name:
                    return author_name
            
            # Otherwise, get text from byline
            author_text = byline.get_text().strip()
            # Remove "By " prefix if present
            author_text = re.sub(r'^By\s+', '', author_text, flags=re.I)
            # Remove common suffixes
            author_text = re.sub(r'\s*[|•]\s*.*$', '', author_text)  # Remove everything after | or •
            if author_text:
                cleaned = self._clean_author(author_text)
                if cleaned:
                    return cleaned
        
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

