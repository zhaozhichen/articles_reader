"""Article API endpoints."""
import logging
import asyncio
import subprocess
import sys
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from pathlib import Path
from app.database import get_db
from app.models import Article
from app.schemas import ArticleResponse, ArticleListResponse, FilterOptionsResponse
from app.config import HTML_DIR, HTML_DIR_EN, HTML_DIR_ZH, BASE_DIR, GEMINI_API_KEY
from app.services.importer import import_articles_from_directory
from app.services.scrapers import get_scraper_for_url
from bs4 import BeautifulSoup

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/articles", tags=["articles"])

# Queue for article import tasks to ensure only one import runs at a time
_import_queue: asyncio.Queue = asyncio.Queue()
_import_lock = asyncio.Lock()
_import_worker_running = False


async def _process_article_import_task(
    url: str,
    scraper,
    script_path: Path,
    timeout_seconds: int,
    env: Dict[str, Any],
    db: Session
) -> Dict[str, Any]:
    """Process a single article import task."""
    try:
        logger.info(f"Running command: python {script_path} --url {url}")
        
        cmd = [
            sys.executable,
            str(script_path),
            "--url",
            url,
            "--output-dir",
            str(HTML_DIR_EN),
            "--zh-dir",
            str(HTML_DIR_ZH)
        ]
        
        # For WeChat and Xiaoyuzhou articles, do not translate
        if scraper.get_source_slug() not in ['wechat', 'xiaoyuzhou']:
            cmd.append("--translate")
        
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(BASE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            logger.error(f"Scraping failed: {error_msg}")
            raise Exception(f"Failed to scrape article: {error_msg}")
        
        logger.info(f"Scraping completed successfully")
        logger.info(f"Script output: {result.stdout}")
        
        # Import articles into database
        logger.info("Importing article into database...")
        import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
        logger.info(f"Imported {import_count} articles into database")
        
        # Get the newly imported article
        new_article = db.query(Article).filter(Article.original_url == url).first()
        if not new_article:
            # Try to find by checking recent imports
            new_article = db.query(Article).order_by(Article.created_at.desc()).first()
        
        if new_article:
            # Mark manually uploaded articles as starred by default
            try:
                if not new_article.starred:
                    new_article.starred = True
                    db.commit()
                    logger.info(f"Marked manually uploaded article as starred: {new_article.id}")
            except Exception as e:
                logger.warning(f"Failed to mark article as starred: {e}", exc_info=True)
                try:
                    db.rollback()
                except:
                    pass
            
            return {
                "success": True,
                "message": "Article added successfully",
                "article": ArticleResponse.model_validate(new_article)
            }
        else:
            return {
                "success": True,
                "message": "Article processed but not found in database",
                "import_count": import_count
            }
            
    except subprocess.TimeoutExpired as e:
        try:
            scraper_check = get_scraper_for_url(url)
            timeout_minutes = 30 if scraper_check and scraper_check.get_source_slug() == 'xiaoyuzhou' else 10
        except:
            timeout_minutes = 30
        logger.error(f"Scraping script timed out after {timeout_minutes} minutes")
        raise Exception(f"Scraping timed out after {timeout_minutes} minutes. For Xiaoyuzhou episodes, this may take longer due to audio download and transcription.")
    except Exception as e:
        logger.error(f"Error processing article import task: {str(e)}", exc_info=True)
        raise


async def _import_worker():
    """Worker function that processes import tasks from the queue."""
    global _import_worker_running
    _import_worker_running = True
    logger.info("Import worker started")
    
    while True:
        try:
            # Get task from queue (wait indefinitely)
            task = await _import_queue.get()
            
            if task is None:  # Shutdown signal
                logger.info("Import worker received shutdown signal")
                break
            
            url, scraper, script_path, timeout_seconds, env, db, future = task
            
            logger.info(f"Processing queued import task for URL: {url} (queue size: {_import_queue.qsize()})")
            
            try:
                result = await _process_article_import_task(
                    url, scraper, script_path, timeout_seconds, env, db
                )
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                _import_queue.task_done()
                
        except Exception as e:
            logger.error(f"Error in import worker: {str(e)}", exc_info=True)
            if 'future' in locals():
                future.set_exception(e)
            _import_queue.task_done()
    
    _import_worker_running = False
    logger.info("Import worker stopped")


def _ensure_worker_running():
    """Ensure the import worker is running."""
    global _import_worker_running
    if not _import_worker_running:
        # In FastAPI, we're always in an async context, so create_task is safe
        asyncio.create_task(_import_worker())


@router.get("", response_model=ArticleListResponse)
async def list_articles(
    category: Optional[str] = Query(None, description="Filter by category"),
    author: Optional[str] = Query(None, description="Filter by author"),
    source: Optional[str] = Query(None, description="Filter by source"),
    date_from: Optional[str] = Query(None, description="Filter by date from (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter by date to (YYYY-MM-DD)"),
    starred: Optional[bool] = Query(None, description="Filter by starred status (true/false)"),
    search: Optional[str] = Query(None, description="Search keyword in article titles"),
    lang: Optional[str] = Query(None, description="Filter by language: 'en' or 'zh'"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    sort: str = Query("date_desc", description="Sort order: date_desc, date_asc"),
    db: Session = Depends(get_db)
):
    """
    Get paginated list of articles with filtering and sorting.
    
    - **category**: Filter by category
    - **author**: Filter by author
    - **source**: Filter by source
    - **date_from**: Filter articles from this date (YYYY-MM-DD)
    - **date_to**: Filter articles to this date (YYYY-MM-DD)
    - **starred**: Filter by starred status (true/false)
    - **search**: Search keyword in article titles (searches both title and title_zh)
    - **lang**: Filter by language ('en' for English only, 'zh' for Chinese only)
    - **page**: Page number (starts from 1)
    - **limit**: Items per page (max 100)
    - **sort**: Sort order (date_desc, date_asc)
    """
    try:
        # Build query
        query = db.query(Article)
        
        logger.info(f"Received request: search='{search}', lang='{lang}', page={page}, limit={limit}")
        
        # Apply search filter first (search in the appropriate language field based on lang parameter)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            logger.info(f"Searching for '{search.strip()}' in language '{lang}'")
            if lang == "zh":
                # Search only in Chinese title when in Chinese mode
                query = query.filter(Article.title_zh.isnot(None), Article.title_zh != "")
                query = query.filter(Article.title_zh.ilike(search_term))
                logger.info(f"Applied filter: title_zh contains '{search.strip()}'")
            elif lang == "en":
                # Search only in English title when in English mode
                query = query.filter(Article.title.isnot(None), Article.title != "")
                query = query.filter(Article.title.ilike(search_term))
                logger.info(f"Applied filter: title contains '{search.strip()}'")
            else:
                # If no lang specified, search in both
                query = query.filter(
                    or_(
                        Article.title.ilike(search_term),
                        Article.title_zh.ilike(search_term)
                    )
                )
                logger.info(f"Applied filter: title or title_zh contains '{search.strip()}'")
        elif lang:
            # Apply language filter only if no search (to show all articles in that language)
            if lang == "zh":
                # Only return articles with Chinese title
                query = query.filter(Article.title_zh.isnot(None), Article.title_zh != "")
            elif lang == "en":
                # Only return articles with English title (all articles should have this, but filter for consistency)
                query = query.filter(Article.title.isnot(None), Article.title != "")
        
        # Apply filters
        if category:
            query = query.filter(Article.category == category)
        if author:
            query = query.filter(Article.author == author)
        if source:
            query = query.filter(Article.source == source)
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                query = query.filter(Article.date >= date_from_obj)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid date_from format. Use YYYY-MM-DD"
                )
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                query = query.filter(Article.date <= date_to_obj)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid date_to format. Use YYYY-MM-DD"
                )
        if starred is not None:
            query = query.filter(Article.starred == starred)
        
        # Get total count
        total = query.count()
        logger.info(f"Total articles matching filters: {total}")
        
        # Apply sorting
        if sort == "date_asc":
            query = query.order_by(Article.date.asc())
        else:  # date_desc (default)
            query = query.order_by(Article.date.desc())
        
        # Apply pagination
        offset = (page - 1) * limit
        articles = query.offset(offset).limit(limit).all()
        logger.info(f"Returning {len(articles)} articles for page {page}")
        
        # Calculate total pages
        total_pages = (total + limit - 1) // limit
        
        return ArticleListResponse(
            articles=[ArticleResponse.model_validate(article) for article in articles],
            total=total,
            page=page,
            limit=limit,
            total_pages=total_pages
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing articles: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing articles: {str(e)}"
        )

