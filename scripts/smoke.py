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
    parser.add_argument('--handoff-to', type=Path, help='Hand off the isolated local server to this binary before click checks')
    parser.add_argument('--expect-paths', action='store_true', help='Require the plain-text path patch')
    parser.add_argument('--expect-home-paths', action='store_true', help='Require ~/ path expansion in a local test')
    parser.add_argument('--expect-client-context', choices=('local', 'ssh'),
                        help='Test Enter opener environment against a separately started stale server')
    parser.add_argument('--plugin', type=Path, default=ROOT)
    parser.add_argument('--remote', help='SSH host with the plugin and patched Herdr installed')
    parser.add_argument('--remote-root', help='Absolute plugin checkout path on the SSH host')
    parser.add_argument('--expect-selection-copy', action='store_true',
                        help='Select text with real mouse input and require a client-local clipboard write')
    parser.add_argument('--saved-machine', action='store_true',
                        help='Exercise the remote through an isolated saved-machine profile')
    parser.add_argument('--client-arg', action='append', default=[], help='Extra client argument, repeatable; use --client-arg=--flag')
    args = parser.parse_args()
    if args.saved_machine and not args.remote:
        parser.error('--saved-machine requires --remote')
    if args.handoff_to and args.remote:
        parser.error('--handoff-to currently requires a local test')
    if args.expect_home_paths and args.remote:
        parser.error('--expect-home-paths currently requires a local test')
    if args.expect_client_context and args.remote:
        parser.error('--expect-client-context uses an isolated local server')
    if bool(args.remote) != bool(args.remote_root):
        parser.error('--remote and --remote-root must be supplied together')
    if not (sys.platform.startswith('linux') or sys.platform == 'darwin'):
        parser.error('The automated PTY smoke test supports Linux and macOS.')
    binary = shutil.which(args.herdr)
    if not binary:
        parser.error('Herdr executable not found: ' + args.herdr)
    binary = str(Path(binary).resolve())
    if not shutil.which('yazi'):
        parser.error('yazi must be installed in PATH')
    # macOS's default per-user TMPDIR exceeds the Unix socket path limit here.
    with tempfile.TemporaryDirectory(prefix='yazi-smoke-', dir='/tmp' if sys.platform == 'darwin' else None) as temporary:
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
        if not args.remote:
            env['HOME'] = str(tmp)
        target = fixture / 'smoke-target.txt'
        target.write_text('Yazi file link smoke test\n')
        clipboard_log = tmp / 'clipboard.jsonl'
        if args.expect_selection_copy:
            # Native tools are recorders: never replace the user's real clipboard.
            bindir = tmp / 'bin'
            bindir.mkdir()
            recorder = ('#!' + sys.executable + '\nimport json,os,sys\n'
                        + 'with open(' + repr(str(clipboard_log)) + ', "a") as f:\n'
                        + ' f.write(json.dumps({"parent":os.getppid(),"text":sys.stdin.read()})+"\\n")\n')
            for name in ('wl-copy', 'xclip', 'xsel', 'pbcopy'):
                tool = bindir / name
                tool.write_text(recorder)
                tool.chmod(0o755)
            for key in list(env):
                if key.startswith('SSH_') or key in ('VSCODE_IPC_HOOK_CLI', 'WSL_DISTRO_NAME', 'WSL_INTEROP'):
                    env.pop(key)
            env.update(PATH=str(bindir) + ':' + env['PATH'], WAYLAND_DISPLAY='selection-test')
        desktop_keys = ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR',
                        'DBUS_SESSION_BUS_ADDRESS', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE')
        opener_output = tmp / 'opener-env.json'
        if args.expect_client_context:
            # Real Yazi Enter invokes this harmless opener instead of a browser.
            probe = tmp / 'opener.py'
            probe.write_text('import json, os, pathlib, sys\n'
                             + 'pathlib.Path(' + repr(str(opener_output)) + ').write_text(json.dumps({'
                             + '"env": {key: os.environ.get(key) for key in ' + repr(desktop_keys) + '},'
                             + '"file": sys.argv[1]}))\n')
            yazi_config = tmp / 'config/yazi'
            yazi_config.mkdir()
            opener = shlex.join([sys.executable, str(probe)]) + ' %s'
            (yazi_config / 'yazi.toml').write_text('[opener]\nprobe = [{ run = '
                + json.dumps(opener) + ', orphan = true }]\n[open]\nrules = [{ url = "*", use = "probe" }]\n')
        renderer = tmp / 'render.py'
        renderer.write_text('''import os
import sys
from pathlib import Path
p = Path(sys.argv[1])
mode = "osc"
while True:
    text = {"osc": "\\x1b]8;;" + p.as_uri() + "\\x1b\\\\OSC_LINK\\x1b]8;;\\x1b\\\\",
            "relative": p.name, "absolute": str(p), "home": "~/" + os.path.relpath(p, Path.home()),
            "home_missing": "~/missing-file.txt", "missing": "missing-file.txt"}[mode]
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
            if args.saved_machine:
                profile = uuid.uuid4().hex
                catalog = tmp / 'state/herdr/client'
                catalog.mkdir(parents=True)
                (catalog / 'endpoints.json').write_text(json.dumps({
                    'version': 1, 'selected_profile': profile, 'ssh': [{
                        'id': profile, 'label': 'Selection test', 'target': args.remote,
                        'session': session, 'enabled': True}]}))
                (catalog / 'endpoint-selection.json').write_text(json.dumps({
                    'version': 1, 'selected_profile': profile}))
            else:
                cli += ['--remote', args.remote]
        else:
            subprocess.run(cli + ['plugin', 'link', str(args.plugin.resolve())], env=env, check=True,
                           stdout=subprocess.DEVNULL, timeout=15)
            if args.expect_client_context:
                server_env = dict(env)
                server_env.update({key: 'stale-server-value' for key in desktop_keys})
                server_env['SSH_CONNECTION'] = 'old-server-ssh'
                with (tmp / 'server.log').open('wb') as log:
                    subprocess.Popen(cli + ['server'], env=server_env, cwd=fixture,
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True)
                sockpath = until(lambda: next((tmp / 'config').glob('herdr*/sessions/' + session + '/herdr.sock'), None), 'stale test server')
                for key in list(env):
                    if key.startswith('SSH_') or key in desktop_keys:
                        env.pop(key)
                env.update(DISPLAY=':client-test', WAYLAND_DISPLAY='wayland-client-test',
                           XDG_SESSION_TYPE='wayland')
                if args.expect_client_context == 'ssh':
                    env['SSH_CONNECTION'] = 'current-ssh-client'
        master, slave = pty.openpty()
        slave_name = os.ttyname(slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 200, 0, 0))
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
            else:
                command = 'sh -c ' + shlex.quote('cd ' + shlex.quote(str(fixture)) + ' && exec ' + command)
            api('pane.send_input', {'pane_id': source, 'text': 'exec ' + command, 'keys': ['enter']})
            until(lambda: 'OSC_LINK' in text(source), 'fixture output')
            if args.handoff_to:
                before = api('pane.process_info', {'pane_id': source})['process_info']
                subprocess.run(cli + ['server', 'live-handoff', '--import-exe', str(args.handoff_to.resolve())],
                               env=env, check=True, timeout=40)
                after = api('pane.process_info', {'pane_id': source})['process_info']
                for key in ('pane_id', 'shell_pid', 'foreground_process_group_id'):
                    if before[key] != after[key]:
                        raise RuntimeError('Handoff changed ' + key)
                until(lambda: 'OSC_LINK' in text(source), 'renderer preserved after handoff')
                # Herdr deliberately disconnects the old client during handoff.
                client.wait(timeout=10)
                reader.join(timeout=2)
                slave = os.open(slave_name, os.O_RDWR | os.O_NOCTTY)
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, 200, 0, 0))
                client = subprocess.Popen([str(args.handoff_to.resolve()), '--session', session, *args.client_arg],
                                          env=env, cwd=fixture, stdin=slave, stdout=slave, stderr=slave,
                                          start_new_session=True)
                os.close(slave)
                reader = threading.Thread(target=drain, daemon=True)
                reader.start()
                time.sleep(1)
                api('pane.send_input', {'pane_id': source, 'text': 'osc', 'keys': ['enter']})
                until(lambda: 'OSC_LINK' in text(source), 'renderer redraw after reconnect')
                print('PASS live handoff preserves pane and process IDs; new client reconnects', flush=True)
            os.write(master, b'\x1b[I')
            time.sleep(0.3)
            if args.expect_selection_copy:
                # The configured sidebar occupies 26 columns; pane starts at 27.
                # Select OSC_LINK by dragging, without Control/link activation.
                os.write(master, b'\x1b[<0;27;2M\x1b[<32;34;2M\x1b[<0;34;2m')
                until(lambda: clipboard_log.exists() and clipboard_log.read_text().endswith('\n'),
                      'client-local selection clipboard write')
                copies = [json.loads(line) for line in clipboard_log.read_text().splitlines()]
                # --remote launches a child client after setting up SSH. Saved
                # machines run the client in the original process.
                writer = copies[-1]['parent']
                ancestry = set()
                while writer > 1 and writer not in ancestry and writer != client.pid:
                    ancestry.add(writer)
                    parent = subprocess.check_output(['ps', '-p', str(writer), '-o', 'ppid='], text=True).strip()
                    writer = int(parent) if parent else 0
                if writer != client.pid or copies[-1]['text'] != 'OSC_LINK':
                    raise RuntimeError('Selection copied by wrong process or wrong text: ' + repr(copies))
                print('PASS mouse selection copies remote/local text in the client process', flush=True)
            cases = [('osc', 'OSC_LINK', True),
                     ('relative', target.name, args.expect_paths),
                     ('absolute', str(target), args.expect_paths)]
            if args.expect_home_paths:
                cases += [('home', '~/fixture/' + target.name, True),
                          ('home_missing', '~/missing-file.txt', False)]
            cases.append(('missing', 'missing-file.txt', False))
            for mode, label, should_open in cases:
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
                    if args.expect_client_context:
                        opener_output.unlink(missing_ok=True)
                        api('pane.send_keys', {'pane_id': opened['pane_id'], 'keys': ['enter']})
                        until(opener_output.exists, 'Enter invokes configured opener')
                        actual = json.loads(opener_output.read_text())
                        expected = {key: env.get(key) if args.expect_client_context == 'local' else None
                                    for key in desktop_keys}
                        if actual['env'] != expected or Path(actual['file']).name != target.name:
                            raise RuntimeError('Opener received wrong environment/file: ' + repr(actual))
                        print('PASS Enter uses ' + args.expect_client_context + ' client context, no stale server desktop', flush=True)
                    api('pane.send_keys', {'pane_id': opened['pane_id'], 'keys': ['q']})
                    until(lambda: len(panes()) == 1, 'Yazi exit')
                else:
                    time.sleep(0.8)
                    if len(panes()) != 1:
                        raise RuntimeError(mode + ': unexpected pane opened')
                    if len(api('plugin.log.list', {'plugin_id': 'local.yazi-links'})['logs']) != before_logs:
                        raise RuntimeError(mode + ': unexpected plugin invocation')
                print('PASS ' + mode + (' opens Yazi' if should_open else ' does not open Yazi'), flush=True)
            print('PASS executable: ' + str(args.handoff_to.resolve() if args.handoff_to else binary), flush=True)
            if args.remote:
                print('PASS remote host: ' + args.remote, flush=True)
        except Exception:
            try:
                for pane in panes():
                    sys.stderr.write('Pane ' + pane['pane_id'] + ':\n' + text(pane['pane_id']) + '\n')
            except Exception:
                pass
            sys.stderr.write(transcript.decode(errors='replace')[-2500:].replace('\x1b', '<ESC>') + '\n')
            raise
        finally:
            # Only our UUID-named server, with isolated configuration; never the user's session.
            try:
                if args.remote:
                    if args.saved_machine:
                        # Stop our client first so it cannot restart its test endpoint.
                        client.terminate()
                        client.wait(timeout=5)
                        subprocess.run(cli + ['server', 'stop'], env=env, check=True,
                                       timeout=10, stdout=subprocess.DEVNULL)
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
