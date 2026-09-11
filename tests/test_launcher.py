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
    log.write(json.dumps({'argv': [os.path.basename(sys.argv[0]), *sys.argv[1:]], 'session': os.environ.get('HERDR_SESSION')}) + '\\n')
if os.path.basename(sys.argv[0]) == 'ssh':
    sys.exit(int(os.environ.get('SSH_EXIT', '0')))
sys.exit(int(os.environ.get('HERDR_EXIT', '0')))
'''
        for path in [self.root / '.build/bin/herdr', self.root / '.local/bin/ssh']:
            path.write_text(helper)
            path.chmod(0o755)
        self.log = self.root / 'calls.jsonl'
        self.env = dict(os.environ, HOME=str(self.root), CALL_LOG=str(self.log))

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

    def test_exit_status_is_preserved(self):
        self.env['SSH_EXIT'] = '19'
        result, calls = self.run_launcher(['--remote', 'host'])
        self.assertEqual(result.returncode, 19)
        self.assertEqual(len(calls), 1)
        self.env['HERDR_EXIT'] = '23'
        result, _ = self.run_launcher(['--unknown'])
        self.assertEqual(result.returncode, 23)
