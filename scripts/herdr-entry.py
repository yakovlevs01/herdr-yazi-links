#!/usr/bin/env python3
"""SSH-discoverable entry point for the pinned Herdr distribution."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def invocation(args, env):
    session = env.get('HERDR_SESSION', 'default')
    command = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--session' and i + 1 < len(args):
            session = args[i + 1]
            i += 2
            continue
        if arg.startswith('--session='):
            session = arg.split('=', 1)[1]
        elif arg in ('--remote', '--machine') or arg.startswith(('--remote=', '--machine=')):
            return session, [], False
        elif arg in ('--help', '-h', '--version', '-V', '--default-config', '--skill'):
            return session, [], False
        elif not arg.startswith('-'):
            command = args[i:]
            break
        i += 1
    if command[:2] == ['session', 'attach'] and len(command) == 3:
        session = command[2]
    starts = not command or command == ['server'] or command == ['remote-client-bridge'] or command[:2] == ['session', 'attach']
    return session, command, starts


def main():
    args = sys.argv[1:]
    session, command, starts = invocation(args, os.environ)
    managed = (ROOT / '.build/server-management.json').exists()
    if managed and command and command[0] in ('update', 'channel'):
        raise SystemExit('This Herdr belongs to herdr-yazi-links. Update through its tested build/install workflow.')
    if managed and session == 'yazi-links' and starts:
        subprocess.run([sys.executable, str(ROOT / 'scripts/server-manager.py'), 'ensure'], check=True)
        if command == ['server']:
            return
    binary = ROOT / '.build/bin/herdr'
    os.execve(binary, [str(binary), *args], os.environ)


if __name__ == '__main__':
    main()
