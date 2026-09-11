#!/usr/bin/env python3
"""Exercise an actual Herdr client/server, OSC 8, Ctrl-click and Yazi on Linux."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
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


def until(function, description, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(0.1)
    raise RuntimeError('Timed out: ' + description)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--herdr', default='herdr', help='Exact executable to test')
    parser.add_argument('--expect-paths', action='store_true', help='Require the plain-text path patch')
    parser.add_argument('--plugin', type=Path, default=ROOT)
    parser.add_argument('--remote', help='SSH host with the plugin and patched Herdr installed')
    parser.add_argument('--remote-root', help='Absolute plugin checkout path on the SSH host')
    parser.add_argument('--client-arg', action='append', default=[], help='Extra client argument, repeatable; use --client-arg=--flag')
    args = parser.parse_args()
    if bool(args.remote) != bool(args.remote_root):
        parser.error('--remote and --remote-root must be supplied together')
    if not sys.platform.startswith('linux'):
        parser.error('The automated PTY smoke test currently supports Linux only.')
    binary = shutil.which(args.herdr)
    if not binary:
        parser.error('Herdr executable not found: ' + args.herdr)
    binary = str(Path(binary).resolve())
    if not shutil.which('yazi'):
        parser.error('yazi must be installed in PATH')
    with tempfile.TemporaryDirectory(prefix='yazi-smoke-') as temporary:
        tmp = Path(temporary)
        session = 'smoke-' + uuid.uuid4().hex[:10]
        env = {k: v for k, v in os.environ.items() if not k.startswith('HERDR_')}
        env.update(XDG_CONFIG_HOME=str(tmp / 'config'), XDG_STATE_HOME=str(tmp / 'state'),
                   XDG_CACHE_HOME=str(tmp / 'cache'), TERM='xterm-256color', SHELL='/bin/sh')
        config = 'onboarding = false\n[terminal]\ndefault_shell = "/bin/sh"\n[ui]\nsidebar_width = 26\nsidebar_min_width = 26\nsidebar_max_width = 26\n'
        for name in ('herdr', 'herdr-dev'):
            directory = tmp / 'config' / name
            directory.mkdir(parents=True)
            (directory / 'config.toml').write_text(config)
        fixture = tmp / 'fixture'
        fixture.mkdir()
        target = fixture / 'smoke-target.txt'
        target.write_text('Yazi file link smoke test\n')
        renderer = tmp / 'render.py'
        renderer.write_text('''import sys
from pathlib import Path
p = Path(sys.argv[1])
mode = "osc"
while True:
    text = {"osc": "\\x1b]8;;" + p.as_uri() + "\\x1b\\\\OSC_LINK\\x1b]8;;\\x1b\\\\",
            "relative": p.name, "absolute": str(p), "missing": "missing-file.txt"}[mode]
    sys.stdout.write("\\x1b[2J\\x1b[H" + text + "\\n")
    sys.stdout.flush()
    mode = sys.stdin.readline().strip()
    if not mode: break
''')
        cli = [binary, '--session', session]
        tunnel = None
        remote_tmp = None
        remote_control = None
        sockpath = None
        if args.remote:
            # Start only a fresh UUID session. Existing remote sessions are untouched.
            remote_control = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', args.remote]
            setup = r"""import json, os, pathlib, subprocess, sys, tempfile, time
root = pathlib.Path(sys.argv[1])
session = sys.argv[2]
os.environ['PATH'] = str(pathlib.Path.home()/'.local/bin') + ':/opt/homebrew/bin:/usr/local/bin:' + os.environ['PATH']
for key in list(os.environ):
    if key.startswith('HERDR_'): del os.environ[key]
tmp = pathlib.Path(tempfile.mkdtemp(prefix='yazi-remote-smoke-'))
(tmp/'smoke-target.txt').write_text('remote file test\n')
(tmp/'render.py').write_text(sys.stdin.read())
subprocess.run([str(root/'.build/bin/herdr'), '--session', session, 'plugin', 'link', str(root)], check=True, stdout=subprocess.DEVNULL)
with (tmp/'server.log').open('wb') as log:
    subprocess.Popen([str(root/'.build/bin/herdr'), '--session', session, 'server'], stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, cwd=tmp)
sockets = []
for attempt in range(100):
    sockets = list((pathlib.Path.home()/'.config').glob('herdr*/sessions/'+session+'/herdr.sock'))
    if sockets: break
    time.sleep(0.1)
