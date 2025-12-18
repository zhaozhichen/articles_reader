#!/usr/bin/env python3
"""
Script to import articles from JSON metadata files into the database.

Usage:
    python import_articles.py [--directory DIR]
"""
import sys
import argparse
import asyncio
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.importer import import_articles_from_directory
from app.config import HTML_DIR

def main():
    parser = argparse.ArgumentParser(
        description='Import articles from JSON metadata files into database'
    )
    parser.add_argument(
        '--directory',
        type=str,
        default=None,
        help=f'Directory containing HTML and JSON files (default: {HTML_DIR})'
    )
    
    args = parser.parse_args()
    
    directory = Path(args.directory) if args.directory else HTML_DIR
    
    if not directory.exists():
        print(f"Error: Directory {directory} does not exist", file=sys.stderr)
        sys.exit(1)
    
    print(f"Importing articles from {directory}...", file=sys.stderr)
    
    try:
        count = await import_articles_from_directory(directory)
        print(f"Successfully imported {count} articles", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Error importing articles: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()

