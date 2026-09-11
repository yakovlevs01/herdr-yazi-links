import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def test_remote_prepares_remote_host_without_local_plugin_registration(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copy2(ROOT / 'herdr-yazi', root / 'herdr-yazi')
            (root / '.build/bin').mkdir(parents=True)
            (root / '.local/bin').mkdir(parents=True)
            helper = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(json.dumps([os.path.basename(sys.argv[0]), *sys.argv[1:]]) + '\\n')
if os.path.basename(sys.argv[0]) == 'ssh':
    sys.exit(int(os.environ.get('SSH_EXIT', '0')))
'''
            for path in [root / '.build/bin/herdr', root / '.local/bin/ssh']:
                path.write_text(helper)
                path.chmod(0o755)
            log = root / 'calls.jsonl'
            env = dict(os.environ, HOME=str(root), CALL_LOG=str(log))
            host = 'host;touch unintended'
            result = subprocess.run([str(root / 'herdr-yazi'), '--remote', host], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(calls[0], ['ssh', '--', host, 'exec "$HOME/pets/herdr-yazi-links/herdr-yazi" --prepare'])
            self.assertEqual(calls[1], ['herdr', '--session', 'yazi-links', '--remote', host])
            log.write_text('')
            env['SSH_EXIT'] = '19'
            result = subprocess.run([str(root / 'herdr-yazi'), '--remote', host], env=env, capture_output=True)
            self.assertEqual(result.returncode, 19)
            self.assertEqual(len(log.read_text().splitlines()), 1)
