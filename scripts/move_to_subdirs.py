#!/usr/bin/env python3
"""
Move existing HTML files to /en and /zh subdirectories.

This script:
1. Moves non-zh_ files to /en subdirectory
2. Moves zh_ files to /zh subdirectory (removing zh_ prefix)
3. Keeps the same filename in both directories
"""
import sys
from pathlib import Path
import shutil

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import HTML_DIR, HTML_DIR_EN, HTML_DIR_ZH

def move_files_to_subdirs(source_dir=None):
    """Move files from source directory to en/ and zh/ subdirectories."""
    if source_dir is None:
        source_dir = HTML_DIR
    
    source_dir = Path(source_dir)
    en_dir = HTML_DIR_EN
    zh_dir = HTML_DIR_ZH
    
    # Ensure directories exist
    en_dir.mkdir(parents=True, exist_ok=True)
    zh_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all HTML files recursively
    html_files = list(source_dir.rglob("*.html"))
    
    if not html_files:
        print(f"No HTML files found in {source_dir}", file=sys.stderr)
        return
    
    print(f"Found {len(html_files)} HTML files", file=sys.stderr)
    
    moved_en = 0
    moved_zh = 0
    skipped = 0
    
    for html_file in html_files:
        # Skip files already in en/ or zh/ directories
        if 'en/' in str(html_file) or 'zh/' in str(html_file):
            skipped += 1
            continue
        
        filename = html_file.name
        
        if filename.startswith('zh_'):
            # This is a Chinese file
            # Remove zh_ prefix and move to zh/ directory
            new_filename = filename[3:]  # Remove 'zh_' prefix
            dest_path = zh_dir / new_filename
            
            # Check if destination already exists
            if dest_path.exists():
                print(f"  Skipping {filename} (destination exists: {dest_path.name})", file=sys.stderr)
                skipped += 1
                continue
            
            try:
                shutil.move(str(html_file), str(dest_path))
                print(f"  Moved {filename} -> zh/{new_filename}", file=sys.stderr)
                moved_zh += 1
            except Exception as e:
                print(f"  Error moving {filename}: {e}", file=sys.stderr)
        else:
            # This is an English file
            dest_path = en_dir / filename
            
            # Check if destination already exists
            if dest_path.exists():
                print(f"  Skipping {filename} (destination exists: {dest_path.name})", file=sys.stderr)
                skipped += 1
                continue
            
            try:
                shutil.move(str(html_file), str(dest_path))
                print(f"  Moved {filename} -> en/{filename}", file=sys.stderr)
                moved_en += 1
            except Exception as e:
                print(f"  Error moving {filename}: {e}", file=sys.stderr)
    
    print(f"\n✅ Moved {moved_en} English files to en/ and {moved_zh} Chinese files to zh/", file=sys.stderr)
    if skipped > 0:
        print(f"   Skipped {skipped} files (already in subdirectories or conflicts)", file=sys.stderr)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Move HTML files to /en and /zh subdirectories'
    )
    parser.add_argument(
        '--source-dir',
        type=str,
        default=None,
        help=f'Source directory (default: {HTML_DIR})'
    )
    
    args = parser.parse_args()
    
    source_dir = Path(args.source_dir) if args.source_dir else HTML_DIR
    
    if not source_dir.exists():
        print(f"Error: Source directory {source_dir} does not exist", file=sys.stderr)
        sys.exit(1)
    
    print(f"Moving files from {source_dir} to en/ and zh/ subdirectories...", file=sys.stderr)
    move_files_to_subdirs(source_dir)
    sys.exit(0)

if __name__ == '__main__':
    main()

