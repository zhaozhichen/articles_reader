"""Scheduler service for running daily article scraping."""
import logging
import asyncio
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from app.config import BASE_DIR, HTML_DIR, HTML_DIR_EN, HTML_DIR_ZH
from app.database import SessionLocal
from app.models import Article
from app.services.importer import import_articles_from_directory

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def run_daily_scrape(target_date_str: Optional[str] = None):
    """Run the article scraping script for a specific date or today's date (Eastern Time).
    
    Args:
        target_date_str: Optional date string in YYYY-MM-DD format. If None, uses today's date.
    """
    try:
        # Get target date
        if target_date_str:
            date_str = target_date_str
            try:
                # Validate date format
                datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                logger.error(f"Invalid date format: {target_date_str}. Use YYYY-MM-DD format.")
                return
        else:
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
        # Timeout set to 3.5 hours (12600 seconds)
        # This should be enough for ~50 articles with translation
        # Use Popen to capture output in real-time and log it
        def run_script():
            # Since scripts now use logging directly, we don't need to capture stdout/stderr
            # The script's logger will write directly to the log file
            # We just need to run the script and wait for it to complete
            process = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Still capture for any remaining print statements
                text=True,
                bufsize=0,  # Unbuffered for real-time output
                universal_newlines=True
            )
            
            # Read output line by line and log it in real-time (for any remaining print statements)
            output_lines = []
            try:
                # Use iter with readline for proper line-by-line reading
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    line = line.rstrip()
                    if line:
                        # Log any remaining print output (scripts should use logger now)
                        logger.warning(f"[Unexpected script output] {line}")
                        output_lines.append(line)
                
                # Wait for process to complete
                returncode = process.wait(timeout=12600)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                logger.error("Scraping script timed out after 3.5 hours")
                raise
            
            # Create a result object similar to subprocess.run
            class Result:
                def __init__(self, returncode, stdout, stderr=''):
                    self.returncode = returncode
                    self.stdout = stdout
                    self.stderr = stderr
            
            return Result(returncode, '\n'.join(output_lines))
        
        result = await asyncio.to_thread(run_script)
        
        if result.returncode == 0:
            logger.info(f"Scraping completed successfully for {date_str}")
        else:
            logger.error(f"Scraping failed for {date_str} (exit code: {result.returncode})")
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
        logger.error("Scraping script timed out after 3.5 hours")
        # Still try to import any articles that were saved before timeout
        logger.info("Attempting to import articles saved before timeout...")
        try:
            import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
            logger.info(f"Imported {import_count} articles (saved before timeout)")
        except Exception as e:
            logger.error(f"Error importing articles after timeout: {str(e)}", exc_info=True)
    except asyncio.CancelledError:
        logger.warning("Daily scrape task was cancelled (likely due to server restart)")
        # Still try to import any articles that were saved before cancellation
        logger.info("Attempting to import articles saved before cancellation...")
        try:
            import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
            logger.info(f"Imported {import_count} articles (saved before cancellation)")
        except Exception as e:
            logger.error(f"Error importing articles after cancellation: {str(e)}", exc_info=True)
        # Re-raise CancelledError to allow proper cleanup
        raise
    except Exception as e:
        logger.error(f"Error running daily scrape: {str(e)}", exc_info=True)
        # Still try to import any articles that were saved before error
        logger.info("Attempting to import articles saved before error...")
        try:
            import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
            logger.info(f"Imported {import_count} articles (saved before error)")
        except Exception as import_error:
            logger.error(f"Error importing articles after error: {str(import_error)}", exc_info=True)

def start_scheduler():
    """Start the scheduler with daily jobs at 7 PM and 11 PM Eastern Time."""
    eastern = pytz.timezone('America/New_York')
    
    # Schedule daily job at 7:00 PM Eastern Time (full scrape and translate)
    scheduler.add_job(
        run_daily_scrape,
        trigger=CronTrigger(hour=19, minute=0, timezone=eastern),
        id='daily_scrape',
        name='Daily article scrape',
        replace_existing=True
    )
    
    # Schedule same job at 11:00 PM Eastern Time
    # If 7 PM job completed, this will be a no-op (script skips existing files)
    # If 7 PM job didn't complete, this will continue the work
    scheduler.add_job(
        run_daily_scrape,
        trigger=CronTrigger(hour=23, minute=0, timezone=eastern),
        id='daily_scrape_backup',
        name='Daily article scrape (backup)',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler started. Daily scrape scheduled for 7:00 PM Eastern Time")
    logger.info("Backup scrape scheduled for 11:00 PM Eastern Time")
    
    # On startup, check if there are any unimported articles from today
    # This helps recover from interrupted scraping tasks
    try:
        import asyncio
        asyncio.create_task(recover_unimported_articles())
    except Exception as e:
        logger.warning(f"Could not start recovery task: {e}")

async def recover_unimported_articles():
    """Recover and import any articles that were saved but not imported due to interruption.
    
    This function checks ALL articles in the directory, not just today's articles.
    This ensures manually added articles (regardless of date) are imported on server startup.
    """
    try:
        # Wait a bit for the server to fully start
        await asyncio.sleep(5)
        
        logger.info("Checking for unimported articles (all dates)...")
        
        # Get all HTML files in the directory
        en_files = list(HTML_DIR_EN.glob("*.html"))
        
        if not en_files:
            logger.info("No HTML files found in directory")
            return
        
        logger.info(f"Found {len(en_files)} HTML files in directory")
        
        # Import all articles - the import function will skip duplicates
        # This ensures any manually added articles are imported
        import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
        logger.info(f"Recovery import completed: {import_count} articles processed (new or updated)")
        
    except Exception as e:
        logger.error(f"Error in recovery task: {e}", exc_info=True)

def stop_scheduler():
    """Stop the scheduler gracefully, waiting for running jobs to complete."""
    # Get running jobs
    running_jobs = scheduler.get_jobs()
    if running_jobs:
        logger.info(f"Shutting down scheduler. {len(running_jobs)} job(s) scheduled.")
    
    # Shutdown scheduler - this will cancel pending jobs but running jobs will continue
    # Use wait=False to allow running jobs to complete, but cancel pending ones
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")

