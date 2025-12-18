#!/usr/bin/env python3
"""
Update articles with category 'na' to 'New Yorker' in the database.
"""
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Article
from datetime import datetime

def update_na_category():
    """Update all articles with category 'na' to 'New Yorker'."""
    db = SessionLocal()
    updated_count = 0
    
    try:
        # Find all articles with category 'na'
        articles = db.query(Article).filter(Article.category == 'na').all()
        
        print(f"Found {len(articles)} articles with category 'na'", file=sys.stderr)
        
        for article in articles:
            article.category = 'New Yorker'
            article.updated_at = datetime.utcnow()
            updated_count += 1
            print(f"  Updating: {article.title} (ID: {article.id})", file=sys.stderr)
        
        db.commit()
        print(f"\nSuccessfully updated {updated_count} articles from 'na' to 'New Yorker'", file=sys.stderr)
        
    except Exception as e:
        db.rollback()
        print(f"Error updating articles: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
    
    return updated_count

if __name__ == '__main__':
    count = update_na_category()
    sys.exit(0 if count >= 0 else 1)

