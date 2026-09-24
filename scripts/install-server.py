#!/usr/bin/env python3
"""Install managed Linux server launch without starting/stopping any Herdr session."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def install():
    if not sys.platform.startswith('linux'):
        raise RuntimeError('Managed server installation requires Linux/systemd.')
    if Path(os.environ.get('SHELL', '')).name != 'zsh':
        raise RuntimeError('Automatic SSH PATH integration currently requires zsh.')
    subprocess.run(['systemctl', '--user', 'show-environment'], check=True, stdout=subprocess.DEVNULL)
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    path = str(Path.home() / '.local/bin') + ':' + str(ROOT / '.build/bin') + ':/usr/local/bin:/usr/bin:/bin'
    unit = '\n'.join(['[Unit]', 'Description=Managed Herdr Yazi session', '', '[Service]',
        'Type=exec', 'WorkingDirectory=%h',
        'ExecStart='+quote(sys.executable)+' '+quote(ROOT / 'scripts/server-manager.py')+' serve',
        'Environment='+quote('PATH='+path),
        'UnsetEnvironment=SSH_CONNECTION SSH_CLIENT SSH_TTY SSH_AUTH_SOCK XDG_SESSION_ID XDG_SESSION_TYPE',
        'KillMode=control-group', 'TimeoutStopSec=30', '',
        '# Started on demand by the launcher, after the local desktop is available.', ''])
    (units / 'herdr-yazi-server.service').write_text(unit)
    entry = Path.home() / '.local/bin/herdr'
    entry.parent.mkdir(parents=True, exist_ok=True)
    target = ROOT / 'scripts/herdr-entry.py'
    if entry.exists() or entry.is_symlink():
        if entry.resolve() != target.resolve():
            entry.rename(entry.with_name('herdr.before-yazi-' + str(time.time_ns())))
    if not entry.is_symlink():
        entry.symlink_to(target)
    # Herdr discovers the remote executable through the user's shell. zsh reads
    # .zshenv for noninteractive SSH too; do not alter the system executable.
    rc = Path.home() / '.zshenv'
    block = '\n# herdr-yazi-links managed entry (also for noninteractive SSH)\nexport PATH="$HOME/.local/bin:$PATH"\n'
    old = rc.read_text() if rc.exists() else ''
    if block not in old:
        if rc.exists():
            shutil.copy2(rc, rc.with_name('.zshenv.before-yazi-' + str(time.time_ns())))
        rc.write_text(old + block)
    (ROOT / '.build/server-management.json').write_text(json.dumps({'session': 'yazi-links', 'unit': 'herdr-yazi-server.service'})+'\n')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    print('Managed server installed. Existing sessions were not restarted.')


if __name__ == '__main__':
    install()
