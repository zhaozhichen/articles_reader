"""Base scraper interface and common functionality."""
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple
import requests
from bs4 import BeautifulSoup

# Create a session to maintain cookies across requests
_session = requests.Session()


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
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate',  # Removed 'br' (Brotli) as requests doesn't support it by default
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Referer': 'https://www.google.com/',  # Add referer to appear more like a real user
        }
        for attempt in range(max_retries):
            try:
                # Use session to maintain cookies
                response = _session.get(url, headers=headers, timeout=30)
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
    
    def save_article(self, url: str, result: ScraperResult, date_str: str, output_dir: str, 
                     zh_dir: str = None, gemini_api_key: str = None, **kwargs) -> Tuple[Optional[str], Optional[str]]:
        """Save article HTML to file. Override in subclasses for custom saving logic.
        
        Args:
            url: Article URL
            result: ScraperResult from scraping
            date_str: Date string for filename (YYYY-MM-DD)
            output_dir: Output directory for English files
            zh_dir: Directory for Chinese translations (optional)
            gemini_api_key: Gemini API key for translation (optional)
            **kwargs: Additional arguments for subclasses
            
        Returns:
            Tuple of (original_filepath, translated_filepath) where translated_filepath may be None
        """
        # Default implementation: save HTML as-is
        # Subclasses can override this for custom behavior (e.g., Xiaoyuzhou with audio processing)
        import os
        from pathlib import Path
        
        # This is a placeholder - subclasses should override
        raise NotImplementedError("Subclasses should implement save_article or use default save logic")

