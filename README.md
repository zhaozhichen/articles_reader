# Articles Reader

A local web application for reading articles from Aeon, Nautilus, and other sources with Chinese translation support. Run it on your local machine (e.g., MacBook) and access it via `http://localhost:8000`.

## 🚀 Quick Start (TL;DR)

```bash
# 1. Install dependencies
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# 3. Start the application
python -m app.main

# 4. Open browser
# Visit http://localhost:8000
```

See [Quick Start](#quick-start) section below for detailed instructions.

## Features

- 📰 Article scraping from Aeon, Nautilus, and other sources
- 🌐 Chinese/English language toggle with automatic translation
- 🔍 Filter articles by category, author, date, and source
- 📱 Responsive card-based layout
- ⏰ Optional automatic daily updates (disabled by default)
- 🎯 Local-first: runs entirely on your machine, no external web app required

## Architecture

- **Backend**: FastAPI + Python 3.12
- **Database**: SQLite with SQLAlchemy ORM
- **Frontend**: Pure HTML/CSS/JavaScript (single-page application)
- **Translation**: Google Gemini API

## Project Structure

```
articles_public/
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
│       ├── importer.py    # Article import service
│       └── scrapers/      # Article scrapers
│           └── ...
├── static/                 # Frontend files
│   └── index.html         # Main web page
├── scripts/               # Utility scripts
│   └── extract_articles_by_date.py  # Article scraper
├── data/                   # Data directory
│   ├── articles.db        # SQLite database (created automatically)
│   ├── html/              # Article HTML files
│   │   ├── en/            # English articles
│   │   └── zh/            # Chinese translations
│   └── logs/              # Application logs
├── .env.example           # Environment variables template
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Quick Start

### 1. Prerequisites

- Python 3.12 or higher
- pip (Python package manager)

### 2. Install Dependencies

```bash
# Create a virtual environment (recommended)
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate
# On Windows:
# venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
# Copy the example environment file
cp .env.example .env

# Edit .env and add your Gemini API key
# You can get a free API key from: https://makersuite.google.com/app/apikey
```

Edit `.env` file:

```bash
# Required: Gemini API Key for translation
GEMINI_API_KEY=your-actual-api-key-here

# Optional: Enable scheduled scraping (default: false)
# Set to 'true' to enable automatic daily scraping at 7 PM and 11 PM Eastern Time
ENABLE_SCHEDULED_SCRAPING=false

# Optional: Server configuration (defaults shown)
# HOST=127.0.0.1
# PORT=8000
```

**Important**: 
- The `.env` file is in `.gitignore` and will not be committed to the repository
- Keep your API key secure and never share it publicly
- Scheduled scraping is **disabled by default** - set `ENABLE_SCHEDULED_SCRAPING=true` to enable automatic daily scraping

### 4. Run the Application

**Step 1**: Make sure you're in the project directory:

```bash
cd /path/to/articles_public
```

**Step 2**: Activate the virtual environment (if not already activated):

```bash
# On macOS/Linux:
source venv/bin/activate

# On Windows:
# venv\Scripts\activate
```

**Step 3**: Start the application:

```bash
# Method 1: Using Python module (recommended)
python -m app.main
```

Or using uvicorn directly:

```bash
# Method 2: Using uvicorn with auto-reload (for development)
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Expected output** when the application starts successfully:

```
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Starting Articles backend server...
INFO:     Database tables created/verified
INFO:     Scheduled scraping is DISABLED. Set ENABLE_SCHEDULED_SCRAPING=true in .env to enable.
INFO:     Scheduler started
```

**Note**: If you see "Scheduled scraping is DISABLED", that's normal - scheduled scraping is off by default. The application will still work for manual scraping and viewing articles.

**To stop the application**: Press `CTRL+C` in the terminal.

### 5. Access the Web App

Once the application is running, open your browser and navigate to:

- **Main page**: `http://localhost:8000`
- **API documentation**: `http://localhost:8000/docs`
- **Health check**: `http://localhost:8000/health`

You should see the articles reader interface. If you haven't scraped any articles yet, the page may be empty - you can manually scrape articles using the instructions in the [Usage](#usage) section below.

## Usage

### Manual Article Scraping

To manually scrape articles for a specific date:

```bash
# Scrape articles from Aeon and Nautilus for a specific date
python scripts/extract_articles_by_date.py "2025-01-15" --translate --output-dir ./data/html/en --zh-dir ./data/html/zh

# Scrape a single article by URL
python scripts/extract_articles_by_date.py --url "https://aeon.co/essays/..." --translate --output-dir ./data/html/en --zh-dir ./data/html/zh
```

The script will:
1. Download articles from Aeon and Nautilus published on the specified date
2. Save English versions to `data/html/en/`
3. Translate to Chinese and save to `data/html/zh/` (if `--translate` is used)
4. Create metadata JSON files for each article

### Scheduled Scraping (Optional)

By default, scheduled scraping is **disabled**. To enable automatic daily scraping:

1. Set `ENABLE_SCHEDULED_SCRAPING=true` in your `.env` file
2. Restart the application

When enabled, the scheduler will:
- Run daily scraping at **7:00 PM Eastern Time** (primary)
- Run backup scraping at **11:00 PM Eastern Time** (if primary didn't complete)
- Clean up old audio files at **2:00 AM Eastern Time**

The scheduler scrapes articles from:
- **Aeon**: All articles published on the current date
- **Nautilus**: All articles published on the current date

**Note**: Scheduled scraping requires the application to be running continuously. If you only want to scrape articles manually, leave `ENABLE_SCHEDULED_SCRAPING=false`.

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GEMINI_API_KEY` | Yes | - | Gemini API key for translation. Get it from [Google AI Studio](https://makersuite.google.com/app/apikey) |
| `ENABLE_SCHEDULED_SCRAPING` | No | `false` | Set to `true` to enable automatic daily scraping |
| `HOST` | No | `127.0.0.1` | Server host (use `127.0.0.1` for localhost) |
| `PORT` | No | `8000` | Server port |
| `DATABASE_URL` | No | `sqlite:///./data/articles.db` | SQLite database path |

## API Endpoints

- `GET /api/articles` - List articles with filtering and pagination
- `GET /api/articles/{id}` - Get article details
- `GET /api/articles/{id}/html?lang={en|zh}` - Get article HTML content
- `GET /api/articles/filters/options` - Get available filter options
- `GET /health` - Health check

See `http://localhost:8000/docs` for interactive API documentation.

## Data Storage

- **Database**: `data/articles.db` (SQLite database)
- **English articles**: `data/html/en/` (HTML files)
- **Chinese translations**: `data/html/zh/` (HTML files)
- **Metadata**: JSON files alongside HTML files
- **Logs**: `data/logs/articles.log`

## Security Notes

⚠️ **Important for Public Repositories**:

1. **Never commit `.env` file** - It's already in `.gitignore`
2. **Never commit API keys** - Always use environment variables
3. **Review all files** before committing to ensure no secrets are hardcoded
4. **Use `.env.example`** as a template for others

## Troubleshooting

### Application won't start

- Check that Python 3.12+ is installed: `python3 --version`
- Ensure virtual environment is activated
- Verify all dependencies are installed: `pip install -r requirements.txt`
- Check that `.env` file exists and contains `GEMINI_API_KEY`

### Translation not working

- Verify `GEMINI_API_KEY` is set correctly in `.env`
- Check API key is valid at [Google AI Studio](https://makersuite.google.com/app/apikey)
- Check logs in `data/logs/articles.log` for error messages

### Scheduled scraping not running

- Verify `ENABLE_SCHEDULED_SCRAPING=true` in `.env`
- Check that the application is running continuously
- Review logs in `data/logs/articles.log` for scheduler messages
- Ensure your system timezone is correct (scheduler uses Eastern Time)

### Port already in use

- Change the port in `.env`: `PORT=8001`
- Or stop the process using port 8000

## Development

### Running in Development Mode

```bash
# With auto-reload on code changes
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### Project Status

This is a public version of a private articles reader. Key differences:
- Scheduled scraping is **disabled by default** (requires explicit opt-in)
- All sensitive information is moved to environment variables
- Configured for local development (localhost by default)
- No dependencies on external web services

## License

[Add your license here]

## Contributing

[Add contribution guidelines if applicable]