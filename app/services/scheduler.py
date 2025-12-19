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
        
        # Run the script asynchronously to avoid blocking the event loop
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=18000  # 5 hours timeout
        )
        
        if result.returncode == 0:
            logger.info(f"Scraping completed successfully for {date_str}")
            logger.info(f"Script output: {result.stdout}")
        else:
            logger.error(f"Scraping failed for {date_str}")
            logger.error(f"Error output: {result.stderr}")
            logger.warning("Script failed, but will still attempt to import any articles that were saved")
        
        # Import articles into database regardless of script exit code
        # This ensures articles are imported even if script was interrupted
        logger.info("Importing articles into database (initial import)...")
        try:
            # Run in thread pool to avoid blocking
            import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
            logger.info(f"Imported {import_count} articles into database")
        except Exception as e:
            logger.error(f"Error importing articles: {str(e)}", exc_info=True)
        
        # If translation was enabled, re-import after a short delay to pick up any translations
        # that completed after the initial import
        if '--translate' in cmd:
            logger.info("Translation was enabled, waiting 30 seconds then re-importing to update translation paths...")
            await asyncio.sleep(30)  # Wait for any in-progress translations to complete
            
            logger.info("Re-importing articles to update translation paths...")
            try:
                # Run in thread pool to avoid blocking
                import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
                logger.info(f"Re-imported {import_count} articles (updated translation paths)")
            except Exception as e:
                logger.error(f"Error re-importing articles: {str(e)}", exc_info=True)
            
    except subprocess.TimeoutExpired:
        logger.error("Scraping script timed out after 5 hours")
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

