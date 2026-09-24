#!/usr/bin/env python3
"""Install the saved-machine receiver in the Linux graphical user session."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    if not sys.platform.startswith('linux') or not shutil.which('systemctl'):
        raise SystemExit('This installer requires Linux systemd. Run scripts/saved-drag.py manually on other systems.')
    if not shutil.which('ripdrag') or not (ROOT/'.build/drag-venv/bin/python').exists():
        raise SystemExit('Install ripdrag and the drag receiver environment first.')
    # Quote systemd values, including literal percent specifiers.
    def quote(value):
        return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'
    directory = Path.home()/'.config/systemd/user'
    directory.mkdir(parents=True, exist_ok=True)
    unit = directory/'herdr-yazi-saved-drag.service'
    path = str(Path.home()/'.local/bin') + ':/usr/local/bin:/usr/bin:/bin'
    text = '\n'.join([
        '[Unit]', 'Description=Herdr Yazi receivers for saved SSH machines',
        'After=graphical-session.target', 'PartOf=graphical-session.target', '',
        '[Service]',
        'ExecStart='+quote(sys.executable)+' '+quote(ROOT/'scripts/saved-drag.py'),
        'Environment='+quote('PATH='+path),
        'Restart=on-failure', 'RestartSec=5', 'TimeoutStopSec=65', '',
        '[Install]', 'WantedBy=graphical-session.target', ''])
    if unit.exists() and unit.read_text() != text:
        shutil.copy2(unit, unit.with_suffix('.service.bak'))
    unit.write_text(text)
    names = [key for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS', 'XAUTHORITY') if os.environ.get(key)]
    if names:
        subprocess.run(['systemctl', '--user', 'import-environment', *names], check=True)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', unit.name], check=True)
    subprocess.run(['systemctl', '--user', 'restart', unit.name], check=True)
    print('Saved-machine receivers enabled. Status: systemctl --user status '+unit.name)

if __name__ == '__main__':
    main()
