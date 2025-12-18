"""Scheduler service for running daily article scraping."""
import logging
import asyncio
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from app.config import BASE_DIR, HTML_DIR, HTML_DIR_EN, HTML_DIR_ZH
from app.database import SessionLocal
from app.models import Article
from app.services.importer import import_articles_from_directory

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def run_daily_scrape():
    """Run the article scraping script for today's date (Eastern Time)."""
    try:
        # Get current date in Eastern Time
        eastern = pytz.timezone('America/New_York')
        today_et = datetime.now(eastern).date()
        date_str = today_et.strftime('%Y-%m-%d')
        
        logger.info(f"Starting daily scrape for date: {date_str}")
        
        # Path to the scraping script
        script_path = BASE_DIR / "scripts" / "extract_articles_by_date.py"
        
        if not script_path.exists():
            logger.error(f"Scraping script not found at {script_path}")
            return
        
        # Run the script with translation enabled
        # Output directory is HTML_DIR_EN (English files)
        # The script will save English files to HTML_DIR_EN
        # and Chinese translations to HTML_DIR_ZH
        cmd = [
            sys.executable,
            str(script_path),
            date_str,
            "--translate",
            "--output-dir",
            str(HTML_DIR_EN),
            "--zh-dir",
            str(HTML_DIR_ZH)
        ]
        
        # Prepare environment variables
        import os
        env = os.environ.copy()
        # GEMINI_API_KEY should already be in environment if set
        
        logger.info(f"Running command: {' '.join(cmd)}")
        
        # Run the script
        result = subprocess.run(
            cmd,
            cwd=str(BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        if result.returncode == 0:
            logger.info(f"Scraping completed successfully for {date_str}")
            logger.info(f"Script output: {result.stdout}")
            
            # Import articles into database
            logger.info("Importing articles into database...")
            # Run in thread pool to avoid blocking
            import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
            logger.info(f"Imported {import_count} articles into database")
        else:
            logger.error(f"Scraping failed for {date_str}")
            logger.error(f"Error output: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        logger.error("Scraping script timed out after 1 hour")
    except Exception as e:
        logger.error(f"Error running daily scrape: {str(e)}", exc_info=True)

def start_scheduler():
    """Start the scheduler with daily job at 7 PM Eastern Time."""
    # Schedule daily job at 7:00 PM Eastern Time
    eastern = pytz.timezone('America/New_York')
    scheduler.add_job(
        run_daily_scrape,
        trigger=CronTrigger(hour=19, minute=0, timezone=eastern),
        id='daily_scrape',
        name='Daily article scrape',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler started. Daily scrape scheduled for 7:00 PM Eastern Time")

def stop_scheduler():
    """Stop the scheduler."""
    scheduler.shutdown()
    logger.info("Scheduler stopped")

