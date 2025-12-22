#!/usr/bin/env python3
"""
Migration script to add starred column to articles table.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine, SessionLocal
from sqlalchemy import text

def migrate():
    """Add starred column to articles table if it doesn't exist."""
    db = SessionLocal()
    try:
        # Check if column already exists
        result = db.execute(text("""
            SELECT COUNT(*) as count 
            FROM pragma_table_info('articles') 
            WHERE name = 'starred'
        """))
        count = result.fetchone()[0]
        
        if count > 0:
            print("Column 'starred' already exists. Skipping migration.")
            return
        
        # Add starred column
        print("Adding 'starred' column to articles table...")
        db.execute(text("""
            ALTER TABLE articles 
            ADD COLUMN starred BOOLEAN NOT NULL DEFAULT 0
        """))
        
        # Create index for better query performance
        print("Creating index on 'starred' column...")
        db.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_articles_starred 
            ON articles(starred)
        """))
        
        db.commit()
        print("Migration completed successfully!")
        
    except Exception as e:
        db.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate()

