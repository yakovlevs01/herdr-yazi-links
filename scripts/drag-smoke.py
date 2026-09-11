#!/usr/bin/env python3
"""Test real remote launcher -> Yazi Ctrl+G -> SFTP -> local ripdrag argv.

Uses only a fresh UUID Herdr session. No server is prestarted: herdr-yazi's
normal prepare.sh chain must create it. The automated phase substitutes only
local ripdrag with an argv recorder. --real-ripdrag additionally opens a real
window, but does not verify a GUI drop into another application.
--progress-check throttles the real SFTP byte stream to verify rendered Yazi
progress, completion and persistent errors.
"""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def until(function, description, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(0.1)
    raise RuntimeError('Timed out: ' + description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote', required=True)
    parser.add_argument('--remote-root', help='Defaults to ~/pets/herdr-yazi-links on host')
    parser.add_argument('--launcher', type=Path, default=ROOT / 'herdr-yazi')
    parser.add_argument('--output', type=Path, help='Retained logs and downloaded test copies')
    parser.add_argument('--progress-check', action='store_true', help='Throttle real SFTP and verify progress, ready and persistent error in Yazi')
    parser.add_argument('--shell-yazi', action='store_true', help='Launch yazi from an ordinary shell pane instead of the link plugin')
    parser.add_argument('--real-ripdrag', action='store_true', help='Also launch real GUI, manual drop still required')
    args = parser.parse_args()
    actual_ripdrag = shutil.which('ripdrag')
    if args.real_ripdrag and not actual_ripdrag:
        parser.error('ripdrag is absent from the local PATH')
    tmp = args.output or Path(tempfile.mkdtemp(prefix='herdr-drag-smoke-'))
    tmp = tmp.resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    session = 'drag-smoke-' + uuid.uuid4().hex[:12]
    print('Artifacts: ' + str(tmp), flush=True)
    print('Temporary remote session: ' + session, flush=True)
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', '--', args.remote]
    def remote(code, *values, **kwargs):
        return subprocess.run(ssh + [shlex.join(['python3', '-c', code, *values])],
                              text=True, stdout=subprocess.PIPE, check=True, timeout=35, **kwargs)
    # This preparation creates files only. Herdr starts exclusively through launcher.
    fixture_code = '''import json, pathlib, sys, tempfile
root = pathlib.Path(sys.argv[1]).expanduser() if sys.argv[1] else pathlib.Path.home()/'pets/herdr-yazi-links'
tmp = pathlib.Path(tempfile.mkdtemp(prefix='herdr-drag-fixture-'))
name = '00-hover 雪 \\'"$;[].txt'
other = '01-other\\n雪 `$(touch NOT_EXECUTED)` \\'".txt'
(tmp/'one').mkdir(); (tmp/'two').mkdir()
files = [(tmp/'one'/name, 'hover payload\\n'), (tmp/'one'/other, 'selected payload\\n'), (tmp/'two'/name, 'same basename different bytes\\n')]
for path, content in files: path.write_text(content)
(tmp/'three').mkdir()
(tmp/'three'/'00-hover-directory').mkdir()
(tmp/'three'/'00-hover-progress.bin').write_bytes(b'p' * (4 * 1024 * 1024))
print(json.dumps({'root':str(root), 'tmp':str(tmp), 'files':[(str(p), c) for p,c in files]}))
'''
    info = json.loads(remote(fixture_code, args.remote_root or '').stdout)
    remote_tmp, remote_root = info['tmp'], info['root']
    (tmp / 'fixtures.json').write_text(json.dumps(info, indent=2))
    bindir = tmp / 'bin'
    bindir.mkdir()
    recorder = bindir / 'ripdrag'
    recorder.write_text('#!' + sys.executable + '''
import json, os, sys
with open(os.environ['HERDR_DRAG_SMOKE_ARGV'], 'a') as stream:
    stream.write(json.dumps(sys.argv[1:]) + '\\n')
''')
    recorder.chmod(0o755)
    if args.progress_check:
        # Only the SFTP subsystem is throttled; broker and Herdr SSH use exec.
        # File contents still travel over the real OpenSSH SFTP connection.
        actual_ssh = shutil.which('ssh')
        wrapper = bindir / 'ssh'
        wrapper.write_text('#!' + sys.executable + '\n' + 'SSH = ' + repr(actual_ssh) + '\n' + """
import os, subprocess, sys, time
if '-s' not in sys.argv[1:] or sys.argv[-1] != 'sftp':
    os.execv(SSH, [SSH, *sys.argv[1:]])
process = subprocess.Popen([SSH, *sys.argv[1:]], stdout=subprocess.PIPE)
try:
    while True:
        block = os.read(process.stdout.fileno(), 8192)
        if not block:
            break
        time.sleep(len(block) / (256 * 1024))
        sys.stdout.buffer.write(block)
        sys.stdout.buffer.flush()
finally:
    process.stdout.close()
    if process.poll() is None:
        process.terminate()
sys.exit(process.wait())
""")
        wrapper.chmod(0o755)
    argv_log = tmp / 'ripdrag.jsonl'
    argv_log.touch()
    env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_')}
    env.update(PATH=str(bindir) + os.pathsep + os.environ['PATH'],
               HERDR_DRAG_CACHE=str(tmp / 'cache'), HERDR_DRAG_SMOKE_ARGV=str(argv_log),
               TERM='xterm-256color')
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 150, 0, 0))
    transcript = (tmp / 'terminal.log').open('wb')
    def drain():
        try:
            while True:
                chunk = os.read(master, 65536)
                if not chunk:
                    break
                transcript.write(chunk)
                transcript.flush()
        except OSError:
            pass
    client = tunnel = None
    copied = []
    try:
        client = subprocess.Popen([str(args.launcher.resolve()), '--remote', args.remote,
                                   '--remote-keybindings', 'server', '--session', session],
                                  env=env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        slave = None
        threading.Thread(target=drain, daemon=True).start()
        socket_code = '''import json, pathlib, sys, time
session=sys.argv[1]
for attempt in range(250):
    paths=list((pathlib.Path.home()/'.config').glob('herdr*/sessions/'+session+'/herdr.sock'))
    if len(paths)==1: print(json.dumps(str(paths[0]))); break
    time.sleep(.1)
else: raise RuntimeError('Launcher did not create unique remote server socket')
'''
        remote_socket = json.loads(remote(socket_code, session).stdout)
        if client.poll() is not None:
            raise RuntimeError('Launcher exited early: ' + str(client.returncode))
        local_socket = tmp / 'control.sock'
        tunnel_log = (tmp / 'tunnel.log').open('wb')
        tunnel = subprocess.Popen(['ssh', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
                                   '-N', '-L', str(local_socket) + ':' + remote_socket,
                                   '--', args.remote], stdout=subprocess.DEVNULL, stderr=tunnel_log)
        until(lambda: local_socket.exists(), 'control socket forwarding')
        def api(method, params=None):
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(10)
                connection.connect(str(local_socket))
                connection.sendall((json.dumps({'id': 'drag-smoke', 'method': method,
                                                'params': params or {}}) + '\n').encode())
                with connection.makefile('rb') as stream:
                    response = json.loads(stream.readline(2_000_000))
            if 'error' in response:
                raise RuntimeError(method + ': ' + str(response['error']))
            return response['result']
        panes = lambda: api('pane.list')['panes']
        source = until(lambda: panes(), 'initial shell pane')[0]['pane_id']
        def visible(pane):
            screen = api('pane.read', {'pane_id': pane, 'source': 'visible', 'format': 'text'})['read']['text']
            (tmp / 'last-pane.txt').write_text(screen)
            return screen
        def open_yazi(path):
            before = {p['pane_id'] for p in panes()}
            if args.shell_yazi:
                api('pane.split', {'pane_id': source, 'direction': 'right',
                    'cwd': str(Path(path).parent), 'focus': True})
            else:
                api('plugin.pane.open', {'plugin_id': 'local.yazi-links', 'entrypoint': 'yazi',
                    'placement': 'split', 'target_pane_id': source, 'direction': 'right',
                    'cwd': str(Path(path).parent), 'focus': True, 'env': {'YAZI_LINK_PATH': path}})
            pane = until(lambda: next((p['pane_id'] for p in panes() if p['pane_id'] not in before), None), 'Yazi pane')
            if args.shell_yazi:
                until(lambda: any(p['pane_id'] == pane and p.get('foreground_cwd') for p in panes()), 'shell startup')
                api('pane.send_input', {'pane_id': pane, 'text': shlex.join(['exec', 'yazi', path]), 'keys': ['enter']})
            until(lambda: '00-hover' in visible(pane), 'Yazi hovered file')
            os.write(master, b'\x1b[I')
            time.sleep(0.5)
            return pane
        def calls():
            return [json.loads(line) for line in argv_log.read_text().splitlines() if line]
        def trigger(expected, progress_pane=None):
            previous = len(calls())
            os.write(master, b'\x07')
            if progress_pane is not None:
                def progressing():
                    screen = visible(progress_pane)
                    match = re.search(r'Drag \d+/\d+ (\d+)%', screen)
                    return screen if match and 0 < int(match[1]) < 100 else None
                progress_screen = until(progressing, 'rendered intermediate Yazi progress', timeout=30)
                (tmp / 'progress-pane.txt').write_text(progress_screen)
            recorded = until(lambda: calls()[previous:] or None, 'Ctrl+G download and local ripdrag', timeout=45)[0]
            if recorded[:4] != ['-x', '-a', '-n', '-b']:
                raise RuntimeError('Unexpected ripdrag flags: ' + repr(recorded))
            if progress_pane is not None:
                ready_screen = until(lambda: (screen if 'Drag: ready' in screen else None)
                                     if (screen := visible(progress_pane)) else None,
                                     'rendered ready in Yazi', timeout=5)
                (tmp / 'ready-pane.txt').write_text(ready_screen)
            files = [Path(path) for path in recorded[4:]]
            received = Counter((p.name, p.read_text()) for p in files)
            wanted = Counter((Path(path).name, content) for path, content in expected)
            if received != wanted:
                raise RuntimeError('Downloaded selection mismatch: ' + repr((received, wanted)))
            for path in files:
                if not path.is_relative_to(tmp / 'cache') or not (path.parents[1] / '.complete').is_file():
                    raise RuntimeError('File exposed before batch completion: ' + str(path))
            copied.extend(files)
            return files
        first, second, duplicate = info['files']
        pane = open_yazi(first[0])
        trigger([first])
        print('PASS hovered file: real Ctrl+G -> SFTP bytes -> local ripdrag argv', flush=True)
        # Yazi's default Ctrl+A selects every file in this fixture directory.
        os.write(master, b'\x01')
        time.sleep(0.5)
        (tmp / 'selected-pane.txt').write_text(visible(pane))
        trigger([first, second])
        print('PASS multiselection, Unicode, quotes, newline and shell punctuation', flush=True)
        time.sleep(4)  # Allow the completed progress task's three-second display to end.
        api('pane.send_keys', {'pane_id': pane, 'keys': ['q']})
        until(lambda: all(p['pane_id'] != pane for p in panes()), 'first Yazi exit')
        pane = open_yazi(duplicate[0])
        trigger([duplicate])
        if copied[0] == copied[-1] or copied[0].read_text() == copied[-1].read_text():
            raise RuntimeError('Duplicate basename overwrote prior copy')
        print('PASS repeated basename preserves earlier copy after ripdrag exit', flush=True)
        if args.progress_check:
            time.sleep(4)
            api('pane.send_keys', {'pane_id': pane, 'keys': ['q']})
            until(lambda: all(p['pane_id'] != pane for p in panes()), 'duplicate Yazi exit')
            slow = str(Path(remote_tmp) / 'three/00-hover-progress.bin')
            pane = open_yazi(slow)
            trigger([(slow, 'p' * (4 * 1024 * 1024))], progress_pane=pane)
            print('PASS rendered intermediate progress and ready after complete download', flush=True)
            # The fixture directory sorts first; gg selects it.
            os.write(master, b'gg')
            time.sleep(0.3)
            previous = len(calls())
            os.write(master, b'\x07')
            error_screen = until(lambda: (screen if 'Drag error:' in screen else None)
                                 if (screen := visible(pane)) else None,
                                 'directory rejection rendered in Yazi')
            (tmp / 'error-pane.txt').write_text(error_screen)
            time.sleep(3.5)
            if 'Drag error:' not in visible(pane) or len(calls()) != previous:
                raise RuntimeError('Directory error disappeared or launched ripdrag')
            print('PASS directory rejection persists in Yazi without launching ripdrag', flush=True)
        remote_verify = '''import json, pathlib, sys
info=json.loads(sys.argv[1])
for path, content in info['files']:
    assert pathlib.Path(path).read_text()==content
assert (pathlib.Path(info['tmp'])/'three'/'00-hover-progress.bin').read_bytes() == b'p' * (4 * 1024 * 1024)
assert (pathlib.Path(info['tmp'])/'three'/'00-hover-directory').is_dir()
assert not list(pathlib.Path(info['tmp']).rglob('NOT_EXECUTED'))
'''
        remote(remote_verify, json.dumps(info))
        print('PASS remote originals unchanged', flush=True)
        if args.real_ripdrag:
            with (tmp / 'real-ripdrag.log').open('wb') as log:
                gui = subprocess.Popen([actual_ripdrag, '-x', '-a', '-n', '-b', str(copied[0])],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
            time.sleep(1)
            if gui.poll() is not None:
                raise RuntimeError('Real ripdrag exited before GUI check: ' + str(gui.returncode))
            print('PASS real ripdrag process started, PID ' + str(gui.pid) + '; GUI drop requires manual verification', flush=True)
        (tmp / 'result.json').write_text(json.dumps({'host': args.remote, 'session': session,
            'yazi_launch': 'shell' if args.shell_yazi else 'link plugin',
            'automated': 'passed', 'progress_ui': 'passed' if args.progress_check else 'not tested', 'gui_drop': 'not tested', 'copies': list(map(str, copied))}, indent=2))
    except Exception:
        if (tmp / 'cache/receiver.log').exists():
            sys.stderr.write((tmp / 'cache/receiver.log').read_text()[-4000:] + '\n')
        raise
    finally:
        cleanup = '''import pathlib, shutil, subprocess, sys
root, session, tmp=sys.argv[1:]
subprocess.run([str(pathlib.Path(root)/'.build/bin/herdr'), '--session', session, 'server', 'stop'], timeout=15)
shutil.rmtree(tmp)
'''
        try:
            remote(cleanup, remote_root, session, remote_tmp)
        finally:
            if client:
                try:
                    client.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    client.terminate()
                    client.wait(timeout=8)
            if tunnel:
                tunnel.terminate()
                tunnel.wait(timeout=5)
            if slave is not None:
                os.close(slave)
            os.close(master)
        print('Retained test copies and logs: ' + str(tmp), flush=True)


if __name__ == '__main__':
    main()
