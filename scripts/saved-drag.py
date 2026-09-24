#!/usr/bin/env python3
"""Maintain local receivers for enabled Herdr SSH profiles. No server mutations."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]

def state_dir():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home()/'.local/state'))) / 'herdr-yazi-drag/saved-machines'

def targets(rows):
    if not isinstance(rows, list):
        raise ValueError('Expected machine list')
    result = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid machine profile')
        if not row.get('enabled'):
            continue
        host, session = row.get('target'), row.get('session')
        if not isinstance(host, str) or not host or host.startswith('-'):
            raise ValueError('Invalid SSH target')
        if not isinstance(session, str) or not session:
            raise ValueError('Invalid remote session')
        result.add((host, session))
    return result

class Receivers:
    def __init__(self, python, env, log):
        self.python, self.env, self.log = python, env, log
        self.children = {}
        self.retry = {}

    def stop(self, key):
        item = self.children.pop(key)
        child = item['process']
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=25)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        child.stdout.close()

    def reconcile(self, desired, now):
        for key in list(self.children):
            item = self.children[key]
            child = item['process']
            if key not in desired:
                self.stop(key)
                self.retry.pop(key, None)
                continue
            if child.poll() is not None or (not item['ready'] and now-item['started'] > 30):
                self.stop(key)
                old = self.retry.get(key, (0, 1))[1]
                delay = min(old * 2, 30)
                self.retry[key] = (now + delay, delay)
                continue
            if not item['ready'] and select.select([child.stdout], [], [], 0)[0]:
                # drag-client emits exactly one short readiness line.
                item['ready'] = child.stdout.readline() == b'READY\n'
            if item['ready'] and now-item['started'] > 60:
                self.retry[key] = (0, 1)
        for key in desired - self.children.keys():
            if now < self.retry.get(key, (0, 1))[0]:
                continue
            child = subprocess.Popen([self.python, str(ROOT/'scripts/drag-client.py'), *key],
                                     env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=self.log)
            self.children[key] = {'process': child, 'ready': False, 'started': now}

    def status(self):
        return [{'target': key[0], 'session': key[1], 'ready': item['ready'],
                 'pid': item['process'].pid} for key, item in sorted(self.children.items())]

    def close(self):
        for key in list(self.children):
            self.stop(key)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--herdr', default=shutil.which('herdr') or str(ROOT/'.build/bin/herdr'))
    args = parser.parse_args()
    state = state_dir()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = (state/'manager.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return
    env = {k:v for k,v in os.environ.items() if k not in ('HERDR_SOCKET_PATH', 'HERDR_CLIENT_SOCKET_PATH', 'HERDR_SESSION', 'HERDR_ENV', 'HERDR_PANE_ID', 'HERDR_TAB_ID', 'HERDR_WORKSPACE_ID')}
    python = ROOT/'.build/drag-venv/bin/python'
    if not python.is_file() or not shutil.which('ripdrag', path=env.get('PATH')):
        raise RuntimeError('Install local ripdrag and the drag receiver environment first')
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with (state/'manager.log').open('a', buffering=1) as log:
        receivers = Receivers(str(python), env, log)
        desired, refresh = set(), 0
        try:
            while not stopping:
                now = time.monotonic()
                if now >= refresh:
                    try:
                        result = subprocess.run([args.herdr, 'machine', 'list', '--json'], env=env,
                                                text=True, capture_output=True, check=True, timeout=5)
                        desired = targets(json.loads(result.stdout))
                    except Exception as error:
                        log.write('Machine catalog: '+str(error)+'\n')
                        # Keep existing connections when the catalog cannot be read.
                    refresh = now + 2
                receivers.reconcile(desired, now)
                tmp = state/'status.tmp'
                tmp.write_text(json.dumps({'pid':os.getpid(), 'receivers':receivers.status()}))
                tmp.replace(state/'status.json')
                time.sleep(.2)
        finally:
            receivers.close()
            (state/'status.json').unlink(missing_ok=True)

if __name__ == '__main__':
    main()
