#!/usr/bin/env python3
"""
Update articles with source/category 'New Yorker' to 'The New Yorker' in the database.
"""
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models import Article
from datetime import datetime

def update_new_yorker():
    """Update all articles with source/category 'New Yorker' to 'The New Yorker'."""
    db = SessionLocal()
    updated_source_count = 0
    updated_category_count = 0
    
    try:
        # Update source
        articles_source = db.query(Article).filter(Article.source == 'New Yorker').all()
        print(f"Found {len(articles_source)} articles with source 'New Yorker'", file=sys.stderr)
        
        for article in articles_source:
            article.source = 'The New Yorker'
            article.updated_at = datetime.utcnow()
            updated_source_count += 1
        
        # Update category
        articles_category = db.query(Article).filter(Article.category == 'New Yorker').all()
        print(f"Found {len(articles_category)} articles with category 'New Yorker'", file=sys.stderr)
        
        for article in articles_category:
            article.category = 'The New Yorker'
            article.updated_at = datetime.utcnow()
            updated_category_count += 1
        
        db.commit()
        print(f"\nSuccessfully updated {updated_source_count} articles' source from 'New Yorker' to 'The New Yorker'", file=sys.stderr)
        print(f"Successfully updated {updated_category_count} articles' category from 'New Yorker' to 'The New Yorker'", file=sys.stderr)
        
    except Exception as e:
        db.rollback()
        print(f"Error updating articles: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
    
    return updated_source_count + updated_category_count

if __name__ == '__main__':
    count = update_new_yorker()
    sys.exit(0 if count >= 0 else 1)

