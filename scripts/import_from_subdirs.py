#!/usr/bin/env python3
"""Script to import articles from en/ and zh/ subdirectories."""
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.importer import import_articles_from_directory
from app.config import HTML_DIR_EN

if __name__ == "__main__":
    print(f"Importing articles from {HTML_DIR_EN}...")
    count = import_articles_from_directory(HTML_DIR_EN)
    print(f"Import completed. Processed {count} articles.")

