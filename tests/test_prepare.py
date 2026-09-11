import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(hasattr(os, 'getsid'), 'Unix session IDs required')
class PrepareTests(unittest.TestCase):
    def test_server_detaches_and_existing_server_is_not_restarted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'scripts').mkdir()
            (root / '.build/bin').mkdir(parents=True)
            shutil.copy2(ROOT / 'scripts/prepare.sh', root / 'scripts/prepare.sh')
            executable = root / '.build/bin/herdr'
            executable.write_text('#!' + sys.executable + '''
import json, os, pathlib, sys
marker = pathlib.Path(os.environ['TEST_SERVER_MARKER'])
command = sys.argv[3:]
if command == ['pane', 'list']:
    sys.exit(0 if marker.exists() else 1)
if command == ['server']:
    marker.write_text(json.dumps({'pid': os.getpid(), 'sid': os.getsid(0)}))
''')
            executable.chmod(0o755)
            marker = root / 'server.json'
            env = dict(os.environ, TEST_SERVER_MARKER=str(marker))
            subprocess.run([str(root / 'scripts/prepare.sh'), 'test-session'], env=env, check=True, timeout=10)
            state = json.loads(marker.read_text())
            self.assertEqual(state['pid'], state['sid'])
            subprocess.run([str(root / 'scripts/prepare.sh'), 'test-session'], env=env, check=True, timeout=10)
            self.assertEqual(json.loads(marker.read_text()), state)
