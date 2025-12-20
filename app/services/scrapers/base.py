"""Base scraper interface and common functionality."""
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple
import requests
from bs4 import BeautifulSoup


@dataclass
class ScraperResult:
    """Result from scraping an article."""
    title: str
    author: str
    date: date
    category: str
    url: str
    html: str
    body_html: Optional[str] = None
    body_element: Optional[BeautifulSoup] = None


class BaseScraper(ABC):
    """Abstract base class for article scrapers."""
    
    def fetch_page(self, url: str, max_retries: int = 3, verbose: bool = True) -> Optional[str]:
        """Fetch a page with retries and random delays to reduce IP ban risk.
        
        Args:
            url: URL to fetch
            max_retries: Maximum number of retry attempts
            verbose: Whether to print progress messages
            
        Returns:
            HTML content as string, or None if fetch failed
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                
                # Random delay after successful request (3-7 seconds) to reduce IP ban risk
                if verbose:
                    delay = random.uniform(3, 7)
                    print(f"    Waiting {delay:.1f}s before next request...", file=__import__('sys').stderr)
                    time.sleep(delay)
                else:
                    time.sleep(random.uniform(3, 7))
                
                return response.text
            except requests.RequestException as e:
                if attempt == max_retries - 1:
                    if verbose:
                        print(f"Error fetching {url}: {e}", file=__import__('sys').stderr)
                    return None
                # Wait before retry
                if verbose:
                    delay = random.uniform(3, 7)
                    print(f"    Retry after {delay:.1f}s...", file=__import__('sys').stderr)
                    time.sleep(delay)
                else:
                    time.sleep(random.uniform(3, 7))
                continue
        return None
    
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL.
        
        Args:
            url: URL to check
            
        Returns:
            True if this scraper can handle the URL, False otherwise
        """
        pass
    
    @abstractmethod
    def extract_metadata(self, html: str, url: str) -> dict:
        """Extract metadata from article HTML.
        
        Args:
            html: HTML content of the article page
            url: Original URL of the article
            
        Returns:
            Dictionary with keys: title, author, date (datetime.date), category, url
        """
        pass
    
    @abstractmethod
    def extract_body(self, html: str) -> Tuple[Optional[str], Optional[BeautifulSoup]]:
        """Extract the main article body content from HTML.
        
        Args:
            html: Full HTML content of the article page
            
        Returns:
            Tuple of (body_html, body_element) where:
            - body_html: HTML string of the body section
            - body_element: BeautifulSoup element of the body
            Either may be None if extraction fails.
        """
        pass
    
    @abstractmethod
    def get_source_name(self) -> str:
        """Get the name of the source this scraper handles.
        
        Returns:
            Source name (e.g., "New Yorker", "New York Times")
        """
        pass
    
    @abstractmethod
    def get_source_slug(self) -> str:
        """Get a URL-safe slug identifier for the source.
        
        Returns:
            Source slug (e.g., "newyorker", "nytimes")
        """
        pass
    
    @abstractmethod
    def extract_category(self, url: str, html: str) -> str:
        """Extract category from URL or HTML.
        
        Args:
            url: Article URL
            html: HTML content (may be used as fallback)
            
        Returns:
            Category name as string
        """
        pass
    
    def scrape(self, url: str, verbose: bool = True) -> Optional[ScraperResult]:
        """Scrape an article from a URL.
        
        Args:
            url: URL of the article to scrape
            verbose: Whether to print progress messages
            
        Returns:
            ScraperResult object, or None if scraping failed
        """
        html = self.fetch_page(url, verbose=verbose)
        if not html:
            return None
        
        metadata = self.extract_metadata(html, url)
        body_html, body_element = self.extract_body(html)
        
        return ScraperResult(
            title=metadata.get('title', 'untitled'),
            author=metadata.get('author', 'unknown'),
            date=metadata.get('date'),
            category=metadata.get('category', ''),
            url=metadata.get('url', url),
            html=html,
            body_html=body_html,
            body_element=body_element
        )

