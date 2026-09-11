#!/usr/bin/env python3
"""Explicit cache cleanup. Run only after receiving apps finish reading copies."""
import argparse
import os
from pathlib import Path
from drag_transfer import cleanup_cache

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--older-than-days', type=float, required=True)
parser.add_argument('--cache', type=Path, default=Path(os.environ.get('HERDR_DRAG_CACHE', str(Path.home() / '.cache/herdr-yazi-drag'))))
args = parser.parse_args()
for removed in cleanup_cache(args.cache, args.older_than_days * 86400):
    print(removed)
