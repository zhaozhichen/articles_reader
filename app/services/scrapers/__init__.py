"""Article scrapers for different sources."""
from typing import Optional
from app.services.scrapers.base import BaseScraper
from app.services.scrapers.newyorker import NewYorkerScraper
from app.services.scrapers.nytimes import NewYorkTimesScraper
from app.services.scrapers.atlantic import AtlanticScraper
from app.services.scrapers.wechat import WeChatScraper

# Registry of all available scrapers
SCRAPERS: list[BaseScraper] = [
    NewYorkerScraper(),
    NewYorkTimesScraper(),
    AtlanticScraper(),
    WeChatScraper(),
]

__all__ = [
    'BaseScraper',
    'NewYorkerScraper',
    'NewYorkTimesScraper',
    'AtlanticScraper',
    'WeChatScraper',
    'get_scraper_for_url',
    'SCRAPERS',
]


def get_scraper_for_url(url: str) -> Optional[BaseScraper]:
    """Get the appropriate scraper for a given URL.
    
    Args:
        url: URL to find a scraper for
        
    Returns:
        BaseScraper instance that can handle the URL, or None if no scraper found
    """
    for scraper in SCRAPERS:
        if scraper.can_handle(url):
            return scraper
    return None

