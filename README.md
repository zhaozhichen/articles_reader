# Articles Reader

A web application for reading NY Times articles with Chinese translation support.

## Features

- 📰 Automatic daily article scraping from The New Yorker
- 🌐 Chinese/English language toggle
- 🔍 Filter articles by category, author, date, and source
- 📱 Responsive card-based layout
- ⏰ Automatic daily updates at 2:00 AM

## Architecture

- **Backend**: FastAPI + Python 3.12
- **Database**: SQLite with SQLAlchemy ORM
- **Frontend**: Pure HTML/CSS/JavaScript (single-page application)
- **Containerization**: Docker
- **Integration**: Ktizo modular web server

## Project Structure

```
articles/
├── app/                    # FastAPI application
│   ├── main.py            # Main application entry
│   ├── database.py        # Database configuration
│   ├── models.py          # SQLAlchemy models
│   ├── schemas.py         # Pydantic schemas
│   ├── config.py          # Configuration
│   ├── routers/           # API routes
│   │   ├── articles.py    # Article endpoints
│   │   └── web.py         # Web endpoints
│   └── services/         # Business logic
│       ├── scheduler.py   # Daily scraping scheduler
│       └── importer.py    # Article import service
├── static/                 # Frontend files
│   └── index.html         # Main web page
├── scripts/               # Utility scripts
│   ├── extract_articles_by_date.py  # Article scraper
│   └── import_articles.py            # Manual import script
├── data/                   # Data directory
│   ├── articles.db        # SQLite database
│   └── html/              # Article HTML files
├── Dockerfile
└── requirements.txt
```

## Setup

### 1. Build Docker Image

```bash
cd /home/tensor/projects/articles
docker build -t articles:latest .
```

### 2. Configure Ktizo

The Ktizo configuration is already created at `/home/tensor/projects/ktizo/apps/articles/app.json`.

Generate Ktizo configuration:

```bash
cd /home/tensor/projects/ktizo
docker run --rm -v "$(pwd):/workspace" -w /workspace node:18-alpine node scripts/generate-config.js
```

### 3. Update docker-compose.yml

Add the articles service to `/home/tensor/projects/ktizo/docker-compose.yml`:

```yaml
services:
  # ... existing services ...
  
  articles:
    image: articles:latest
    container_name: ktizo-articles
    restart: unless-stopped
    volumes:
      - /home/tensor/projects/articles/data:/app/data
    environment:
      - DATABASE_URL=sqlite:///./data/articles.db
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - HOST=0.0.0.0
      - PORT=8000
    networks:
      - ktizo-network
```

### 4. Deploy

```bash
cd /home/tensor/projects/ktizo
docker compose restart caddy
docker compose build launcher && docker compose up -d launcher
docker compose up -d articles
```

## Usage

### Manual Article Scraping

To manually scrape articles for a specific date:

```bash
cd /home/tensor/projects/articles
python scripts/extract_articles_by_date.py "2025-01-15" --translate --output-dir ./data/html
```

### Import Existing Articles

To import existing HTML files and metadata into the database:

```bash
cd /home/tensor/projects/articles
python scripts/import_articles.py --directory ./data/html
```

### Access the Web App

- Main page: `http://articles.ktizo.io` (or your configured subdomain)
- API documentation: `http://articles.ktizo.io/docs`

## Environment Variables

- `DATABASE_URL`: SQLite database path (default: `sqlite:///./data/articles.db`)
- `GEMINI_API_KEY`: Gemini API key for translation (required for Chinese translation)
- `HOST`: Server host (default: `0.0.0.0`)
- `PORT`: Server port (default: `8000`)

## API Endpoints

- `GET /api/articles` - List articles with filtering and pagination
- `GET /api/articles/{id}` - Get article details
- `GET /api/articles/{id}/html?lang={en|zh}` - Get article HTML content
- `GET /api/articles/filters/options` - Get available filter options
- `GET /health` - Health check

## Scheduled Tasks

The application automatically runs article scraping every day at 2:00 AM. The scheduler:
1. Runs the scraping script for today's date
2. Imports new articles into the database
3. Logs all activities

## Notes

- HTML files are stored in `data/html/` directory
- Database file is at `data/articles.db`
- Metadata JSON files are created alongside HTML files
- The scraper creates both English and Chinese versions when translation is enabled

