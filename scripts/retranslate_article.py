#!/usr/bin/env python3
"""Script to retranslate a specific article to fix layout issues."""
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.translator import translate_html_with_gemini_retry
from app.config import HTML_DIR_EN, HTML_DIR_ZH

def retranslate_article(filename: str):
    """Retranslate an article by filename."""
    en_file = HTML_DIR_EN / filename
    zh_file = HTML_DIR_ZH / filename
    
    if not en_file.exists():
        print(f"Error: English file not found: {en_file}", file=sys.stderr)
        return 1
    
    print(f"Reading English file: {en_file}", file=sys.stderr)
    with open(en_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    print(f"Translating article (this may take a few minutes)...", file=sys.stderr)
    translated_html = translate_html_with_gemini_retry(html_content, max_retries=2)
    
    if not translated_html:
        print(f"Error: Translation failed", file=sys.stderr)
        return 1
    
    # Ensure zh directory exists
    HTML_DIR_ZH.mkdir(parents=True, exist_ok=True)
    
    # Backup old file if exists
    if zh_file.exists():
        backup_file = zh_file.with_suffix('.html.backup')
        print(f"Backing up old translation to: {backup_file}", file=sys.stderr)
        with open(zh_file, 'r', encoding='utf-8') as f:
            with open(backup_file, 'w', encoding='utf-8') as bf:
                bf.write(f.read())
    
    # Save new translation
    print(f"Saving new translation to: {zh_file}", file=sys.stderr)
    with open(zh_file, 'w', encoding='utf-8') as f:
        f.write(translated_html)
    
    print(f"Successfully retranslated article!", file=sys.stderr)
    return 0

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <filename>", file=sys.stderr)
        print(f"Example: {sys.argv[0]} 2025-06-30_interactive_https_www.nytimes.com_by_steven-strogatz_Bowling_for_Nobels.html", file=sys.stderr)
        sys.exit(1)
    
    filename = sys.argv[1]
    sys.exit(retranslate_article(filename))


