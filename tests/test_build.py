"""Test that failed upstream upgrades never replace the working executable."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BuildSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copy(ROOT / 'build.sh', self.root / 'build.sh')
        for directory in ('tests', 'patches', 'scripts', 'tools', '.build/bin'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        (self.root / 'tests/test_fixture.py').write_text('import unittest\nclass Fixture(unittest.TestCase):\n    def test_fixture(self): pass\n')
        source = self.root / 'source'
        source.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(source), *args], stderr=subprocess.DEVNULL, text=True).strip()
        git('init', '-b', 'main')
        (source / 'demo.txt').write_text('before\n')
        git('add', 'demo.txt')
        git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'fixture')
        revision = git('rev-parse', 'HEAD')
        (source / 'demo.txt').write_text('after\n')
        patch = subprocess.check_output(['git', '-C', str(source), 'diff'])
        (self.root / 'patches/change.patch').write_bytes(patch)
        (source / 'demo.txt').write_text('before\n')
        self.source = self.root / '.build' / ('source-' + revision)
        source.rename(self.source)
        config = {'repository': 'invalid-unused-fixture', 'revision': revision, 'rust': 'test', 'zig': '0.16.0', 'patch': 'change.patch'}
        (self.root / 'patches/upstream.toml').write_text('\n'.join(f'{k} = {json.dumps(v)}' for k, v in config.items()))
        (self.root / 'scripts/smoke.py').write_text('import os,sys\nsys.exit(1 if os.environ.get("FAIL_STAGE") == "smoke" else 0)\n')
        self.executable = self.root / '.build/bin/herdr'
        self.executable.write_text('old binary')
        self.env = dict(os.environ)
        for key in ('CARGO_TARGET_DIR', 'HERDR_YAZI_BUILD_DIR', 'HERDR_YAZI_UPSTREAM_FILE', 'HERDR_YAZI_TOOLCHAIN'):
            self.env.pop(key, None)
        self.env['ZIG'] = str(self.root / 'tools/zig')
        self.env['PATH'] = str(self.root / 'tools') + os.pathsep + self.env['PATH']
        (self.root / 'tools/zig').write_text('#!/bin/sh\necho 0.16.0\n')
        (self.root / 'tools/cargo').write_text('''#!/bin/sh
set -eu
if [ "${FAIL_STAGE:-}" = "$2" ]; then exit 1; fi
if [ "$2" = build ]; then
    mkdir -p "$CARGO_TARGET_DIR/release"
    printf 'new binary' > "$CARGO_TARGET_DIR/release/herdr"
fi
''')
        for path in (self.root / 'tools').iterdir():
            path.chmod(0o755)

    def run_build(self, failure=None):
        env = dict(self.env)
        if failure:
            env['FAIL_STAGE'] = failure
        return subprocess.run(['bash', str(self.root / 'build.sh')], env=env, capture_output=True, text=True)

    def test_failed_tests_build_or_smoke_preserve_installed_binary(self):
        for failure in ('test', 'build', 'smoke'):
            with self.subTest(stage=failure):
                result = self.run_build(failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.executable.read_text(), 'old binary')

    def test_success_replaces_atomically_and_repeated_patch_is_accepted(self):
        with self.executable.open() as running_binary:
            result = self.run_build()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(running_binary.read(), 'old binary')
            self.assertEqual(self.executable.read_text(), 'new binary')
        self.assertEqual(self.run_build().returncode, 0)

    def test_incompatible_patch_preserves_installed_binary(self):
        (self.source / 'demo.txt').write_text('upstream incompatible change\n')
        result = self.run_build()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.executable.read_text(), 'old binary')


if __name__ == '__main__':
    unittest.main()
