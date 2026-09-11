import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'scripts').mkdir()
        shutil.copy2(ROOT / 'herdr-yazi', self.root / 'herdr-yazi')
        shutil.copy2(ROOT / 'scripts/launch.py', self.root / 'scripts/launch.py')
        (self.root / '.build/bin').mkdir(parents=True)
        (self.root / '.local/bin').mkdir(parents=True)
        helper = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps({'argv': [os.path.basename(sys.argv[0]), *sys.argv[1:]], 'session': os.environ.get('HERDR_SESSION'), 'socket': os.environ.get('HERDR_SOCKET_PATH'), 'pane': os.environ.get('HERDR_PANE_ID'), 'path': os.environ.get('PATH')}) + '\\n')
if os.path.basename(sys.argv[0]) == 'ssh':
    sys.exit(int(os.environ.get('SSH_EXIT', '0')))
sys.exit(int(os.environ.get('HERDR_EXIT', '0')))
'''
        for path in [self.root / '.build/bin/herdr', self.root / '.local/bin/ssh']:
            path.write_text(helper)
            path.chmod(0o755)
        self.log = self.root / 'calls.jsonl'
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('HERDR_')}
        self.env.update(HOME=str(self.root), CALL_LOG=str(self.log), PATH=str(self.root / '.local/bin') + os.pathsep + os.environ['PATH'])

    def run_launcher(self, args):
        self.log.write_text('')
        result = subprocess.run([str(self.root / 'herdr-yazi'), *args], env=self.env, capture_output=True)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return result, calls

    def test_all_remote_options_reach_herdr_unchanged(self):
        cases = [
            ['--remote', 'my-mac-m1', '--remote-keybindings', 'server'],
            ['--remote-keybindings=server', '--remote=my-mac-m1', '--session=work'],
            ['--session', 'work', '--remote', 'host;touch unintended', '--future-option', 'a b'],
            ['--remote', 'host', '--', '--remote', 'not-a-host', '--session', 'not-a-session'],
        ]
        for args in cases:
            with self.subTest(args=args):
                result, calls = self.run_launcher(args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[-1]['argv'], ['herdr', *args])
                self.assertEqual(calls[-1]['session'], 'yazi-links')
        self.assertEqual(calls[0]['argv'], ['ssh', '--', 'host', 'exec "$HOME/pets/herdr-yazi-links/scripts/prepare.sh" yazi-links'])

    def test_explicit_session_is_prepared_and_shell_quoted(self):
        name = "work';touch unintended"
        result, calls = self.run_launcher(['--remote', 'host', '--session', name])
        self.assertEqual(result.returncode, 0)
        import shlex
        self.assertEqual(calls[0]['argv'][-1], 'exec "$HOME/pets/herdr-yazi-links/scripts/prepare.sh" ' + shlex.quote(name))

    def test_local_commands_help_and_malformed_args_have_no_setup_side_effects(self):
        for args in [[], ['--help'], ['session', 'attach', 'work'],
                     ['--remote', 'host', '--help'], ['--remote'],
                     ['--', '--remote', 'literal'], ['--new-upstream-option', 'value']]:
            with self.subTest(args=args):
                result, calls = self.run_launcher(args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual([call['argv'] for call in calls], [['herdr', *args]])

    def test_pane_commands_keep_the_callers_socket_and_ids(self):
        self.env.update(HERDR_SOCKET_PATH='/tmp/owned.sock', HERDR_ENV='1',
                        HERDR_PANE_ID='w3:p8', HERDR_SESSION='existing')
        for args in [['pane', 'current', '--current'], ['agent', 'list'],
                     ['--session', 'other', 'pane', 'list']]:
            result, calls = self.run_launcher(args)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(calls[-1]['socket'], '/tmp/owned.sock')
            self.assertEqual(calls[-1]['pane'], 'w3:p8')
            self.assertEqual(calls[-1]['session'], 'existing')
        _, calls = self.run_launcher([])
        self.assertIsNone(calls[-1]['socket'])
        self.assertIsNone(calls[-1]['pane'])
        self.assertEqual(calls[-1]['session'], 'yazi-links')
        _, calls = self.run_launcher(['--remote', 'host', '--future', 'value'])
        self.assertIsNone(calls[-1]['socket'])
        self.assertIsNone(calls[-1]['pane'])

    def test_explicit_environment_session_and_path_priority_are_preserved(self):
        self.env['HERDR_SESSION'] = 'chosen'
        _, calls = self.run_launcher(['status'])
        self.assertEqual(calls[-1]['session'], 'chosen')
        self.assertTrue(calls[-1]['path'].startswith(self.env['PATH']))

    def test_informational_and_duplicate_remote_flags_do_not_prepare(self):
        for args in [['--remote', 'host', '--skill'], ['--remote', 'host', '--default-config'],
                     ['--remote', 'one', '--remote', 'two'], ['pane', 'list', '--remote', 'host']]:
            _, calls = self.run_launcher(args)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]['argv'], ['herdr', *args])

    def test_exit_status_is_preserved(self):
        self.env['SSH_EXIT'] = '19'
        result, calls = self.run_launcher(['--remote', 'host'])
        self.assertEqual(result.returncode, 19)
        self.assertEqual(len(calls), 1)
        self.env['HERDR_EXIT'] = '23'
        result, _ = self.run_launcher(['--unknown'])
        self.assertEqual(result.returncode, 23)
