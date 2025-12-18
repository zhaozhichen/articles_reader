"""SQLAlchemy database models."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from app.database import Base

class Article(Base):
    """Article model for storing article metadata and file paths."""
    __tablename__ = "articles"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, nullable=False, index=True)
    title_zh = Column(String, nullable=True)  # Chinese title (optional)
    date = Column(DateTime, nullable=False, index=True)  # Publication date
    category = Column(String, nullable=False, index=True)
    author = Column(String, nullable=False, index=True)
    source = Column(String, nullable=False, default="The New Yorker", index=True)
    original_url = Column(String, nullable=False, unique=True)
    html_file_en = Column(String, nullable=False)  # Path to English HTML file
    html_file_zh = Column(String, nullable=True)  # Path to Chinese HTML file (optional)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

