#!/usr/bin/env python3
"""Standalone script to clean up old audio files."""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.audio_cleanup import cleanup_old_audio_files
from app.utils.logger import setup_script_logger

# Setup logger
logger = setup_script_logger("cleanup_audio")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Clean up old audio files")
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=5,
        help="Time to live in days (default: 5)"
    )
    
    args = parser.parse_args()
    
    logger.info(f"Starting audio cleanup with TTL: {args.ttl_days} days")
    
    result = cleanup_old_audio_files(ttl_days=args.ttl_days)
    
    print(f"\nCleanup Summary:")
    print(f"  Total files checked: {result['total_files']}")
    print(f"  Files deleted: {result['deleted_files']}")
    print(f"  Space freed: {result['deleted_size_mb']} MB")
    print(f"  Files remaining: {result['remaining_files']}")
    
    sys.exit(0)
