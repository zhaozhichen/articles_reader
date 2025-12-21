"""Web app API endpoints."""
import logging
from typing import Optional
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Query, HTTPException, status
from pydantic import BaseModel
from app.config import LOG_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web", tags=["web"])

class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str
    message: str

class LogResponse(BaseModel):
    logs: list[LogEntry]
    total_lines: int
    date: str

@router.get("/logs", response_model=LogResponse)
async def get_logs(
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format (default: today)"),
    lines: int = Query(100, ge=1, le=5000, description="Number of lines to retrieve (max 5000)")
):
    """
    Get application logs for a specific date.
    
    - **date**: Date in YYYY-MM-DD format (default: today)
    - **lines**: Number of lines to retrieve (default: 100, max: 5000)
    """
    try:
        # Determine which log file to read
        if date:
            try:
                log_date = datetime.strptime(date, '%Y-%m-%d').date()
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid date format. Use YYYY-MM-DD"
                )
        else:
            log_date = datetime.now().date()
        
        # Try to read the log file for the specified date
        log_file = LOG_DIR / "articles.log"
        
        # If the date is not today, check for rotated log files
        if log_date != datetime.now().date():
            # TimedRotatingFileHandler creates files with .YYYY-MM-DD suffix
            log_file = LOG_DIR / f"articles.log.{log_date.strftime('%Y-%m-%d')}"
        
        if not log_file.exists():
            return LogResponse(
                logs=[],
                total_lines=0,
                date=log_date.strftime('%Y-%m-%d')
            )
        
        # Read log file
        log_entries = []
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                total_lines = len(all_lines)
                
                # Get last N lines
                lines_to_read = min(lines, total_lines)
                recent_lines = all_lines[-lines_to_read:] if lines_to_read > 0 else []
                
                # Parse log entries
                for line in recent_lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Parse log format: "2025-12-17 23:21:39,123 - logger_name - LEVEL - message"
                    parts = line.split(' - ', 3)
                    if len(parts) >= 4:
                        timestamp = parts[0].strip()
                        logger_name = parts[1].strip()
                        level = parts[2].strip()
                        message = parts[3].strip()
                        
                        log_entries.append(LogEntry(
                            timestamp=timestamp,
                            level=level,
                            logger=logger_name,
                            message=message
                        ))
                    else:
                        # If parsing fails, include the whole line as message
                        log_entries.append(LogEntry(
                            timestamp="",
                            level="INFO",
                            logger="",
                            message=line
                        ))
                
                # Reverse to show most recent first
                log_entries.reverse()
                
        except Exception as e:
            logger.error(f"Error reading log file: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error reading log file: {str(e)}"
            )
        
        return LogResponse(
            logs=log_entries,
            total_lines=total_lines,
            date=log_date.strftime('%Y-%m-%d')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting logs: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting logs: {str(e)}"
        )

@router.get("/logs/dates")
async def get_available_log_dates():
    """
    Get list of available log dates.
    """
    try:
        dates = []
        
        # Check main log file
        main_log = LOG_DIR / "articles.log"
        if main_log.exists():
            dates.append(datetime.now().date().strftime('%Y-%m-%d'))
        
        # Check rotated log files
        for log_file in LOG_DIR.glob("articles.log.*"):
            try:
                # Extract date from filename (articles.log.YYYY-MM-DD)
                date_str = log_file.name.replace("articles.log.", "")
                datetime.strptime(date_str, '%Y-%m-%d')
                dates.append(date_str)
            except ValueError:
                continue
        
        dates.sort(reverse=True)  # Most recent first
        return {"dates": dates}
        
    except Exception as e:
        logger.error(f"Error getting log dates: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting log dates: {str(e)}"
        )

