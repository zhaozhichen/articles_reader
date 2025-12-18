#!/bin/bash
# Convenience script to import manually uploaded HTML articles

cd /home/tensor/projects/ktizo

echo "Importing articles from HTML files..."
docker compose exec articles python -c "
import sys
sys.path.insert(0, '/app')
from pathlib import Path
import re
from datetime import datetime
from bs4 import BeautifulSoup
from app.database import SessionLocal
from app.models import Article

def parse_filename(filename):
    filename = Path(filename).name
    is_zh = filename.startswith('zh_')
    if is_zh:
        base_name = filename[3:]
    else:
        base_name = filename
    base_name = base_name.replace('.html', '')
    parts = base_name.split('_')
    if len(parts) < 4:
        return None
    try:
        date_obj = datetime.strptime(parts[0], '%Y-%m-%d')
    except:
        return None
    category = parts[1]
    author = parts[2] if len(parts) > 3 else 'unknown'
    title = '_'.join(parts[3:]) if len(parts) > 3 else 'untitled'
    return {
        'is_zh': is_zh,
        'date': date_obj,
        'category': category,
        'author': author.replace('_', ' '),
        'title': title.replace('_', ' '),
        'original_filename': filename
    }

def extract_metadata_from_html(html_path):
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        soup = BeautifulSoup(html_content, 'html.parser')
        metadata = {}
        og_url = soup.find('meta', property='og:url')
        if og_url and og_url.get('content'):
            metadata['url'] = og_url.get('content')
        canonical = soup.find('link', rel='canonical')
        if canonical and canonical.get('href'):
            metadata['url'] = canonical.get('href')
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            metadata['title'] = og_title.get('content')
        else:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text().strip()
                title = re.sub(r'\s*\|\s*The New Yorker\s*$', '', title)
                metadata['title'] = title
        author_meta = soup.find('meta', property='article:author')
        if author_meta and author_meta.get('content'):
            metadata['author'] = author_meta.get('content')
        return metadata
    except Exception as e:
        return {}

directory = Path('/app/data/html')
html_files = list(directory.rglob('*.html'))
print(f'Found {len(html_files)} HTML files', file=sys.stderr)

en_files = {}
zh_files = {}

for html_file in html_files:
    parsed = parse_filename(html_file.name)
    if not parsed:
        print(f'  Skipping {html_file.name} (cannot parse)', file=sys.stderr)
        continue
    rel_path = html_file.relative_to(directory)
    key = (parsed['date'], parsed['category'], parsed['author'])
    if parsed['is_zh']:
        zh_files[key] = {'path': str(rel_path), 'parsed': parsed, 'html_metadata': extract_metadata_from_html(html_file)}
    else:
        en_files[key] = {'path': str(rel_path), 'parsed': parsed, 'html_metadata': extract_metadata_from_html(html_file)}

print(f'Found {len(en_files)} English articles and {len(zh_files)} Chinese translations', file=sys.stderr)

db = SessionLocal()
imported_count = 0
updated_count = 0

try:
    for key, en_data in en_files.items():
        parsed = en_data['parsed']
        html_meta = en_data['html_metadata']
        title = html_meta.get('title') or parsed['title']
        author = html_meta.get('author') or parsed['author']
        url = html_meta.get('url') or ''
        zh_data = zh_files.get(key)
        zh_path = zh_data['path'] if zh_data else None
        existing = None
        if url:
            existing = db.query(Article).filter(Article.original_url == url).first()
        if not existing:
            existing = db.query(Article).filter(Article.html_file_en == en_data['path']).first()
        if existing:
            existing.title = title
            existing.title_zh = zh_data['html_metadata'].get('title') if zh_data else None
            existing.date = parsed['date']
            existing.category = parsed['category']
            existing.author = author
            existing.html_file_en = en_data['path']
            existing.html_file_zh = zh_path
            existing.updated_at = datetime.utcnow()
            if url and not existing.original_url:
                existing.original_url = url
            updated_count += 1
            print(f'  Updated: {title[:50]}...', file=sys.stderr)
        else:
            article = Article(
                title=title,
                title_zh=zh_data['html_metadata'].get('title') if zh_data else None,
                date=parsed['date'],
                category=parsed['category'],
                author=author,
                source='New Yorker',
                original_url=url,
                html_file_en=en_data['path'],
                html_file_zh=zh_path
            )
            db.add(article)
            imported_count += 1
            print(f'  Imported: {title[:50]}...', file=sys.stderr)
    db.commit()
    print(f'\n✅ Successfully imported {imported_count} new articles and updated {updated_count} existing articles', file=sys.stderr)
except Exception as e:
    print(f'❌ Error: {e}', file=sys.stderr)
    import traceback
    traceback.print_exc()
    db.rollback()
finally:
    db.close()
"

echo ""
echo "Import complete! Check the web app at http://articles.ktizo.io"

