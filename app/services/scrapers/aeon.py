"""Aeon article scraper."""
import json
import re
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, date
from typing import Optional, Tuple, List
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from app.services.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


class AeonScraper(BaseScraper):
    """Scraper for Aeon articles (essays only, filters out videos)."""
    
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL.
        
        Only handles essays URLs, filters out videos.
        """
        parsed = urlparse(url)
        # Only handle essays, not videos
        return parsed.netloc in {'aeon.co', 'www.aeon.co'} and parsed.path.startswith('/essays/')
    
    def get_source_name(self) -> str:
        """Get the name of the source this scraper handles."""
        return "Aeon"
    
    def get_source_slug(self) -> str:
        """Get a URL-safe slug identifier for the source."""
        return "aeon"
    
    def extract_category(self, url: str, html: str) -> str:
        """Extract category from URL path or JSON-LD breadcrumb.
        
        Examples:
        - https://aeon.co/essays/... -> extract from breadcrumb or URL
        - Categories: philosophy, science, psychology, society, culture
        """
        # Try to extract from JSON-LD breadcrumb first
        try:
            soup = BeautifulSoup(html, 'html.parser')
            json_ld_scripts = soup.find_all('script', type='application/ld+json')
            for script in json_ld_scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                        items = data.get('itemListElement', [])
                        if items and len(items) > 0:
                            # First item is usually the category
                            first_item = items[0]
                            if isinstance(first_item, dict):
                                name = first_item.get('name', '')
                                if name and name.lower() not in {'essays', 'aeon', 'home'}:
                                    return name
                except (json.JSONDecodeError, KeyError, AttributeError):
                    continue
        except Exception:
            pass
        
        # Fallback: extract from URL path
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        
        # Common Aeon categories
        categories = ['philosophy', 'science', 'psychology', 'society', 'culture']
        for part in path_parts:
            if part.lower() in categories:
                return part.capitalize()
        
        # Default fallback
        return 'Essays'
    
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
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract title from JSON-LD or HTML."""
        # Try JSON-LD first
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    headline = data.get('headline')
                    if headline:
                        return headline.strip()
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Try OpenGraph
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()
        
        # Try h1
        h1 = soup.find('h1')
        if h1:
            title_text = h1.get_text(strip=True)
            if title_text:
                return title_text
        
        # Fallback to <title> tag
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            # Remove site suffix if present
            title_text = re.sub(r'\s*\|\s*Aeon.*$', '', title_text, flags=re.I)
            return title_text.strip()
        
        return 'untitled'
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract author from JSON-LD or HTML."""
        # Try JSON-LD first
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    author = data.get('author')
                    if author:
                        author_name = None
                        if isinstance(author, list) and len(author) > 0:
                            first_author = author[0]
                            if isinstance(first_author, dict):
                                author_name = first_author.get('name')
                            elif isinstance(first_author, str):
                                author_name = first_author
                        elif isinstance(author, dict):
                            author_name = author.get('name')
                        elif isinstance(author, str):
                            author_name = author
                        
                        if author_name:
                            cleaned = self._clean_author(author_name)
                            if cleaned:
                                return cleaned
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Try meta tags
        meta_author = soup.find('meta', property='article:author') or soup.find('meta', attrs={'name': 'author'})
        if meta_author and meta_author.get('content'):
            cleaned = self._clean_author(meta_author['content'])
            if cleaned:
                return cleaned
        
        # Try byline in HTML
        byline_selectors = [
            '[class*="byline"]',
            '[class*="author"]',
            'p:contains("by")',
        ]
        for selector in byline_selectors:
            if selector.startswith('p:'):
                # Simple text search for "by"
                for p in soup.find_all('p'):
                    text = p.get_text(strip=True)
                    if re.match(r'^[Bb]y\s+', text):
                        author_text = re.sub(r'^[Bb]y\s+', '', text).strip()
                        # Remove date or other suffixes
                        author_text = re.sub(r'\s*[|•].*$', '', author_text).strip()
                        cleaned = self._clean_author(author_text)
                        if cleaned:
                            return cleaned
            else:
                byline = soup.select_one(selector)
                if byline:
                    author_text = byline.get_text(strip=True)
                    author_text = re.sub(r'^[Bb]y\s+', '', author_text).strip()
                    author_text = re.sub(r'\s*[|•].*$', '', author_text).strip()
                    cleaned = self._clean_author(author_text)
                    if cleaned:
                        return cleaned
        
        return 'unknown'
    
    def _clean_author(self, author: Optional[str]) -> Optional[str]:
        """Clean author name, removing URLs and invalid values."""
        if not author:
            return None
        
        author = author.strip()
        if not author:
            return None
        
        # Remove URLs
        if author.startswith(('http://', 'https://', 'www.')):
            return None
        
        # Remove if contains too many slashes (likely a URL)
        if '/' in author and author.count('/') > 2:
            return None
        
        # Remove if too short or invalid
        if len(author) < 2 or author.lower() in {'unknown', 'none', 'n/a', 'aeon'}:
            return None
        
        # Remove embedded URLs
        author = re.sub(r'https?://\S+', '', author).strip()
        
        return author if author else None
    
    def _extract_publish_date(self, soup: BeautifulSoup) -> Optional[date]:
        """Extract publish date from JSON-LD or HTML."""
        # Try JSON-LD first
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    date_published = data.get('datePublished')
                    if date_published:
                        dt = self._parse_iso_date(date_published)
                        if dt:
                            return dt
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        # Try meta tags
        meta_date = soup.find('meta', property='article:published_time')
        if meta_date and meta_date.get('content'):
            dt = self._parse_iso_date(meta_date['content'])
            if dt:
                return dt
        
        # Try time tag
        time_tag = soup.find('time')
        if time_tag and time_tag.get('datetime'):
            dt = self._parse_iso_date(time_tag['datetime'])
            if dt:
                return dt
        
        return None
    
    def _parse_iso_date(self, date_str: Optional[str]) -> Optional[date]:
        """Parse ISO date string to date object."""
        if not date_str:
            return None
        
        try:
            # Handle ISO format with timezone
            date_str = date_str.replace('Z', '+00:00')
            dt = datetime.fromisoformat(date_str)
            return dt.date()
        except (ValueError, AttributeError):
            # Try other formats
            try:
                # Try RFC 2822 format (from RSS)
                dt = datetime.strptime(date_str, '%a, %d %b %Y %H:%M:%S %Z')
                return dt.date()
            except ValueError:
                pass
        
        return None
    
    def extract_body(self, html: str) -> Tuple[Optional[str], Optional[BeautifulSoup]]:
        """Extract the main article body content from HTML."""
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check for access restrictions
        if self._is_access_blocked(soup):
            # Try JSON-LD fallback
            body_element = self._extract_from_json_ld(soup)
            if body_element and self._is_body_sufficient(body_element):
                return str(body_element), body_element
        
        # Try main selectors for article body
        selectors = [
            'article',
            '[class*="article-body"]',
            '[class*="article-content"]',
            '[class*="essay-body"]',
            '[class*="content"]',
            'main',
        ]
        
        for selector in selectors:
            body_element = soup.select_one(selector)
            if body_element:
                # Remove noise elements
                self._remove_noise_elements(body_element)
                if self._is_body_sufficient(body_element):
                    return str(body_element), body_element
        
        # Fallback: find largest text container
        body_element = self._extract_largest_text_container(soup)
        if body_element and self._is_body_sufficient(body_element):
            return str(body_element), body_element
        
        return None, None
    
    def _is_access_blocked(self, soup: BeautifulSoup) -> bool:
        """Check if page has access restrictions."""
        text = soup.get_text(' ', strip=True).lower()
        keywords = (
            'subscribe', 'subscription', 'sign in', 'log in', 'login',
            'register', 'create account', 'verify access', 'continue reading',
            'unlock', 'trial', 'captcha', 'paywall'
        )
        if any(k in text for k in keywords):
            return True
        
        # Check for overlay/modal markers
        overlays = soup.find_all(['div', 'section'], class_=re.compile(r'paywall|subscribe|overlay|modal', re.I))
        if overlays:
            return True
        
        return False
    
    def _extract_from_json_ld(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Try to extract article body from JSON-LD structured data."""
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get('@type') == 'Article':
                    article_body = data.get('articleBody')
                    if article_body and isinstance(article_body, str):
                        # Wrap in a div for BeautifulSoup
                        wrap = BeautifulSoup(f'<div class="extracted-body">{article_body}</div>', 'html.parser')
                        return wrap.find('div')
            except (json.JSONDecodeError, KeyError, AttributeError):
                continue
        
        return None
    
    def _remove_noise_elements(self, element: BeautifulSoup):
        """Remove noise elements from article body."""
        # Remove common noise elements
        noise_selectors = [
            'nav', 'footer', 'aside', 'script', 'style',
            '[class*="subscribe"]', '[class*="newsletter"]',
            '[class*="social"]', '[class*="share"]',
            '[class*="ad"]', '[class*="advertisement"]',
        ]
        for selector in noise_selectors:
            for elem in element.select(selector):
                elem.decompose()
    
    def _extract_largest_text_container(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Find the largest text-containing container."""
        candidates = soup.find_all(['article', 'section', 'div', 'main'])
        best = None
        best_len = 0
        
        for elem in candidates:
            text = elem.get_text(' ', strip=True)
            if len(text) > best_len:
                best_len = len(text)
                best = elem
        
        return best
    
    def _is_body_sufficient(self, body: BeautifulSoup) -> bool:
        """Check if body has sufficient content."""
        text = body.get_text(' ', strip=True)
        
        # Minimum text length
        if len(text) < 200:
            return False
        
        # Check paragraph count
        paragraphs = [p.get_text(' ', strip=True) for p in body.find_all('p')]
        valid_paragraphs = [p for p in paragraphs if len(p) >= 30]
        if valid_paragraphs and len(valid_paragraphs) < 3:
            return False
        
        # Check for too much noise (subscription/login text)
        noise_keywords = ['subscribe', 'newsletter', 'sign in', 'log in']
        noise_count = sum(1 for keyword in noise_keywords if keyword in text.lower())
        if noise_count > 5:  # Too many noise keywords
            return False
        
        return True
    
    def find_articles_by_date(self, target_date: date, max_workers: int = 10) -> List[str]:
        """
        Find all essays published on the target date using RSS feed.
        
        Args:
            target_date: datetime.date object for the target date
            max_workers: Number of concurrent workers (not used for RSS, kept for API compatibility)
        
        Returns:
            List of essay URLs matching the date (videos are filtered out)
        """
        matching_urls = []
        
        logger.info(f"Searching for Aeon essays published on {target_date}...")
        logger.info(f"Fetching RSS feed...")
        
        # Fetch RSS feed
        rss_url = "https://aeon.co/feed.rss"
        try:
            response = self.fetch_page(rss_url, verbose=True)
            if not response:
                logger.error(f"Failed to fetch RSS feed from {rss_url}")
                return []
            
            # Parse RSS feed
            # Handle potential XML declaration and encoding issues
            try:
                root = ET.fromstring(response)
            except ET.ParseError:
                # Try removing XML declaration if present
                response_clean = response.lstrip()
                if response_clean.startswith('<?xml'):
                    # Find the end of XML declaration
                    end_decl = response_clean.find('?>')
                    if end_decl != -1:
                        response_clean = response_clean[end_decl + 2:].lstrip()
                root = ET.fromstring(response_clean)
            
            # Find all items (RSS 2.0 doesn't use namespaces by default)
            items = root.findall('.//item')
            logger.info(f"Found {len(items)} items in RSS feed")
            
            for item in items:
                # Extract link
                link_elem = item.find('link')
                if link_elem is None or link_elem.text is None:
                    continue
                
                link = link_elem.text.strip()
                # Remove query parameters
                link = link.split('?')[0]
                
                # Filter: only essays, not videos
                if not link.startswith('https://aeon.co/essays/'):
                    continue
                
                # Extract pubDate
                pub_date_elem = item.find('pubDate')
                if pub_date_elem is None or pub_date_elem.text is None:
                    continue
                
                pub_date_str = pub_date_elem.text.strip()
                
                # Parse date (format: "Fri, 16 Jan 2026 11:00:00 GMT")
                try:
                    pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %Z').date()
                except ValueError:
                    # Try alternative format
                    try:
                        pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z').date()
                    except ValueError:
                        logger.warning(f"Could not parse date: {pub_date_str}")
                        continue
                
                # Check if date matches target
                if pub_date == target_date:
                    matching_urls.append(link)
                    logger.info(f"  Found matching essay: {link} (published {pub_date})")
            
            logger.info(f"Found {len(matching_urls)} essays published on {target_date}")
            
        except ET.ParseError as e:
            logger.error(f"Failed to parse RSS feed: {e}")
            return []
        except Exception as e:
            logger.error(f"Error processing RSS feed: {e}", exc_info=True)
            return []
        
        return matching_urls
