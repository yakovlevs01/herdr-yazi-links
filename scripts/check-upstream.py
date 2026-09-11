#!/usr/bin/env python3
"""Build/test a Herdr revision without changing the installed patched executable."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True, help='Full 40-character upstream Git commit')
    parser.add_argument('--rust', help='Candidate Rust toolchain, otherwise use the current pin')
    parser.add_argument('--zig-version', help='Candidate Zig version; set ZIG to that executable')
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-fA-F]{40}', args.revision):
        parser.error('--revision must be a full Git commit hash, not a moving branch')
    config = tomllib.loads((ROOT / 'patches/upstream.toml').read_text())
    config['revision'] = args.revision.lower()
    if args.rust:
        config['rust'] = args.rust
    if args.zig_version:
        config['zig'] = args.zig_version
    candidate = ROOT / '.build/candidates' / config['revision']
    candidate.mkdir(parents=True, exist_ok=True)
    metadata = candidate / 'upstream.toml'
    metadata.write_text('\n'.join(f'{key} = {json.dumps(value)}' for key, value in config.items()) + '\n')
    env = dict(os.environ, HERDR_YAZI_BUILD_DIR=str(candidate), HERDR_YAZI_UPSTREAM_FILE=str(metadata))
    subprocess.run(['bash', str(ROOT / 'build.sh')], env=env, check=True)
    print('PASS candidate: ' + str(candidate / 'bin/herdr'))
    print('Installed .build/bin/herdr and patches/upstream.toml were not changed.')
    print('To adopt it, review/update the committed pin and patch, then run build.sh.')
    print('No running Herdr server was restarted.')


if __name__ == '__main__':
    main()
