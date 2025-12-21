"""Unified logging utility for scripts and application.

This module provides a unified logging interface that ensures all output
goes to the application log file in real-time. Scripts should use this
instead of print() to sys.stderr.
"""
import logging
import sys
import logging.handlers
from pathlib import Path
from app.config import LOG_DIR
import pytz
from datetime import datetime

# Custom formatter that converts time to EST (same as main.py)
class ESTFormatter(logging.Formatter):
    """Formatter that converts time to Eastern Time."""
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        self.eastern = pytz.timezone('America/New_York')
    
    def formatTime(self, record, datefmt=None):
        """Format time in EST timezone."""
        ct = datetime.fromtimestamp(record.created, tz=self.eastern)
        if datefmt:
            s = ct.strftime(datefmt)
        else:
            t = ct.strftime("%Y-%m-%d %H:%M:%S")
            s = f"{t} EST"
        return s

def setup_script_logger(name: str = "script") -> logging.Logger:
    """Setup a logger for scripts that writes to the main log file.
    
    This logger writes to the same log file as the main application,
    ensuring all output is unified and real-time.
    
    Args:
        name: Logger name (default: "script")
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Don't add handlers if they already exist
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    
    # Get the root logger's file handler (if it exists)
    root_logger = logging.getLogger()
    file_handler = None
    
    for handler in root_logger.handlers:
        if isinstance(handler, logging.handlers.TimedRotatingFileHandler):
            file_handler = handler
            break
    
    # If no file handler exists, create one
    if not file_handler:
        log_file = LOG_DIR / "articles.log"
        file_handler = logging.handlers.TimedRotatingFileHandler(
            log_file,
            when='midnight',
            interval=1,
            backupCount=30,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        formatter = ESTFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Ensure immediate flushing for real-time visibility
        original_emit = file_handler.emit
        def emit_with_flush(record):
            original_emit(record)
            if hasattr(file_handler.stream, 'flush'):
                file_handler.stream.flush()
        file_handler.emit = emit_with_flush
    
    # Add file handler to script logger
    logger.addHandler(file_handler)
    
    # Also add console handler for immediate feedback (to stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.INFO)
    formatter = ESTFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False
    
    return logger

# Create a default script logger that can be imported
script_logger = setup_script_logger("script")