@router.get("/{article_id}", response_model=ArticleResponse)
async def get_article(
    article_id: str,
    db: Session = Depends(get_db)
):
    """
    Get a specific article by ID.
    """
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article not found"
            )
        
        return ArticleResponse.model_validate(article)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting article: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting article: {str(e)}"
        )

@router.get("/{article_id}/html")
async def get_article_html(
    article_id: str,
    lang: str = Query("en", description="Language: 'en' or 'zh'"),
    db: Session = Depends(get_db)
):
    """
    Get article HTML content.
    
    - **lang**: Language code ('en' for English, 'zh' for Chinese)
    """
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article not found"
            )
        
        # Determine which file to serve based on language
        # Files are stored in /en or /zh subdirectories with same filename
        if lang == "zh":
            # Use zh subdirectory
            if article.html_file_zh:
                # Extract filename from path (could be "zh/filename.html" or just "filename.html")
                zh_path = Path(article.html_file_zh)
                if zh_path.parts[0] == 'zh':
                    # Path already includes 'zh/' prefix
                    filename = zh_path.name
                    file_path = HTML_DIR_ZH / filename
                else:
                    # Just filename, use zh subdirectory
                    file_path = HTML_DIR_ZH / zh_path.name
            else:
                # Use the same filename from en file in zh subdirectory
                filename = Path(article.html_file_en).name
                file_path = HTML_DIR_ZH / filename
            
            # If Chinese file doesn't exist, fallback to English version
            if not file_path.exists():
                logger.warning(f"Chinese version not found for {article.id}, falling back to English")
                # Fallback to English version
                en_path = Path(article.html_file_en)
                if en_path.parts[0] == 'en':
                    filename = en_path.name
                    file_path = HTML_DIR_EN / filename
                else:
                    file_path = HTML_DIR_EN / en_path.name
        else:
            # Use en subdirectory
            en_path = Path(article.html_file_en)
            if en_path.parts[0] == 'en':
                # Path already includes 'en/' prefix
                filename = en_path.name
                file_path = HTML_DIR_EN / filename
            else:
                # Just filename, use en subdirectory
                file_path = HTML_DIR_EN / en_path.name
        
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"HTML file not found: {file_path}"
            )
        
        # Read HTML content and return as response
        # Don't set filename to prevent download
        from fastapi.responses import Response
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        return Response(
            content=html_content,
            media_type="text/html"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving article HTML: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error serving article HTML: {str(e)}"
        )