if len(sockets) != 1: raise RuntimeError('Cannot locate isolated remote socket: ' + repr(sockets))
print(json.dumps({'tmp': str(tmp), 'socket': str(sockets[0])}))
"""
            response = subprocess.run(remote_control + [shlex.join(['python3', '-c', setup, args.remote_root, session])],
                                      input=renderer.read_text(), text=True, stdout=subprocess.PIPE, check=True, timeout=40)
            info = json.loads(response.stdout)
            remote_tmp = info['tmp']
            target = Path(remote_tmp) / 'smoke-target.txt'
            remote_renderer = str(Path(remote_tmp) / 'render.py')
            sockpath = tmp / 'remote.sock'
            tunnel = subprocess.Popen(remote_control[:-1] + ['-o', 'ExitOnForwardFailure=yes', '-N',
                '-L', str(sockpath) + ':' + info['socket'], args.remote], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            until(lambda: sockpath.exists() or (tunnel.poll() is not None and (_ for _ in ()).throw(RuntimeError('SSH forwarding failed'))), 'SSH socket forward')
            cli += ['--remote', args.remote]
        else:
            subprocess.run(cli + ['plugin', 'link', str(args.plugin.resolve())], env=env, check=True,
                           stdout=subprocess.DEVNULL, timeout=15)
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 120, 0, 0))
        transcript = bytearray()
        def drain():
            try:
                while True:
                    chunk = os.read(master, 65536)
                    if not chunk:
                        break
                    transcript.extend(chunk)
                    if len(transcript) > 2_000_000:
                        del transcript[:1_000_000]
            except OSError:
                pass
        client = subprocess.Popen(cli + args.client_arg, env=env, cwd=fixture, stdin=slave, stdout=slave, stderr=slave,
                                  start_new_session=True)
        os.close(slave)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        stopped = False
        try:
            sockpath = sockpath or until(lambda: next((tmp / 'config').glob('herdr*/sessions/' + session + '/herdr.sock'), None), 'test socket')
            def api(method, params=None):
                with socket.socket(socket.AF_UNIX) as connection:
                    connection.settimeout(10)
                    connection.connect(str(sockpath))
                    connection.sendall((json.dumps({'id': 'smoke', 'method': method, 'params': params or {}}) + '\n').encode())
                    response = json.loads(connection.makefile('rb').readline(2_000_000))
                if 'error' in response:
                    raise RuntimeError(method + ': ' + str(response['error']))
                return response['result']
            panes = lambda: api('pane.list')['panes']
            source = until(lambda: panes(), 'initial pane')[0]['pane_id']
            text = lambda pane: api('pane.read', {'pane_id': pane, 'source': 'visible', 'format': 'text'})['read']['text']
            command = shlex.join(['python3', remote_renderer, str(target)]) if args.remote else shlex.join([sys.executable, str(renderer), str(target)])
            if args.remote:
                command = 'sh -c ' + shlex.quote('cd ' + shlex.quote(remote_tmp) + ' && exec ' + command)
            api('pane.send_input', {'pane_id': source, 'text': 'exec ' + command, 'keys': ['enter']})
            until(lambda: 'OSC_LINK' in text(source), 'fixture output')
            os.write(master, b'\x1b[I')
            time.sleep(0.3)
            for mode, label, should_open in [('osc', 'OSC_LINK', True),
                    ('relative', target.name, args.expect_paths),
                    ('absolute', str(target), args.expect_paths), ('missing', 'missing-file.txt', False)]:
                if mode != 'osc':
                    api('pane.send_input', {'pane_id': source, 'text': mode, 'keys': ['enter']})
                    until(lambda: label in text(source), mode + ' output')
                time.sleep(0.3)
                before_logs = len(api('plugin.log.list', {'plugin_id': 'local.yazi-links'})['logs'])
                # Fixed test geometry: 26-column sidebar, one tab row, a single unframed pane.
                # Real SGR Control+left press/release, not direct pane.link.activate.
                os.write(master, b'\x1b[<16;30;2M\x1b[<16;30;2m')
                if should_open:
                    opened = until(lambda: [p for p in panes() if p['pane_id'] != source], mode + ' Yazi pane')[0]
                    until(lambda: target.name in (text(opened['pane_id']).strip().splitlines() or [''])[-1], 'selected target in Yazi status line')
                    until(lambda: any(log.get('exit_code') == 0 for log in api('plugin.log.list', {'plugin_id': 'local.yazi-links'})['logs'][before_logs:]), 'successful plugin action')
                    api('pane.send_keys', {'pane_id': opened['pane_id'], 'keys': ['q']})
                    until(lambda: len(panes()) == 1, 'Yazi exit')
                else:
                    time.sleep(0.8)
                    if len(panes()) != 1:
                        raise RuntimeError(mode + ': unexpected pane opened')
                    if len(api('plugin.log.list', {'plugin_id': 'local.yazi-links'})['logs']) != before_logs:
                        raise RuntimeError(mode + ': unexpected plugin invocation')
                print('PASS ' + mode + (' opens Yazi' if should_open else ' does not open Yazi'), flush=True)
            print('PASS executable: ' + binary, flush=True)
            if args.remote:
                print('PASS remote host: ' + args.remote, flush=True)
        except Exception:
            sys.stderr.write(transcript.decode(errors='replace')[-2500:].replace('\x1b', '<ESC>') + '\n')
            raise
        finally:
            # Only our UUID-named server, with isolated configuration; never the user's session.
            try:
                if args.remote:
                    cleanup = 'import pathlib, shutil, subprocess, sys; root, session, tmp = sys.argv[1:]; subprocess.run([str(pathlib.Path(root)/".build/bin/herdr"), "--session", session, "server", "stop"], check=True); shutil.rmtree(tmp)'
                    subprocess.run(remote_control + [shlex.join(['python3', '-c', cleanup, args.remote_root, session, remote_tmp])], check=True, timeout=20, stdout=subprocess.DEVNULL)
                else:
                    subprocess.run(cli + ['server', 'stop'], env=env, check=True, timeout=10, stdout=subprocess.DEVNULL)
                stopped = True
            finally:
                try:
                    client.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    client.terminate()
                    client.wait(timeout=5)
                os.close(master)
                if tunnel is not None:
                    tunnel.terminate()
                    tunnel.wait(timeout=5)
            if not stopped:
                raise RuntimeError('Failed to stop isolated test server ' + session)


if __name__ == '__main__':
    main()
