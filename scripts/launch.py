#!/usr/bin/env python3
"""Pass the original argv to Herdr; inspect only SSH/session setup metadata."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import select
import time
import signal

ROOT = Path(__file__).resolve().parents[1]


def remote_client(binary, args, env, host, session, python):
    """Own receiver lifetime without changing Herdr's arguments or server lifetime."""
    def interrupted(signum, frame):
        raise SystemExit(128 + signum)
    previous = {sig: signal.signal(sig, interrupted) for sig in (signal.SIGTERM, signal.SIGHUP)}
    receiver = subprocess.Popen([str(python), str(ROOT / 'scripts/drag-client.py'), host, session],
                                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    client = None
    try:
        ready, _, _ = select.select([receiver.stdout], [], [], 25)
        if not ready or receiver.stdout.readline() != b'READY\n':
            raise SystemExit('Local drag receiver could not start. Resolve the reported error and reconnect.')
        client = subprocess.Popen([str(binary), *args], env=env)
        while client.poll() is None:
            if receiver.poll() is not None:
                client.terminate()
                client.wait()
                raise SystemExit('Drag receiver disconnected; Herdr server remains running. Reconnect to continue.')
            time.sleep(0.1)
        return client.returncode
    finally:
        if client is not None and client.poll() is None:
            client.terminate()
            client.wait()
        receiver.terminate()
        try:
            receiver.wait(timeout=25)
        except subprocess.TimeoutExpired:
            receiver.kill()
            receiver.wait()
        receiver.stdout.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def preparation(args, default_session):
    remote = None
    session = default_session
    pending = None
    help_requested = False
    remote_count = 0
    for arg in args:
        if pending:
            if pending == 'remote':
                remote = arg
            else:
                session = arg
            pending = None
        elif arg == '--':
            break
        elif arg in ('--help', '-h', '--version', '-V', '--default-config', '--skill'):
            help_requested = True
        elif arg == '--remote':
            remote_count += 1
            pending = 'remote'
        elif arg == '--session':
            pending = 'session'
        elif arg.startswith('--remote='):
            remote_count += 1
            remote = arg.partition('=')[2]
        elif arg.startswith('--session='):
            session = arg.partition('=')[2]
    # Let Herdr diagnose malformed flags, and never contact SSH for help/version.
    if pending or help_requested or remote_count != 1 or not remote or remote.startswith('-'):
        return None
    return remote, session


def has_subcommand(args):
    """Distinguish pane/agent/etc. commands without restricting future CLI flags."""
    pending = False
    for arg in args:
        if pending:
            pending = False
        elif arg == '--':
            break
        elif arg in ('--session', '--remote', '--remote-keybindings'):
            pending = True
        elif not arg.startswith('-'):
            return True
    return False


def launch_environment(args, source):
    env = dict(source)
    # Commands inside a pane must retain its socket, session and --current IDs.
    # Only an application attach starts outside the calling pane's context.
    remote_attach = bool(args and args[0].startswith('-') and preparation(args, 'yazi-links'))
    if remote_attach or not has_subcommand(args):
        if env.get('HERDR_SOCKET_PATH') or env.get('HERDR_ENV') == '1':
            env.pop('HERDR_SESSION', None)
        for key in ('HERDR_SOCKET_PATH', 'HERDR_CLIENT_SOCKET_PATH', 'HERDR_ENV',
                    'HERDR_PANE_ID', 'HERDR_WORKSPACE_ID', 'HERDR_TAB_ID'):
            env.pop(key, None)
    env.setdefault('HERDR_SESSION', 'yazi-links')
    paths = env.get('PATH', '').split(os.pathsep)
    for fallback in (str(Path.home() / '.local/bin'), '/opt/homebrew/bin', '/usr/local/bin'):
        if fallback not in paths:
            paths.append(fallback)
    env['PATH'] = os.pathsep.join(paths)
    return env


def main():
    args = sys.argv[1:]
    binary = ROOT / '.build/bin/herdr'
    if not os.access(binary, os.X_OK):
        raise SystemExit('Build Herdr first: ' + str(ROOT / 'build.sh'))
    env = launch_environment(args, os.environ)
    setup = None if args and not args[0].startswith('-') else preparation(args, env['HERDR_SESSION'])
    if setup:
        host, session = setup
        command = 'exec "$HOME/pets/herdr-yazi-links/scripts/prepare.sh" ' + shlex.quote(session)
        result = subprocess.run(['ssh', '--', host, command], env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
        python = ROOT / '.build/drag-venv/bin/python'
        if python.exists():
            raise SystemExit(remote_client(binary, args, env, host, session, python))
    os.execve(binary, [str(binary), *args], env)


if __name__ == '__main__':
    main()
