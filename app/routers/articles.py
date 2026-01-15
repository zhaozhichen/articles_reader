"""Article API endpoints."""
import logging
import asyncio
import subprocess
import sys
import os
import uuid
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

# Task status storage for async import tasks
_import_tasks: Dict[str, Dict[str, Any]] = {}


async def _process_article_import_task(
    url: str,
    scraper,
    script_path: Path,
    timeout_seconds: int,
    env: Dict[str, Any],
    db: Session,
    task_id: str
) -> Dict[str, Any]:
    """Process a single article import task."""
    try:
        # Update task status to processing
        if task_id in _import_tasks:
            _import_tasks[task_id]["status"] = "processing"
            _import_tasks[task_id]["message"] = "正在处理文章..."
        logger.info(f"Running command: python {script_path} --url {url}")
        
        # Update task status
        if task_id in _import_tasks:
            _import_tasks[task_id]["status"] = "processing"
            _import_tasks[task_id]["message"] = "正在抓取文章内容..."
        
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
            if task_id in _import_tasks:
                _import_tasks[task_id]["status"] = "error"
                _import_tasks[task_id]["error"] = f"Failed to scrape article: {error_msg}"
            raise Exception(f"Failed to scrape article: {error_msg}")
        
        logger.info(f"Scraping completed successfully")
        logger.info(f"Script output: {result.stdout}")
        
        # Import articles into database
        logger.info("Importing article into database...")
        if task_id in _import_tasks:
            _import_tasks[task_id]["status"] = "processing"
            _import_tasks[task_id]["message"] = "正在导入到数据库..."
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
            
            result = {
                "success": True,
                "message": "Article added successfully",
                "article": ArticleResponse.model_validate(new_article)
            }
            if task_id in _import_tasks:
                _import_tasks[task_id]["status"] = "completed"
                _import_tasks[task_id]["result"] = result
            return result
        else:
            result = {
                "success": True,
                "message": "Article processed but not found in database",
                "import_count": import_count
            }
            if task_id in _import_tasks:
                _import_tasks[task_id]["status"] = "completed"
                _import_tasks[task_id]["result"] = result
            return result
            
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
        if task_id in _import_tasks:
            _import_tasks[task_id]["status"] = "error"
            _import_tasks[task_id]["error"] = str(e)
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
            
            url, scraper, script_path, timeout_seconds, env, db, future, task_id = task
            
            logger.info(f"Processing queued import task for URL: {url} (queue size: {_import_queue.qsize()})")
            
            try:
                result = await _process_article_import_task(
                    url, scraper, script_path, timeout_seconds, env, db, task_id
                )
                if future:
                    future.set_result(result)
            except Exception as e:
                if future:
                    future.set_exception(e)
            finally:
                _import_queue.task_done()
                
        except Exception as e:
            logger.error(f"Error in import worker: {str(e)}", exc_info=True)
            if 'future' in locals() and future:
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
    sort: str = Query("created_desc", description="Sort order: created_desc, date_desc, created_asc, date_asc"),
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
    - **sort**: Sort order (created_desc=按添加时间从新到旧, date_desc=按文章时间从新到旧, created_asc=按添加时间从旧到新, date_asc=按文章时间从旧到新)
    """
    try:
        # Build query
        query = db.query(Article)
        
        logger.info(f"Received request: search='{search}', lang='{lang}', page={page}, limit={limit}, sort='{sort}'")
        
        # Apply search filter first (search in titles and HTML content)
        if search and search.strip():
            search_term = f"%{search.strip()}%"
            search_lower = search.strip().lower()
            logger.info(f"Searching for '{search.strip()}' in all articles (titles and HTML content)")
            
            # First, search in titles (search in both English and Chinese titles, regardless of lang filter)
            # This ensures we find all articles that match in titles
            title_query = db.query(Article).filter(
                or_(
                    Article.title.ilike(search_term),
                    Article.title_zh.ilike(search_term)
                )
            )
            logger.info(f"Searching in both title and title_zh for '{search.strip()}'")
            
            # Get articles matching title search
            title_matched_ids = {article.id for article in title_query.all()}
            logger.info(f"Found {len(title_matched_ids)} articles matching title search")
            
            # Now search in HTML content
            # Get all articles to search (we'll apply other filters after search)
            # This ensures we search all articles as requested
            all_articles = db.query(Article).all()
            html_matched_ids = set()
            
            # Search HTML content
            def search_html_content(article: Article) -> bool:
                """Search for keyword in article HTML content."""
                try:
                    # Try to read HTML files
                    html_files = []
                    
                    # Try English HTML
                    if article.html_file_en:
                        en_path = Path(article.html_file_en)
                        if en_path.parts[0] == 'en':
                            filename = en_path.name
                            file_path = HTML_DIR_EN / filename
                        else:
                            file_path = HTML_DIR_EN / en_path.name
                        if file_path.exists():
                            html_files.append(file_path)
                    
                    # Try Chinese HTML
                    if article.html_file_zh:
                        zh_path = Path(article.html_file_zh)
                        if zh_path.parts[0] == 'zh':
                            filename = zh_path.name
                            file_path = HTML_DIR_ZH / filename
                        else:
                            file_path = HTML_DIR_ZH / zh_path.name
                        if file_path.exists():
                            html_files.append(file_path)
                    
                    # Search in HTML files
                    for html_file in html_files:
                        try:
                            with open(html_file, 'r', encoding='utf-8') as f:
                                html_content = f.read().lower()
                                if search_lower in html_content:
                                    return True
                        except Exception as e:
                            logger.warning(f"Error reading HTML file {html_file}: {e}")
                            continue
                    
                    return False
                except Exception as e:
                    logger.warning(f"Error searching HTML for article {article.id}: {e}")
                    return False
            
            # Search HTML content for all articles (in batches to avoid blocking)
            from concurrent.futures import ThreadPoolExecutor
            
            # Use thread pool to search HTML files in parallel
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = []
                for article in all_articles:
                    if article.id not in title_matched_ids:  # Skip if already matched by title
                        future = executor.submit(search_html_content, article)
                        futures.append((article.id, future))
                
                # Collect results
                for article_id, future in futures:
                    try:
                        if future.result(timeout=5):  # 5 second timeout per file
                            html_matched_ids.add(article_id)
                    except Exception as e:
                        logger.warning(f"Error searching HTML for article {article_id}: {e}")
            
            logger.info(f"Found {len(html_matched_ids)} articles matching HTML content search")
            
            # Combine title and HTML matches
            all_matched_ids = title_matched_ids | html_matched_ids
            logger.info(f"Total {len(all_matched_ids)} articles matching search (title + HTML)")
            
            # Filter query to only include matched articles
            if all_matched_ids:
                query = query.filter(Article.id.in_(all_matched_ids))
            else:
                # No matches found, return empty result
                query = query.filter(Article.id == None)  # This will return no results
            
            # Note: We do NOT apply language filter when searching, because:
            # 1. User wants to search all articles regardless of language
            # 2. HTML content may match even if article doesn't have title in preferred language
            # Language filter is only applied when NOT searching (see elif lang block below)
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
        if sort == "created_desc":
            query = query.order_by(Article.created_at.desc())
        elif sort == "created_asc":
            query = query.order_by(Article.created_at.asc())
        elif sort == "date_asc":
            query = query.order_by(Article.date.asc())
        elif sort == "date_desc":
            query = query.order_by(Article.date.desc())
        else:  # Unknown sort, default to created_desc
            logger.warning(f"Unknown sort parameter: '{sort}', defaulting to created_desc")
            query = query.order_by(Article.created_at.desc())
        
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
        
        # Replace relative image paths with API URLs
        # Images are stored as relative paths like "images/img_xxx.jpg"
        # We need to convert them to API URLs like "/api/articles/{article_id}/images/images/img_xxx.jpg"
        import re
        def replace_image_path(match):
            img_path = match.group(1)
            # Skip if already an absolute URL (http/https)
            if img_path.startswith('http://') or img_path.startswith('https://'):
                return match.group(0)
            # Convert relative path to API URL
            api_url = f"/api/articles/{article_id}/images/{img_path}"
            return f'src="{api_url}"'
        
        # Replace src="images/..." with API URLs
        html_content = re.sub(r'src="([^"]*images/[^"]+)"', replace_image_path, html_content)
        # Also handle srcset attributes
        def replace_srcset(match):
            srcset_content = match.group(1)
            # Replace each URL in srcset
            def replace_srcset_url(url_match):
                url = url_match.group(1)
                if url.startswith('http://') or url.startswith('https://'):
                    return url_match.group(0)
                api_url = f"/api/articles/{article_id}/images/{url}"
                return url_match.group(0).replace(url, api_url)
            srcset_content = re.sub(r'([^\s,]+)', replace_srcset_url, srcset_content)
            return f'srcset="{srcset_content}"'
        html_content = re.sub(r'srcset="([^"]+)"', replace_srcset, html_content)
        
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

@router.get("/{article_id}/images/{image_path:path}")
async def get_article_image(
    article_id: str,
    image_path: str,
    db: Session = Depends(get_db)
):
    """
    Get an image file for an article.
    
    - **article_id**: Article ID
    - **image_path**: Path to the image file (relative to article HTML file, e.g., "images/img_xxx.jpg")
    """
    try:
        article = db.query(Article).filter(Article.id == article_id).first()
        
        if not article:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Article not found"
            )
        
        # Determine which directory to look in based on article's HTML file
        # Images are stored in the same directory as the HTML file (in an "images" subdirectory)
        if article.html_file_en:
            en_path = Path(article.html_file_en)
            if en_path.parts[0] == 'en':
                filename = en_path.name
                html_dir = HTML_DIR_EN
            else:
                html_dir = HTML_DIR_EN
        else:
            html_dir = HTML_DIR_EN
        
        # Construct image file path
        # image_path is like "images/img_xxx.jpg"
        image_file = html_dir / image_path
        
        # Security: ensure the image path is within the HTML directory
        try:
            image_file.resolve().relative_to(html_dir.resolve())
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid image path"
            )
        
        if not image_file.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Image not found: {image_path}"
            )
        
        # Determine content type from file extension
        from fastapi.responses import FileResponse
        media_type = "image/jpeg"  # default
        ext = image_file.suffix.lower()
        if ext in ['.png']:
            media_type = "image/png"
        elif ext in ['.gif']:
            media_type = "image/gif"
        elif ext in ['.webp']:
            media_type = "image/webp"
        elif ext in ['.svg']:
            media_type = "image/svg+xml"
        
        return FileResponse(
            path=str(image_file),
            media_type=media_type
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving article image: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error serving article image: {str(e)}"
        )

@router.get("/filters/options", response_model=FilterOptionsResponse)
async def get_filter_options(
    category: Optional[str] = Query(None, description="Filter by category (exclude from options)"),
    author: Optional[str] = Query(None, description="Filter by author (exclude from options)"),
    source: Optional[str] = Query(None, description="Filter by source (exclude from options)"),
    date_from: Optional[str] = Query(None, description="Filter by date from (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter by date to (YYYY-MM-DD)"),
    db: Session = Depends(get_db)
):
    """
    Get available filter options (categories, authors, sources, date range).
    When filters are provided, returns only options available after applying those filters.
    This allows cascading filters where selecting one filter updates available options in others.
    """
    try:
        logger.info(f"Getting filter options with filters: category={category}, author={author}, source={source}, date_from={date_from}, date_to={date_to}")
        
        # Start with base query
        query = db.query(Article)
        total_before = query.count()
        logger.info(f"Total articles before filtering: {total_before}")
        
        # Apply filters to narrow down the articles we consider
        # Note: We exclude the field we're querying from the filter
        # (e.g., when getting categories, we don't filter by category)
        
        # Apply author filter (when getting categories/sources)
        if author:
            query = query.filter(Article.author == author)
            logger.info(f"Applied author filter: {author}")
        
        # Apply source filter (when getting categories/authors)
        if source:
            # Check what source values exist in database
            all_sources = db.query(Article.source).distinct().limit(10).all()
            logger.info(f"Sample source values in DB: {[s[0] for s in all_sources]}")
            logger.info(f"Filtering by source: {repr(source)} (type: {type(source)})")
            query = query.filter(Article.source == source)
            count_after_source = query.count()
            logger.info(f"Applied source filter: {source}, articles after filter: {count_after_source}")
        
        # Apply category filter (when getting authors/sources)
        if category:
            query = query.filter(Article.category == category)
            logger.info(f"Applied category filter: {category}")
        
        # Apply date filters
        if date_from:
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                query = query.filter(Article.date >= date_from_obj)
            except ValueError:
                pass  # Invalid date format, ignore
        
        if date_to:
            try:
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                query = query.filter(Article.date <= date_to_obj)
            except ValueError:
                pass  # Invalid date format, ignore
        
        # Get distinct categories from filtered articles
        # Note: When category filter is applied, we still query categories from articles matching other filters
        # This allows showing all available categories after applying other filters
        categories = query.with_entities(Article.category).distinct().all()
        categories_list = [cat[0] for cat in categories if cat[0]]
        logger.info(f"Found {len(categories_list)} categories after filtering (sample: {categories_list[:5]})")
        
        # Get distinct authors from filtered articles
        # Note: When author filter is applied, we still query authors from articles matching other filters
        authors = query.with_entities(Article.author).distinct().all()
        authors_list = [auth[0] for auth in authors if auth[0]]
        logger.info(f"Found {len(authors_list)} authors after filtering (sample: {authors_list[:5]})")
        
        # Get distinct sources from filtered articles
        # Note: When source filter is applied, we still query sources from articles matching other filters
        sources = query.with_entities(Article.source).distinct().all()
        sources_list = [src[0] for src in sources if src[0]]
        logger.info(f"Found {len(sources_list)} sources after filtering")
        
        # Get date range from filtered articles
        min_date = query.with_entities(func.min(Article.date)).scalar()
        max_date = query.with_entities(func.max(Article.date)).scalar()
        
        date_range = {
            "min": min_date.strftime('%Y-%m-%d') if min_date else None,
            "max": max_date.strftime('%Y-%m-%d') if max_date else None
        }
        
        # Log final results
        logger.info(f"Returning filter options: {len(categories_list)} categories, {len(authors_list)} authors, {len(sources_list)} sources")
        if source:
            logger.info(f"With source filter '{source}', should have fewer options than total")
        
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
    Manually add an article by URL. Returns immediately with a task ID.
    Use /import-status/{task_id} to check the status.
    
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
        
        # Generate task ID
        task_id = str(uuid.uuid4())
        
        # Initialize task status
        _import_tasks[task_id] = {
            "status": "queued",
            "url": url,
            "message": "任务已加入队列，等待处理...",
            "created_at": datetime.now().isoformat()
        }
        
        # Ensure worker is running
        _ensure_worker_running()
        
        # Create a future to wait for the result (for backward compatibility, but we won't wait)
        future = asyncio.Future()
        
        # Add task to queue
        queue_size = _import_queue.qsize()
        if queue_size > 0:
            logger.info(f"Article import queued (position in queue: {queue_size + 1})")
            _import_tasks[task_id]["message"] = f"任务已加入队列（队列位置: {queue_size + 1}）"
        
        await _import_queue.put((url, scraper, script_path, timeout_seconds, env, db, future, task_id))
        
        # Return immediately with task ID
        return {
            "task_id": task_id,
            "message": "任务已创建，正在后台处理中...",
            "status": "queued"
        }
        
    except HTTPException:
        raise
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


@router.get("/import-status/{task_id}")
async def get_import_status(
    task_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the status of an article import task.
    
    - **task_id**: Task ID returned from /add-from-url
    """
    if task_id not in _import_tasks:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    task = _import_tasks[task_id]
    
    # If task is completed, try to get the article
    if task["status"] == "completed" and "result" in task:
        result = task["result"]
        if "article" in result:
            # Refresh article from database
            article_id = result["article"].id
            article = db.query(Article).filter(Article.id == article_id).first()
            if article:
                result["article"] = ArticleResponse.model_validate(article)
    
    return {
        "task_id": task_id,
        "status": task["status"],
        "message": task.get("message", ""),
        "error": task.get("error"),
        "result": task.get("result"),
        "created_at": task.get("created_at")
    }


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

