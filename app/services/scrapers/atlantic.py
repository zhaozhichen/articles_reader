"""Atlantic article scraper."""
import json
import re
import logging
from datetime import datetime, date
from typing import Optional, Tuple, List
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    
    def extract_article_urls_from_page(self, html_content: str) -> List[str]:
        """Extract article URLs from the /latest page."""
        urls = []
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Find all article links - Atlantic uses <article> tags with links inside
        articles = soup.find_all('article')
        for article in articles:
            # Find the main link in the article
            link = article.find('a', href=True)
            if link:
                url = link.get('href')
                if url:
                    # Make sure it's a full URL
                    if url.startswith('/'):
                        url = f'https://www.theatlantic.com{url}'
                    # Only include actual article URLs
                    if url.startswith('https://www.theatlantic.com/') and \
                       not url.endswith('/latest') and \
                       '/latest?' not in url and \
                       url not in urls:
                        urls.append(url)
        
        # Also try to find links in list items (backup method)
        if not urls:
            list_items = soup.find_all('li')
            for li in list_items:
                link = li.find('a', href=True)
                if link:
                    url = link.get('href')
                    if url and url.startswith('https://www.theatlantic.com/') and \
                       not url.endswith('/latest') and \
                       '/latest?' not in url and \
                       url not in urls:
                        urls.append(url)
        
        return urls
    
    def get_article_date(self, url: str) -> Tuple[Optional[date], Optional[date]]:
        """Fetch an article and return its publish and modified dates.
        
        Returns a tuple of (publish_date, modified_date) where either may be None.
        """
        html = self.fetch_page(url, verbose=False)
        if html:
            soup = BeautifulSoup(html, 'html.parser')
            publish_date = self._extract_publish_date(soup)
            # Atlantic doesn't typically provide modified_date in a separate field
            # So we return (publish_date, None)
            return (publish_date, None)
        return (None, None)
    
    def find_articles_by_date(self, target_date: date, max_workers: int = 10) -> List[str]:
        """
        Find all articles published on the target date.
        
        Atlantic's /latest page shows articles in reverse chronological order.
        We only need to check the first page since it contains all recent articles.
        
        Args:
            target_date: datetime.date object for the target date
            max_workers: Number of concurrent workers for fetching articles
        
        Returns:
            List of article URLs matching the date
        """
        matching_urls = []
        
        logger.info(f"Searching for Atlantic articles published on {target_date}...")
        logger.info(f"Fetching /latest page...")
        
        # Fetch the /latest page
        url = "https://www.theatlantic.com/latest/"
        html = self.fetch_page(url, verbose=True)
        if not html:
            logger.error(f"Failed to fetch /latest page")
            return []
        
        article_urls = self.extract_article_urls_from_page(html)
        
        if not article_urls:
            logger.warning(f"No articles found on /latest page")
            return []
        
        logger.info(f"Found {len(article_urls)} articles on /latest page. Checking dates...")
        
        # Check publish dates for articles
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {
                executor.submit(self.get_article_date, url): url 
                for url in article_urls
            }
            
            completed = 0
            for future in as_completed(future_to_url):
                article_url = future_to_url[future]
                completed += 1
                try:
                    publish_date, modified_date = future.result()
                    
                    # Check if publish date matches target
                    matches = False
                    date_str = ""
                    if publish_date == target_date:
                        matches = True
                        date_str = f"publish: {publish_date}"
                    elif publish_date:
                        date_str = f"publish: {publish_date}"
                    
                    if matches:
                        matching_urls.append(article_url)
                        logger.info(f"  [{completed}/{len(article_urls)}] ✓ {article_url} ({date_str})")
                    elif publish_date:
                        # Determine if article is newer or older
                        if publish_date > target_date:
                            logger.debug(f"  [{completed}/{len(article_urls)}] ✗ {article_url} ({date_str}, newer)")
                        else:
                            logger.debug(f"  [{completed}/{len(article_urls)}] ✗ {article_url} ({date_str}, older)")
                    else:
                        # Couldn't determine date
                        logger.debug(f"  [{completed}/{len(article_urls)}] ✗ {article_url} (date: not found)")
                except Exception as e:
                    logger.error(f"  [{completed}/{len(article_urls)}] Error processing {article_url}: {e}", exc_info=True)
        
        logger.info(f"\nFound {len(matching_urls)} Atlantic articles published on {target_date}")
        return matching_urls

