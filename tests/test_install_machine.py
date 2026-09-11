import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('install_machine', ROOT / 'scripts/install-machine.py')
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


class MachineInstallerTests(unittest.TestCase):
    def test_checkout_alias_is_created_without_replacing_other_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / 'source'
            root.mkdir()
            with patch.object(INSTALL.Path, 'home', return_value=home):
                INSTALL.configure_checkout(root)
                INSTALL.configure_checkout(root)
                self.assertEqual((home / 'pets/herdr-yazi-links').resolve(), root)
                another = home / 'another'
                another.mkdir()
                with self.assertRaisesRegex(ValueError, 'Another checkout'):
                    INSTALL.configure_checkout(another)
            self.assertEqual((home / 'pets/herdr-yazi-links').resolve(), root)

    def test_yazi_compatibility_rejects_old_and_future_api(self):
        with patch.object(INSTALL.shutil, 'which', return_value='/bin/yazi'):
            for version, expected in [('26.1.22', False), ('26.5.6', True), ('26.9.1', True), ('27.1.1', False)]:
                with self.subTest(version=version), patch.object(INSTALL.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Yazi ' + version)):
                    self.assertEqual(INSTALL.compatible_yazi(), expected)

    def test_invalid_options_fail_before_bootstrap(self):
        result = subprocess.run(['sh', str(ROOT / 'install.sh'), '--not-an-option'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Unknown option', result.stderr)

    def test_supported_platforms_are_explicit(self):
        self.assertEqual(INSTALL.target('Linux', 'x86_64'), 'linux-x86_64')
        self.assertEqual(INSTALL.target('Darwin', 'arm64'), 'macos-aarch64')
        with self.assertRaises(ValueError):
            INSTALL.target('Linux', 'aarch64')

    def test_pinned_download_failure_preserves_previous_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / 'remote'
            remote.write_bytes(b'incomplete or wrong binary')
            installed = root / 'installed'
            installed.write_bytes(b'previous working binary')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                INSTALL.fetch(remote.as_uri(), installed, '0' * 64)
            self.assertEqual(installed.read_bytes(), b'previous working binary')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ['installed', 'remote'])

    def test_verified_download_and_repeated_install_reuse_binary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'asset'
            source.write_bytes(b'new binary')
            manifest = {'herdr': {'linux-x86_64': {'url': source.as_uri(), 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}}}
            with patch.object(INSTALL, 'run'):
                binary = INSTALL.install_herdr(root, manifest, 'linux-x86_64')
            self.assertEqual(binary.read_bytes(), b'new binary')
            with patch.object(INSTALL, 'run'), patch.object(INSTALL, 'fetch') as fetch:
                INSTALL.install_herdr(root, manifest, 'linux-x86_64')
                fetch.assert_not_called()

    def test_shell_config_is_idempotent_and_appends_path(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            profile = home / '.zshrc'
            original = 'export PATH="/my/custom/bin:$PATH"\n# user configuration\n'
            profile.write_text(original)
            with patch.dict(os.environ, {'SHELL': '/bin/zsh'}):
                INSTALL.configure_path(home)
                once = profile.read_text()
                INSTALL.configure_path(home)
            self.assertTrue(once.startswith(original))
            self.assertIn('export PATH="$PATH:$HOME/.local/bin"', once)
            self.assertEqual(profile.read_text(), once)
            backups = list(home.glob('.zshrc.herdr-yazi-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)

    def test_launcher_replacement_preserves_user_file_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launcher = root / 'launcher'
            launcher.write_text('user file')
            target = root / 'target'
            target.write_text('target')
            INSTALL.link(launcher, target)
            INSTALL.link(launcher, target)
            self.assertEqual(launcher.resolve(), target)
            backups = list(root.glob('launcher.herdr-yazi-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), 'user file')

    def test_manifest_checksums_and_release_pins(self):
        manifest = json.loads((ROOT / 'install-assets.json').read_text())
        for component, platforms in manifest.items():
            self.assertEqual(set(platforms), {'linux-x86_64', 'macos-aarch64'})
            for entry in platforms.values():
                self.assertRegex(entry['sha256'], r'^[a-f0-9]{64}$')
                self.assertTrue(entry['url'].startswith('https://github.com/'))
                self.assertNotIn('/latest/', entry['url'])

    def test_help_is_available_without_package_installs(self):
        result = subprocess.run(['sh', str(ROOT / 'install.sh'), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--sender-only', result.stdout)

    def test_sender_only_skips_receiver_and_does_not_start_server(self):
        with patch.object(INSTALL, 'ROOT', ROOT), patch.object(INSTALL, 'target', return_value='linux-x86_64'), \
             patch.object(INSTALL.os, 'geteuid', return_value=1000), patch.object(INSTALL, 'install_yazi'), \
             patch.object(INSTALL, 'install_herdr', return_value=Path('/pinned/herdr')), \
             patch.object(INSTALL, 'install_receiver') as receiver, patch.object(INSTALL, 'link'), \
             patch.object(INSTALL, 'configure_path'), patch.object(INSTALL, 'configure_checkout'), patch.object(INSTALL, 'run') as run, \
             patch.object(INSTALL, 'check', return_value=True), patch.object(INSTALL.shutil, 'which', return_value='/bin/ssh'), \
             patch.object(INSTALL.sys, 'argv', ['install-machine.py', '--sender-only']):
            self.assertEqual(INSTALL.main(), 0)
        receiver.assert_not_called()
        commands = [list(map(str, call.args[0])) for call in run.call_args_list]
        self.assertIn(['/pinned/herdr', '--session', 'yazi-links', 'plugin', 'link', str(ROOT)], commands)
        self.assertFalse(any('server' in command or 'update' in command for command in commands))

    def test_check_does_not_mutate_installation(self):
        with patch.object(INSTALL, 'target', return_value='linux-x86_64'), \
             patch.object(INSTALL, 'check', return_value=False), patch.object(INSTALL, 'install_herdr') as installer, \
             patch.object(INSTALL, 'packages') as packages, patch.object(INSTALL, 'link') as link, \
             patch.object(INSTALL.sys, 'argv', ['install-machine.py', '--check']):
            self.assertEqual(INSTALL.main(), 1)
        installer.assert_not_called()
        packages.assert_not_called()
        link.assert_not_called()

    def test_shell_symlink_backup_keeps_original_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            target = home / 'dotfiles-zshrc'
            original = 'export PATH="/custom/bin:$PATH"\n'
            target.write_text(original)
            (home / '.zshrc').symlink_to(target)
            INSTALL.configure_path(home)
            saved = list(home.glob('.zshrc.herdr-yazi-backup-*'))
            self.assertEqual(len(saved), 1)
            self.assertFalse(saved[0].is_symlink())
            self.assertEqual(saved[0].read_text(), original)
            self.assertTrue((home / '.zshrc').is_symlink())