@router.get("/filters/options", response_model=FilterOptionsResponse)
async def get_filter_options(
    db: Session = Depends(get_db)
):
    """
    Get available filter options (categories, authors, sources, date range).
    """
    try:
        # Get distinct categories
        categories = db.query(Article.category).distinct().all()
        categories_list = [cat[0] for cat in categories if cat[0]]
        
        # Get distinct authors
        authors = db.query(Article.author).distinct().all()
        authors_list = [auth[0] for auth in authors if auth[0]]
        
        # Get distinct sources
        sources = db.query(Article.source).distinct().all()
        sources_list = [src[0] for src in sources if src[0]]
        
        # Get date range
        min_date = db.query(func.min(Article.date)).scalar()
        max_date = db.query(func.max(Article.date)).scalar()
        
        date_range = {
            "min": min_date.strftime('%Y-%m-%d') if min_date else None,
            "max": max_date.strftime('%Y-%m-%d') if max_date else None
        }
        
        return FilterOptionsResponse(
            categories=sorted(categories_list),
            authors=sorted(authors_list),
            sources=sorted(sources_list),
            date_range=date_range
        )
        
    except Exception as e:
        logger.error(f"Error getting filter options: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting filter options: {str(e)}"
        )

class AddArticleRequest(BaseModel):
    url: str

@router.put("/{article_id}/star")
async def toggle_star_article(
    article_id: str,
    db: Session = Depends(get_db)
):
    """
    Toggle the starred status of an article.
    
    - **article_id**: ID of the article to star/unstar
    """
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Article with id {article_id} not found"
            )
        
        # Toggle starred status
        article.starred = not article.starred
        db.commit()
        db.refresh(article)
        
        logger.info(f"Toggled star status for article {article_id}: {article.starred}")
        
        return ArticleResponse.model_validate(article)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error toggling star status for article {article_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error toggling star status: {str(e)}"
        )

