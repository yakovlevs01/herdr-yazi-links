#!/usr/bin/env python3
"""Print file links to Ctrl-click in Herdr. No agent is needed."""
from pathlib import Path
import sys

path = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / 'README.md'
if not path.is_file():
    raise SystemExit('File not found: ' + str(path))
print('Ctrl-click the next line: stock Herdr + plugin should open Yazi.')
print('\x1b]8;;' + path.as_uri() + '\x1b\\Open this file in Yazi\x1b]8;;\x1b\\')
print('\nThese plain paths additionally require the Herdr patch:')
print(path)
try:
    print(path.relative_to(Path.cwd()))
except ValueError:
    pass
print('\nA non-existent path must not open anything:')
print('/nonexistent-herdr-yazi-demo/file.txt')
