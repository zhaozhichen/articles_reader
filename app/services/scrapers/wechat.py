"""WeChat Official Account (微信公众号) article scraper."""
import json
import re
from datetime import datetime
from typing import Optional, Tuple
from bs4 import BeautifulSoup
from app.services.scrapers.base import BaseScraper


class WeChatScraper(BaseScraper):
    """Scraper for WeChat Official Account (微信公众号) articles."""
    
    def can_handle(self, url: str) -> bool:
        """Check if this scraper can handle the given URL."""
        return url.startswith('https://mp.weixin.qq.com/s/')
    
    def get_source_name(self) -> str:
        """Get the name of the source this scraper handles."""
        return "公众号"
    
    def get_source_slug(self) -> str:
        """Get a URL-safe slug identifier for the source."""
        return "wechat"
    
    def extract_category(self, url: str, html: str) -> str:
        """Extract category from HTML.
        
        For WeChat articles, the category is the official account name (公众号名称).
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try to find official account name from various sources
        # 1. Look for profile_nickname in script tags
        scripts = soup.find_all('script')
        for script in scripts:
            if script.string:
                # Pattern: var profile_nickname = "公众号名称";
                match = re.search(r'profile_nickname\s*[:=]\s*["\']([^"\']+)["\']', script.string, re.IGNORECASE)
                if match:
                    nickname = match.group(1)
                    if nickname and nickname != 'Weixin Official Accounts Platform':
                        return nickname
                
                # Pattern: "nickname":"公众号名称"
                match = re.search(r'["\']nickname["\']\s*:\s*["\']([^"\']+)["\']', script.string, re.IGNORECASE)
                if match:
                    nickname = match.group(1)
                    if nickname and nickname != 'Weixin Official Accounts Platform':
                        return nickname
        
        # 2. Try to find in page title (format: "文章标题 - 公众号名称")
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text().strip()
            if ' - ' in title_text:
                parts = title_text.split(' - ')
                if len(parts) > 1:
                    account_name = parts[-1].strip()
                    if account_name and account_name != 'Weixin Official Accounts Platform':
                        return account_name
        
        # 3. Fallback
        return '公众号'
    
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
            from datetime import date
            article_date = date.today()
        
        # Extract category (which is the official account name for WeChat)
        category = self.extract_category(url, html)
        
        return {
            'title': title,
            'author': author,
            'date': article_date,
            'category': category,
            'url': url
        }
    
    def extract_body(self, html: str) -> Tuple[Optional[str], Optional[BeautifulSoup]]:
        """Extract the main article body content from HTML.
        
        For WeChat articles, the main content is in #js_content div.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try to find the main content area (#js_content)
        js_content = soup.find('div', id='js_content')
        if js_content:
            return str(js_content), js_content
        
        # Fallback: try other common WeChat article selectors
        selectors = [
            ('div', {'class': re.compile(r'rich_media_content', re.I)}),
            ('article', {}),
            ('main', {}),
        ]
        
        for tag_name, attrs in selectors:
            if 'class' in attrs:
                body_element = soup.find(tag_name, class_=attrs['class'])
            else:
                body_element = soup.find(tag_name)
            
            if body_element:
                text_content = body_element.get_text(strip=True)
                if len(text_content) > 200:  # Has meaningful content
                    return str(body_element), body_element
        
        # Last resort: return the full HTML body
        body_element = soup.find('body')
        if body_element:
            return str(body_element), body_element
        
        return html, soup
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """Extract article title from HTML."""
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
            # Remove account name suffix if present (format: "Title - Account Name")
            title = re.sub(r'\s*-\s*[^-]+$', '', title)
            return title
        
        return 'untitled'
    
    def _extract_author(self, soup: BeautifulSoup) -> str:
        """Extract author name from article HTML."""
        # Try meta name="author"
        author_meta = soup.find('meta', attrs={'name': 'author'})
        if author_meta and author_meta.get('content'):
            author = author_meta.get('content')
            if author and author != 'Weixin Official Accounts Platform':
                return author
        
        # Try meta property="article:author"
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            author = author_meta.get('content')
            if author and author != 'Weixin Official Accounts Platform':
                return author
        
        return 'unknown'
    
    def _extract_publish_date(self, soup: BeautifulSoup) -> Optional[datetime.date]:
        """Extract publish date from article HTML."""
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
        
        return None

