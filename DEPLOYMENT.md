# Deployment Guide

## Quick Start

### 1. Build Docker Image

```bash
cd /home/tensor/projects/articles
docker build -t articles:latest .
```

### 2. Generate Ktizo Configuration

```bash
cd /home/tensor/projects/ktizo
docker run --rm -v "$(pwd):/workspace" -w /workspace node:18-alpine node scripts/generate-config.js
```

### 3. Update docker-compose.yml

Add the following service to `/home/tensor/projects/ktizo/docker-compose.yml`:

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
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
```

### 4. Deploy

```bash
cd /home/tensor/projects/ktizo

# Restart Caddy to apply new routing
docker compose restart caddy

# Rebuild and restart launcher to show new app
docker compose build launcher
docker compose up -d launcher

# Start articles service
docker compose up -d articles
```

### 5. Verify

- Check container status: `docker compose ps articles`
- Check logs: `docker compose logs articles`
- Access web app: `http://articles.ktizo.io` (or your configured subdomain)

## Manual Operations

### Import Existing Articles

If you have existing HTML files and JSON metadata:

```bash
docker compose exec articles python scripts/import_articles.py --directory /app/data/html
```

### Manual Scraping

To manually scrape articles for a specific date:

```bash
docker compose exec articles python scripts/extract_articles_by_date.py "2025-01-15" --translate --output-dir /app/data/html
```

### View Logs

```bash
docker compose logs -f articles
```

## Troubleshooting

### Container won't start

1. Check logs: `docker compose logs articles`
2. Verify environment variables are set correctly
3. Ensure data directory has proper permissions

### Articles not showing

1. Check if database exists: `ls -la /home/tensor/projects/articles/data/articles.db`
2. Import articles manually if needed
3. Check API: `curl http://articles.ktizo.io/api/articles`

### Scheduler not running

1. Check logs for scheduler messages
2. Verify timezone settings
3. Manually trigger: Check scheduler logs at 2:00 AM

### Translation not working

1. Verify `GEMINI_API_KEY` is set in environment
2. Check logs for translation errors
3. Test API key: `echo $GEMINI_API_KEY`

