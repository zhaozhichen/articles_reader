# Local Deployment Guide

This application is designed to run locally on your machine. For local deployment instructions, please refer to the [README.md](README.md) Quick Start section.

## Quick Start

See the main [README.md](README.md) for detailed local deployment instructions.

The application runs on `http://localhost:8000` by default.

## Manual Operations

### Import Existing Articles

If you have existing HTML files and JSON metadata:

```bash
python scripts/import_articles.py --directory ./data/html
```

### Manual Scraping

To manually scrape articles for a specific date:

```bash
python scripts/extract_articles_by_date.py "2025-01-15" --translate --output-dir ./data/html/en --zh-dir ./data/html/zh
```

### View Logs

```bash
# Logs are stored in data/logs/articles.log
tail -f data/logs/articles.log
```

## Troubleshooting

### Application won't start

1. Check logs in `data/logs/articles.log`
2. Verify environment variables are set correctly in `.env`
3. Ensure data directory has proper permissions

### Articles not showing

1. Check if database exists: `ls -la ./data/articles.db`
2. Import articles manually if needed
3. Check API: `curl http://localhost:8000/api/articles`

### Scheduler not running

1. Check logs for scheduler messages
2. Verify `ENABLE_SCHEDULED_SCRAPING=true` in `.env`
3. Ensure the application is running continuously

### Translation not working

1. Verify `GEMINI_API_KEY` is set in `.env`
2. Check logs for translation errors
3. Test API key at [Google AI Studio](https://makersuite.google.com/app/apikey)
