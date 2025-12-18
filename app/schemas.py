"""Pydantic schemas for request/response validation."""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

class ArticleBase(BaseModel):
    """Base article schema."""
    title: str
    title_zh: Optional[str] = None
    date: datetime
    category: str
    author: str
    source: str = "The New Yorker"
    original_url: str

class ArticleCreate(ArticleBase):
    """Schema for creating an article."""
    html_file_en: str
    html_file_zh: Optional[str] = None

class ArticleResponse(ArticleBase):
    """Schema for article response."""
    id: str
    html_file_en: str
    html_file_zh: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ArticleListResponse(BaseModel):
    """Schema for paginated article list response."""
    articles: list[ArticleResponse]
    total: int
    page: int
    limit: int
    total_pages: int

class FilterOptionsResponse(BaseModel):
    """Schema for filter options response."""
    categories: list[str]
    authors: list[str]
    sources: list[str]
    date_range: dict[str, Optional[str]]  # {"min": "2025-01-01", "max": "2025-12-31"}

