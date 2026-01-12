"""Audio file cleanup service - removes files older than TTL days."""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from app.config import AUDIO_DIR

logger = logging.getLogger(__name__)

def cleanup_old_audio_files(ttl_days: int = 5) -> dict:
    """Clean up audio files (MP3) and transcript files (TXT) older than TTL days.
    
    Args:
        ttl_days: Time to live in days (default: 5)
        
    Returns:
        Dictionary with cleanup statistics:
        {
            'total_files': int,
            'deleted_files': int,
            'deleted_size_mb': float,
            'remaining_files': int
        }
    """
    if not AUDIO_DIR.exists():
        logger.warning(f"Audio directory does not exist: {AUDIO_DIR}")
        return {
            'total_files': 0,
            'deleted_files': 0,
            'deleted_size_mb': 0.0,
            'remaining_files': 0
        }
    
    cutoff_time = datetime.now() - timedelta(days=ttl_days)
    cutoff_timestamp = cutoff_time.timestamp()
    
    # Get both MP3 and TXT files
    all_files = list(AUDIO_DIR.glob("*.mp3")) + list(AUDIO_DIR.glob("*.txt"))
    total_files = len(all_files)
    deleted_files = 0
    deleted_size_mb = 0.0
    
    logger.info(f"Starting audio cleanup: checking {total_files} files in {AUDIO_DIR}")
    logger.info(f"Cutoff time: {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')} (files older than {ttl_days} days will be deleted)")
    
    for audio_file in all_files:
        try:
            # Get file modification time
            mtime = audio_file.stat().st_mtime
            mtime_datetime = datetime.fromtimestamp(mtime)
            
            if mtime < cutoff_timestamp:
                # File is older than TTL, delete it
                file_size_mb = audio_file.stat().st_size / (1024 * 1024)
                audio_file.unlink()
                deleted_files += 1
                deleted_size_mb += file_size_mb
                logger.info(f"Deleted old audio file: {audio_file.name} (modified: {mtime_datetime.strftime('%Y-%m-%d %H:%M:%S')}, size: {file_size_mb:.2f}MB)")
        except Exception as e:
            logger.error(f"Error processing file {audio_file.name}: {e}", exc_info=True)
    
    remaining_files = total_files - deleted_files
    
    result = {
        'total_files': total_files,
        'deleted_files': deleted_files,
        'deleted_size_mb': round(deleted_size_mb, 2),
        'remaining_files': remaining_files
    }
    
    logger.info(f"Audio cleanup completed: deleted {deleted_files}/{total_files} files ({deleted_size_mb:.2f}MB), {remaining_files} files remaining")
    
    return result
