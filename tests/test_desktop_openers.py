"""Run both installed opener entry points with a controlled desktop API helper."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OpenerTests(unittest.TestCase):
    def run_opener(self, name, paths, response, statuses=()):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "desktop-bin").mkdir()
            opener = root / "desktop-bin" / name
            shutil.copy2(ROOT / "desktop-bin" / name, opener)
            log = root / "calls.jsonl"
            (root / "drag.py").write_text("""import json,os
from pathlib import Path
def record(value):
 with open(os.environ['OPEN_LOG'],'a') as f: f.write(json.dumps(value)+'\\n')
def submit(paths, action):
 record({'paths':paths,'action':action})
 return json.loads(os.environ['OPEN_RESULT'])
def watch(job, session):
 record({'job':job,'session':session})
 yield from json.loads(os.environ['OPEN_STATUSES'])
""")
            env = dict(
                os.environ,
                OPEN_LOG=str(log),
                OPEN_RESULT=json.dumps(response),
                OPEN_STATUSES=json.dumps(statuses),
            )
            result = subprocess.run(
                [sys.executable, str(opener), *paths],
                env=env,
                capture_output=True,
                text=True,
                timeout=5,
            )
            calls = (
                [json.loads(line) for line in log.read_text().splitlines()]
                if log.exists()
                else []
            )
            return result, calls

    def test_local_open_passes_literal_paths_and_does_not_watch(self):
        paths = ["/a b", "/雪;$(touch NEVER)\n.txt"]
        for name in ("open", "xdg-open"):
            with self.subTest(opener=name):
                result, calls = self.run_opener(name, paths, {"message": "Opened"})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, [{"paths": paths, "action": "open"}])

    def test_remote_open_watches_the_response_scope_not_inherited_session(self):
        for name in ("open", "xdg-open"):
            with self.subTest(opener=name):
                result, calls = self.run_opener(
                    name,
                    ["/file"],
                    {"id": "job", "scope": "work@client"},
                    [{"state": "queued"}, {"state": "done"}],
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls[-1], {"job": "job", "session": "work@client"})

    def test_remote_errors_and_cancellation_are_not_reported_as_success(self):
        for state in ("error", "cancelled"):
            for name in ("open", "xdg-open"):
                with self.subTest(state=state, opener=name):
                    result, _ = self.run_opener(
                        name,
                        ["/file"],
                        {"id": "job", "scope": "work@client"},
                        [{"state": state, "message": "receiver unavailable"}],
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("receiver unavailable", result.stderr)

    def test_missing_file_does_not_request_a_desktop_operation(self):
        for name in ("open", "xdg-open"):
            result, calls = self.run_opener(name, [], {})
            self.assertEqual(result.returncode, 1)
            self.assertEqual(calls, [])
