#!/usr/bin/env python3
"""
Update articles with source 'new yorker' to 'New Yorker' in the database.
"""
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Article
from datetime import datetime

def update_source():
    """Update all articles with source 'new yorker' to 'New Yorker'."""
    db = SessionLocal()
    updated_count = 0
    
    try:
        # Find all articles with source 'new yorker'
        articles = db.query(Article).filter(Article.source == 'new yorker').all()
        
        print(f"Found {len(articles)} articles with source 'new yorker'", file=sys.stderr)
        
        for article in articles:
            article.source = 'New Yorker'
            article.updated_at = datetime.utcnow()
            updated_count += 1
            print(f"  Updating: {article.title} (ID: {article.id})", file=sys.stderr)
        
        db.commit()
        print(f"\nSuccessfully updated {updated_count} articles from 'new yorker' to 'New Yorker'", file=sys.stderr)
        
    except Exception as e:
        db.rollback()
        print(f"Error updating articles: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
    
    return updated_count

if __name__ == '__main__':
    count = update_source()
    sys.exit(0 if count >= 0 else 1)

