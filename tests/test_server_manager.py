import importlib.util
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

def module(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

manager = module('server_manager', 'server-manager.py')
entry = module('herdr_entry', 'herdr-entry.py')

class ManagedServerTests(unittest.TestCase):
    def test_ssh_and_stale_pane_context_do_not_reach_server(self):
        env = manager.clean_environment({'SSH_CONNECTION': 'remote', 'SSH_AUTH_SOCK': '/ssh',
            'HERDR_SOCKET_PATH': '/other', 'HERDR_SESSION': 'other', 'XDG_SESSION_TYPE': 'tty',
            'XDG_SESSION_ID': '7', 'DISPLAY': ':0', 'PATH': '/bin', 'HOME': '/home/test'})
        self.assertEqual(env, {'DISPLAY': ':0', 'PATH': '/bin', 'HOME': '/home/test'})

    def test_desktop_requires_real_socket(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {'XDG_RUNTIME_DIR': temp, 'WAYLAND_DISPLAY': 'wayland-test'}
            self.assertFalse(manager.desktop_ready(env))
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(str(Path(temp) / 'wayland-test'))
                self.assertTrue(manager.desktop_ready(env))

    def test_start_routes_both_remote_bridge_and_local_attach(self):
        for args in [[], ['server'], ['remote-client-bridge'], ['--session', 'yazi-links'],
                     ['session', 'attach', 'yazi-links']]:
            self.assertEqual(entry.invocation(args, {'HERDR_SESSION': 'yazi-links'})[::2], ('yazi-links', True))
        for args in [['pane', 'list'], ['--remote', 'mac'], ['--help'], ['server', 'stop']]:
            self.assertFalse(entry.invocation(args, {})[2])
        self.assertEqual(entry.invocation(['--session=other', 'remote-client-bridge'], {})[0], 'other')

    def test_existing_unmanaged_server_is_never_stopped(self):
        class Result:
            def __init__(self, code): self.returncode = code
        with tempfile.NamedTemporaryFile() as marker, patch.object(manager, 'MARKER', Path(marker.name)), \
             patch.dict(os.environ, {'SSH_CONNECTION': 'remote'}), \
             patch.object(manager.subprocess, 'run', side_effect=[Result(0), Result(3)]) as run:
            manager.ensure()
            self.assertEqual(run.call_count, 2)
            self.assertFalse(any('stop' in str(call) for call in run.call_args_list))

    def test_missing_desktop_prevents_headless_server_start(self):
        with patch.object(manager, 'desktop_ready', return_value=False), patch.object(manager.os, 'execve') as execute:
            with self.assertRaisesRegex(RuntimeError, 'No local desktop'):
                manager.serve()
            execute.assert_not_called()

    def test_bridge_start_failure_never_falls_back_to_direct_spawn(self):
        import subprocess
        with patch.object(entry, 'ROOT', ROOT), \
             patch.object(Path, 'exists', return_value=True), \
             patch.object(entry.sys, 'argv', ['herdr', '--session', 'yazi-links', 'remote-client-bridge']), \
             patch.object(entry.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['ensure'])), \
             patch.object(entry.os, 'execve') as execute:
            with self.assertRaises(subprocess.CalledProcessError):
                entry.main()
            execute.assert_not_called()

    def test_upstream_update_cannot_overwrite_managed_binary(self):
        with patch.object(Path, 'exists', return_value=True), \
             patch.object(entry.sys, 'argv', ['herdr', 'update']), \
             patch.object(entry.os, 'execve') as execute:
            with self.assertRaisesRegex(SystemExit, 'tested build/install'):
                entry.main()
            execute.assert_not_called()

    def test_install_is_repeatable_and_preserves_existing_entry(self):
        installer = module('install_server', 'install-server.py')
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.build').mkdir()
            (home / '.local/bin').mkdir(parents=True)
            (home / '.local/bin/herdr').write_text('existing executable')
            (home / '.zshenv').write_text('# existing config\n')
            with patch.object(installer, 'ROOT', home), patch.object(Path, 'home', return_value=home), \
                 patch.dict(os.environ, {'SHELL': '/bin/zsh'}), patch.object(installer.subprocess, 'run') as run:
                installer.install()
                installer.install()
            self.assertEqual((home / '.zshenv').read_text().count('# herdr-yazi-links managed entry'), 1)
            backups = list((home / '.local/bin').glob('herdr.before-yazi-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), 'existing executable')
            self.assertTrue((home / '.local/bin/herdr').is_symlink())
            self.assertFalse(any('stop' in str(call) or 'restart' in str(call) for call in run.call_args_list))
