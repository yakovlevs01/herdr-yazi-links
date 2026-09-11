#!/usr/bin/env python3
"""Local receiver owned by one herdr-yazi client process."""
import argparse
import json
import os
from pathlib import Path
import queue
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from drag import LIMIT, packet, validate
from drag_transfer import download


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('session')
    args = parser.parse_args()
    cache = Path(os.environ.get('HERDR_DRAG_CACHE', str(Path.home() / '.cache/herdr-yazi-drag')))
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = (cache / 'receiver.log').open('a', buffering=1)
    ripdrag = shutil.which('ripdrag')
    if not ripdrag:
        raise RuntimeError('Install local ripdrag before using remote drag')
    command = 'exec python3 "$HOME/pets/herdr-yazi-links/drag.py" serve ' + shlex.join([args.session, socket.gethostname()])
    ssh = subprocess.Popen(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ServerAliveInterval=5',
                            '-o', 'ServerAliveCountMax=3', '--', args.host, command],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
    write_lock = threading.Lock()
    stop = threading.Event()
    def feedback(value):
        with write_lock:
            ssh.stdin.write(packet(value))
            ssh.stdin.flush()
    def report(message, level='info', job=None, **status):
        log.write(json.dumps({'time': time.time(), 'level': level, 'id': job, 'message': message, **status}) + '\n')
        try:
            feedback({'message': message, 'level': level, 'id': job, **status})
        except (OSError, ValueError):
            pass
    def heartbeat():
        while not stop.wait(2):
            windows[:] = [window for window in windows if window.poll() is None]
            try:
                feedback({'heartbeat': True})
            except (OSError, ValueError):
                return
    jobs = queue.Queue(maxsize=8)
    windows = []
    def work():
        while not stop.is_set():
            try:
                job = jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                report('Preparing download', job=job['id'], state='downloading')
                last_progress = [0.0]
                counters = {}
                last_index = [None]
                def progress(value):
                    if stop.is_set():
                        raise RuntimeError('Receiver disconnected; download cancelled')
                    counters.update(value)
                    if (time.monotonic() - last_progress[0] >= 0.2
                            or value['file_index'] != last_index[0]):
                        report('Downloading', job=job['id'], state='downloading', **value)
                        last_progress[0] = time.monotonic()
                        last_index[0] = value['file_index']
                files = download(args.host, job['paths'], cache, batch_progress=progress)
                if stop.is_set():
                    raise RuntimeError('Disconnected before ripdrag launch; completed cache retained')
                window = subprocess.Popen([ripdrag, '-x', '-a', '-n', '-b', *map(str, files)],
                                          stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                          start_new_session=True)
                windows.append(window)
                time.sleep(0.2)
                if window.poll() not in (None, 0):
                    raise RuntimeError('ripdrag exited with code ' + str(window.returncode))
                counters['percent'] = 100
                report('Opened ripdrag: ' + str(files[0].parent.parent), job=job['id'], state='done', **counters)
            except Exception as error:
                report(str(error), 'error', job['id'], state='error')
    try:
        ready, _, _ = select.select([ssh.stdout], [], [], 20)
        if not ready:
            raise RuntimeError('Receiver startup timed out; see ' + str(cache / 'receiver.log'))
        greeting = ssh.stdout.readline(LIMIT)
        if not greeting:
            raise RuntimeError('Remote receiver refused connection; possible receiver conflict. See ' + str(cache / 'receiver.log'))
        token = json.loads(greeting)['ready']
        threading.Thread(target=heartbeat, daemon=True).start()
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        print('READY', flush=True)
        while True:
            line = ssh.stdout.readline(LIMIT + 1025)
            if not line:
                break
            if len(line) > LIMIT + 1024:
                raise ValueError('Oversized request')
            job = json.loads(line)
            validate({'paths': job['paths']})
            if job.get('receiver') != token:
                raise ValueError('Receiver mismatch')
            try:
                jobs.put_nowait(job)
            except queue.Full:
                report('Queue full; request rejected', 'error', job['id'], state='error')
        raise RuntimeError('Receiver SSH connection closed. Reconnect Herdr to restore drag.')
    finally:
        stop.set()
        if 'worker' in locals():
            worker.join(timeout=20)
        ssh.stdin.close()
        try:
            ssh.wait(timeout=3)
        except subprocess.TimeoutExpired:
            ssh.terminate()
            ssh.wait(timeout=3)
        ssh.stdout.close()
        log.close()


if __name__ == '__main__':
    def terminate(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    try:
        main()
    except Exception as error:
        print('Herdr drag: ' + str(error), file=sys.stderr)
        sys.exit(1)
