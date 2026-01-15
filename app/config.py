"""Application configuration."""
import os
from pathlib import Path

# Base directory
BASE_DIR = Path(__file__).parent.parent

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/data/articles.db")

# Server configuration
# Default to localhost for local development
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# Data directories
DATA_DIR = BASE_DIR / "data"
HTML_DIR = DATA_DIR / "html"
HTML_DIR_EN = HTML_DIR / "en"
HTML_DIR_ZH = HTML_DIR / "zh"
AUDIO_DIR = DATA_DIR / "audio"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR_EN.mkdir(parents=True, exist_ok=True)
HTML_DIR_ZH.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Gemini API key (for translation)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Enable scheduled scraping (default: False)
# Set ENABLE_SCHEDULED_SCRAPING=true in .env to enable automatic daily scraping
ENABLE_SCHEDULED_SCRAPING = os.getenv("ENABLE_SCHEDULED_SCRAPING", "false").lower() == "true"

# Log directory
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

