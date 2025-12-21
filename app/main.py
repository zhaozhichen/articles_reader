"""Main FastAPI application."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from app.database import engine, Base
from app.routers import articles, web
from app.config import HOST, PORT
from app.services.scheduler import start_scheduler, stop_scheduler

# Configure logging
from app.config import LOG_DIR
import logging.handlers
import pytz
from datetime import datetime

# Create logs directory if it doesn't exist
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Custom formatter that converts time to EST
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

# Configure root logger with both file and console handlers
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Remove existing handlers to avoid duplicates
if not root_logger.handlers:
    # File handler - daily rotating log files
    log_file = LOG_DIR / "articles.log"
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_file,
        when='midnight',
        interval=1,
        backupCount=30,  # Keep 30 days of logs
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)
    file_formatter = ESTFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    # Ensure immediate flushing for real-time log visibility
    import sys
    if hasattr(file_handler.stream, 'flush'):
        # Force flush after each log entry by wrapping the handler
        original_emit = file_handler.emit
        def emit_with_flush(record):
            original_emit(record)
            file_handler.stream.flush()
        file_handler.emit = emit_with_flush

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = ESTFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)

    # Add handlers
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events."""
    # Startup
    logger.info("Starting Articles backend server...")
    
    # Create database tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
    
    # Start scheduler
    start_scheduler()
    logger.info("Scheduler started")
    
    yield
    
    # Shutdown
    stop_scheduler()
    
    # Shutdown
    logger.info("Shutting down Articles backend server...")

# Create FastAPI app
app = FastAPI(
    title="Articles Backend API",
    description="Backend server for Articles web app - NY Times article reader",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(articles.router)
app.include_router(web.router)

# Mount static files
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except:
    pass  # Static directory might not exist

# Serve index.html at root
@app.get("/", include_in_schema=False)
async def serve_index():
    """Serve the web app index page."""
    index_path = os.path.join("static", "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Articles Backend API", "version": "1.0.0", "status": "running"}

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)