@router.delete("/{article_id}")
async def delete_article(
    article_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete an article by ID.
    Deletes both the database record and the associated HTML files.
    """
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article not found"
            )
        
        # Get file paths
        en_file = None
        zh_file = None
        
        if article.html_file_en:
            en_path = Path(article.html_file_en)
            if en_path.parts[0] == 'en':
                filename = en_path.name
                en_file = HTML_DIR_EN / filename
            else:
                en_file = HTML_DIR_EN / en_path.name
        
        if article.html_file_zh:
            zh_path = Path(article.html_file_zh)
            if zh_path.parts[0] == 'zh':
                filename = zh_path.name
                zh_file = HTML_DIR_ZH / filename
            else:
                zh_file = HTML_DIR_ZH / zh_path.name
        
        # Delete files
        deleted_files = []
        if en_file and en_file.exists():
            en_file.unlink()
            deleted_files.append(str(en_file))
            logger.info(f"Deleted EN file: {en_file}")
            
            # Delete corresponding JSON metadata file
            json_file = en_file.with_suffix('.json')
            if json_file.exists():
                json_file.unlink()
                deleted_files.append(str(json_file))
                logger.info(f"Deleted JSON file: {json_file}")
        
        if zh_file and zh_file.exists():
            zh_file.unlink()
            deleted_files.append(str(zh_file))
            logger.info(f"Deleted ZH file: {zh_file}")
        
        # Delete database record
        article_title = article.title
        db.delete(article)
        db.commit()
        
        logger.info(f"Deleted article: {article_title} (ID: {article_id})")
        
        return {
            "message": "Article deleted successfully",
            "deleted_files": deleted_files
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting article: {str(e)}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting article: {str(e)}"
        )

@router.post("/add-from-url")
async def add_article_from_url(
    request: AddArticleRequest,
    db: Session = Depends(get_db)
):
    """
    Manually add an article by URL.
    
    - **url**: Article URL to scrape and add
    """
    try:
        url = request.url.strip()
        
        # Check if we have a scraper for this URL
        scraper = get_scraper_for_url(url)
        if not scraper:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"URL not supported. Supported sources: New Yorker, New York Times, Atlantic, 公众号, 小宇宙"
            )
        
        # Check if article already exists
        existing = db.query(Article).filter(Article.original_url == url).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Article with this URL already exists"
            )
        
        logger.info(f"Queuing article import from URL: {url} (source: {scraper.get_source_name()})")
        
        # Path to the scraping script
        script_path = BASE_DIR / "scripts" / "extract_articles_by_date.py"
        
        if not script_path.exists():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Scraping script not found"
            )
        
        # Prepare environment variables
        env = os.environ.copy()
        if GEMINI_API_KEY:
            env["GEMINI_API_KEY"] = GEMINI_API_KEY
        
        # For Xiaoyuzhou, increase timeout to 30 minutes (audio download + transcription + summary generation can take time)
        timeout_seconds = 1800 if scraper.get_source_slug() == 'xiaoyuzhou' else 600
        
        # Ensure worker is running
        _ensure_worker_running()
        
        # Create a future to wait for the result
        future = asyncio.Future()
        
        # Add task to queue
        queue_size = _import_queue.qsize()
        if queue_size > 0:
            logger.info(f"Article import queued (position in queue: {queue_size + 1})")
        
        await _import_queue.put((url, scraper, script_path, timeout_seconds, env, db, future))
        
        # Wait for the task to complete
        # Note: We don't add asyncio.wait_for here because:
        # 1. The subprocess already has its own timeout (timeout_seconds)
        # 2. Adding another timeout could cause premature cancellation
        # 3. The frontend AbortController handles client-side timeout
        try:
            result = await future
            # Result already contains the correct format from _process_article_import_task
            if "article" in result:
                return {
                    "message": result.get("message", "Article added successfully"),
                    "article": result.get("article")
                }
            else:
                return {
                    "message": result.get("message", "Article processed"),
                    "import_count": result.get("import_count", 0)
                }
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Error waiting for import task: {error_msg}", exc_info=True)
            
            # Check if it's a timeout error
            if "timed out" in error_msg.lower():
                try:
                    scraper_check = get_scraper_for_url(url)
                    timeout_minutes = 30 if scraper_check and scraper_check.get_source_slug() == 'xiaoyuzhou' else 10
                except:
                    timeout_minutes = 30
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Scraping timed out after {timeout_minutes} minutes. For Xiaoyuzhou episodes, this may take longer due to audio download and transcription."
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Error adding article: {error_msg}"
                )
        
    except HTTPException:
        raise
    except subprocess.TimeoutExpired as e:
        # Get scraper again in case it's not in scope
        try:
            scraper_check = get_scraper_for_url(url)
            timeout_minutes = 30 if scraper_check and scraper_check.get_source_slug() == 'xiaoyuzhou' else 10
        except:
            timeout_minutes = 30
        logger.error(f"Scraping script timed out after {timeout_minutes} minutes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Scraping timed out after {timeout_minutes} minutes. For Xiaoyuzhou episodes, this may take longer due to audio download and transcription."
        )
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"Error adding article from URL: {str(e)}", exc_info=True)
        logger.error(f"Full traceback: {error_trace}")
        # Ensure we return JSON error response, not HTML
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error adding article: {str(e)}"
        )


class AskAIRequest(BaseModel):
    question: str


@router.post("/{article_id}/ask-ai")
async def ask_ai_about_article(
    article_id: str,
    request: AskAIRequest,
    db: Session = Depends(get_db)
):
    """
    Ask AI a question about an article using Gemini-3-flash-preview.
    
    - **article_id**: Article ID
    - **question**: User's question about the article
    """
    try:
        if not GEMINI_AVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Gemini API not available. Please install google-generativeai."
            )
        
        api_key = GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GEMINI_API_KEY not configured"
            )
        
        # Get article
        article = db.query(Article).filter(Article.id == article_id).first()
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article not found"
            )
        
        # Get article HTML content
        en_path = Path(article.html_file_en)
        if en_path.parts[0] == 'en':
            filename = en_path.name
            file_path = HTML_DIR_EN / filename
        else:
            file_path = HTML_DIR_EN / en_path.name
        
        if not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article HTML file not found"
            )
        
        # Read HTML content
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Convert HTML to plain text
        soup = BeautifulSoup(html_content, 'html.parser')
        # Remove script and style elements
        for script in soup(["script", "style"]):
            script.decompose()
        # Get text
        text_content = soup.get_text(separator='\n', strip=True)
        
        # Limit text length to avoid token limits (keep first 50000 characters)
        if len(text_content) > 50000:
            text_content = text_content[:50000] + "\n\n[内容已截断...]"
        
        # Configure Gemini
        genai.configure(api_key=api_key)
        
        # Use gemini-3-flash-preview model
        try:
            model = genai.GenerativeModel("models/gemini-3-flash-preview")
        except Exception as e:
            logger.warning(f"Could not use gemini-3-flash-preview: {e}")
            # Fallback to other models
            try:
                model = genai.GenerativeModel("models/gemini-2.5-flash")
            except:
                model = genai.GenerativeModel("gemini-pro")
        
        # Build prompt
        prompt = f"""请基于以下文章内容回答用户的问题。请用中文回答。

文章标题：{article.title}
文章作者：{article.author}
文章分类：{article.category}

文章内容：
{text_content}

用户问题：{request.question}

请基于文章内容提供准确、详细的回答。如果文章内容中没有相关信息，请明确说明。"""
        
        # Generate response
        response = model.generate_content(prompt)
        
        answer = response.text if hasattr(response, 'text') else str(response)
        
        return {
            "answer": answer,
            "article_title": article.title
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error asking AI about article: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error asking AI: {str(e)}"
        )


@router.post("/import")
async def import_articles_manually():
    """
    Manually trigger import of articles from HTML files.
    
    This endpoint scans the HTML directory and imports any articles that are not yet in the database.
    Useful for importing manually added articles or recovering from interrupted imports.
    """
    try:
        logger.info("Manual import triggered via API")
        import_count = await asyncio.to_thread(import_articles_from_directory, HTML_DIR_EN)
        logger.info(f"Manual import completed: {import_count} articles processed")
        return {
            "message": "Import completed successfully",
            "articles_processed": import_count
        }
    except Exception as e:
        logger.error(f"Error in manual import: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error importing articles: {str(e)}"
        )

