#!/usr/bin/env python3
"""Exercise managed server isolation using a disposable service and config only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
name = 'herdr-yazi-check-' + str(os.getpid())
unit = name + '.service'
with tempfile.TemporaryDirectory(prefix=name) as temp:
    root = Path(temp)
    (root / 'scripts').mkdir()
    (root / '.build/bin').mkdir(parents=True)
    (root / '.build/bin/herdr').symlink_to(ROOT / '.build/bin/herdr')
    script = root / 'scripts/server-manager.py'
    script.write_text((ROOT / 'scripts/server-manager.py').read_text().replace('yazi-links', name))
    env = dict(os.environ, XDG_CONFIG_HOME=str(root / 'config'))
    for key in list(env):
        if key.startswith('HERDR_'):
            del env[key]
    binary = str(ROOT / '.build/bin/herdr')
    try:
        for origin in ('local', 'ssh'):
            caller = dict(env)
            if origin == 'ssh':
                caller.update(SSH_CONNECTION='test-remote', SSH_CLIENT='test', XDG_SESSION_TYPE='tty')
                caller.pop('DISPLAY', None)
                caller.pop('WAYLAND_DISPLAY', None)
            subprocess.run(['systemd-run', '--user', '--unit', name, '--collect',
                            '--setenv=XDG_CONFIG_HOME='+str(root / 'config'),
                            sys.executable, str(script), 'serve'], env=caller, check=True)
            for _ in range(100):
                result = subprocess.run([binary, '--session', name, 'pane', 'list'], env=env, capture_output=True)
                if result.returncode == 0:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Server not ready')
            pid = subprocess.check_output(['systemctl', '--user', 'show', unit, '-p', 'MainPID', '--value'], text=True).strip()
            values = dict(item.split(b'=', 1) for item in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in item)
            assert not any(k.startswith(b'SSH_') for k in values), 'SSH environment leaked'
            assert values.get(b'DISPLAY') or values.get(b'WAYLAND_DISPLAY'), 'Desktop missing'
            assert unit in Path('/proc/'+pid+'/cgroup').read_text()
            assert os.getsid(int(pid)) == int(pid), 'Remote daemon SID check would fail'
            print('PASS '+origin+': pinned server ready, desktop environment, no SSH variables, service cgroup, detached SID')
            subprocess.run(['systemctl', '--user', 'stop', unit], check=True)
    finally:
        subprocess.run(['systemctl', '--user', 'stop', unit], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
