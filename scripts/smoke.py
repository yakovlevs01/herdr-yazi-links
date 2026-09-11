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
    args = parser.parse_args()
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
        client = subprocess.Popen(cli, env=env, cwd=fixture, stdin=slave, stdout=slave, stderr=slave,
                                  start_new_session=True)
        os.close(slave)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        stopped = False
        try:
            sockpath = until(lambda: next((tmp / 'config').glob('herdr*/sessions/' + session + '/herdr.sock'), None), 'test socket')
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
            command = shlex.join([sys.executable, str(renderer), str(target)])
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
        except Exception:
            sys.stderr.write(transcript.decode(errors='replace')[-2500:].replace('\x1b', '<ESC>') + '\n')
            raise
        finally:
            # Only our UUID-named server, with isolated configuration; never the user's session.
            try:
                subprocess.run(cli + ['server', 'stop'], env=env, check=True, timeout=10,
                               stdout=subprocess.DEVNULL)
                stopped = True
            finally:
                try:
                    client.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    client.terminate()
                    client.wait(timeout=5)
                os.close(master)
            if not stopped:
                raise RuntimeError('Failed to stop isolated test server ' + session)


if __name__ == '__main__':
    main()
