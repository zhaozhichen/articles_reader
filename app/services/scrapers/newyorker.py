"""New Yorker article scraper."""
import json
import re
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from app.services.scrapers.base import BaseScraper


class NewYorkerScraper(BaseScraper):
    """Scraper for New Yorker articles."""
    
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL."""
        return url.startswith('https://www.newyorker.com/')
    
    def get_source_name(self) -> str:
        """Get the name of the source this scraper handles."""
        return "New Yorker"
    
    def get_source_slug(self) -> str:
        """Get a URL-safe slug identifier for the source."""
        return "newyorker"
    
    def extract_category(self, url: str, html: str) -> str:
        """Extract category from URL path.
        
        Examples:
        - https://www.newyorker.com/books/book-currents/... -> 'books'
        - https://www.newyorker.com/culture/postscript/... -> 'culture'
        - https://www.newyorker.com/best-books-2025 -> 'New Yorker'
        """
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        
        # Common categories to look for
        categories = ['news', 'books', 'culture', 'magazine', 'humor', 'cartoons', 'archive', 
                      'crossword-puzzles-and-games', 'goings-on', 'puzzles-and-games-dept', 
                      'newsletter', 'video', 'fiction-and-poetry', 'podcasts', 'podcast']
        
        for category in categories:
            if path.startswith(f'{category}/') or path == category:
                return category
        
        # If no category found, return 'New Yorker'
        return 'New Yorker'
    
    def extract_metadata(self, html: str, url: str) -> dict:
        """Extract metadata from article HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract title
        title = self._extract_title(soup)
        
        # Extract author
        author = self._extract_author(soup)
        
        # Extract date
        publish_date, modified_date = self._extract_publish_date(soup)
        # Use modified date if available, otherwise publish date
        article_date = modified_date if modified_date else publish_date
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
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title from HTML."""
        # Try og:title meta tag first
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title.get('content')
        
        # Try title tag
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text().strip()
            # Remove " | New Yorker" suffix if present
            title = re.sub(r'\s*\|\s*New Yorker\s*$', '', title)
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
    
    def _extract_publish_date(self, soup: BeautifulSoup) -> Tuple[Optional[datetime.date], Optional[datetime.date]]:
        """Extract publish date from article HTML.
        
        Returns a tuple of (publish_date, modified_date) where either may be None.
        """
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
    
    def extract_article_urls_from_page(self, html_content: str) -> list:
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
    
    def get_article_date(self, url: str) -> Tuple[Optional[datetime.date], Optional[datetime.date]]:
        """Fetch an article and return its publish and modified dates.
        
        Returns a tuple of (publish_date, modified_date) where either may be None.
        """
        html = self.fetch_page(url, verbose=False)
        if html:
            soup = BeautifulSoup(html, 'html.parser')
            return self._extract_publish_date(soup)
        return (None, None)
    
    def find_articles_by_date(self, target_date: datetime.date, max_pages: int = 100, max_workers: int = 10) -> list:
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
        
        import sys
        print(f"Searching for articles published on {target_date}...", file=sys.stderr)
        print(f"Scanning /latest pages (will stop early if all articles are older)...", file=sys.stderr)
        
        # Process pages one by one, checking dates as we go
        while page <= max_pages:
            url = f"https://www.newyorker.com/latest?page={page}"
            print(f"\nFetching page {page}...", file=sys.stderr)
            
            html = self.fetch_page(url, verbose=True)
            if not html:
                print(f"Failed to fetch page {page}, stopping.", file=sys.stderr)
                break
            
            article_urls = self.extract_article_urls_from_page(html)
            
            if not article_urls:
                print(f"No articles found on page {page}, stopping.", file=sys.stderr)
                break
            
            print(f"Found {len(article_urls)} articles on page {page}. Checking dates...", file=sys.stderr)
            
            # Check publish dates for articles on this page
            page_article_dates = {}
            
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

