#!/usr/bin/env python3
"""Own the Linux yazi-links server through a user service; never replace a live server."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UNIT = 'herdr-yazi-server.service'
MARKER = ROOT / '.build/server-management.json'
BINARY = ROOT / '.build/bin/herdr'


def clean_environment(source):
    return {k: v for k, v in source.items()
            if not k.startswith(('SSH_', 'HERDR_')) and k not in ('XDG_SESSION_ID', 'XDG_SESSION_TYPE')}


def desktop_ready(env):
    runtime = env.get('XDG_RUNTIME_DIR', '')
    wayland = env.get('WAYLAND_DISPLAY', '')
    display = env.get('DISPLAY', '')
    return bool((runtime and wayland and (Path(runtime) / wayland).is_socket()) or
                (display.startswith(':') and
                 (Path('/tmp/.X11-unix') / ('X' + display[1:].split('.')[0])).is_socket()))


def ensure():
    if not MARKER.exists():
        return
    # Import only an actual local desktop caller, never SSH's inherited variables.
    if not os.environ.get('SSH_CONNECTION') and desktop_ready(os.environ):
        keys = [k for k in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
                           'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_CURRENT_DESKTOP')
                if os.environ.get(k)]
        subprocess.run(['systemctl', '--user', 'import-environment', *keys], check=True)
    probe_env = clean_environment(os.environ)
    listening = subprocess.run([str(BINARY), '--session', 'yazi-links', 'pane', 'list'],
                               env=probe_env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=10).returncode == 0
    active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', UNIT]).returncode == 0
    if listening and not active:
        print('Herdr: using existing legacy server; desktop fix awaits explicit migration. '
              'See docs/server-management.ru.md.', file=sys.stderr)
        return
    subprocess.run(['systemctl', '--user', 'start', UNIT], check=True)
    import time
    for _ in range(100):
        if subprocess.run([str(BINARY), '--session', 'yazi-links', 'pane', 'list'],
                          env=probe_env, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=5).returncode == 0:
            return
        time.sleep(.1)
    raise RuntimeError('Managed server did not become ready; inspect journalctl --user -u ' + UNIT)


def serve():
    env = clean_environment(os.environ)
    if not desktop_ready(env):
        raise RuntimeError('No local desktop socket. Log in to the PC desktop before starting yazi-links.')
    # Do not claim ownership of a server another binary already started.
    if subprocess.run([str(BINARY), '--session', 'yazi-links', 'pane', 'list'], env=env,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('Another yazi-links server is already running; refusing replacement.')
    if os.getsid(0) != os.getpid():
        os.setsid()
    os.execve(BINARY, [str(BINARY), '--session', 'yazi-links', 'server'], env)


def main():
    try:
        if sys.argv[1:] == ['serve']:
            serve()
        elif sys.argv[1:] == ['ensure']:
            ensure()
        else:
            raise RuntimeError('Usage: server-manager.py ensure|serve')
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print('Herdr service: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
