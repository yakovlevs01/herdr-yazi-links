#!/usr/bin/env python3
"""Pass the original argv to Herdr; inspect only SSH/session setup metadata."""
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def preparation(args, default_session):
    remote = None
    session = default_session
    pending = None
    help_requested = False
    for arg in args:
        if pending:
            if pending == 'remote':
                remote = arg
            else:
                session = arg
            pending = None
        elif arg == '--':
            break
        elif arg in ('--help', '-h', '--version', '-V'):
            help_requested = True
        elif arg == '--remote':
            pending = 'remote'
        elif arg == '--session':
            pending = 'session'
        elif arg.startswith('--remote='):
            remote = arg.partition('=')[2]
        elif arg.startswith('--session='):
            session = arg.partition('=')[2]
    # Let Herdr diagnose malformed flags, and never contact SSH for help/version.
    if pending or help_requested or not remote or remote.startswith('-'):
        return None
    return remote, session


def main():
    args = sys.argv[1:]
    binary = ROOT / '.build/bin/herdr'
    if not os.access(binary, os.X_OK):
        raise SystemExit('Build Herdr first: ' + str(ROOT / 'build.sh'))
    env = dict(os.environ)
    for key in ('HERDR_SOCKET_PATH', 'HERDR_CLIENT_SOCKET_PATH', 'HERDR_ENV',
                'HERDR_PANE_ID', 'HERDR_WORKSPACE_ID', 'HERDR_TAB_ID'):
        env.pop(key, None)
    # Keep the established isolated default without inserting CLI arguments.
    env['HERDR_SESSION'] = 'yazi-links'
    env['PATH'] = str(Path.home() / '.local/bin') + ':/opt/homebrew/bin:/usr/local/bin:' + env.get('PATH', '')
    setup = preparation(args, env['HERDR_SESSION'])
    if setup:
        host, session = setup
        command = 'exec "$HOME/pets/herdr-yazi-links/scripts/prepare.sh" ' + shlex.quote(session)
        result = subprocess.run(['ssh', '--', host, command], env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
    os.execve(binary, [str(binary), *args], env)


if __name__ == '__main__':
    main()
