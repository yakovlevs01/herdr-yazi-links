import contextlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('drag_transfer', ROOT / 'scripts/drag_transfer.py')
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


def attrs(size, mode=stat.S_IFREG | 0o644, mtime=100):
    return SimpleNamespace(st_size=size, st_mode=mode, st_mtime=mtime)


class RemoteFile(io.BytesIO):
    def __init__(self, data, metadata):
        super().__init__(data)
        self.metadata = metadata

    def stat(self):
        return self.metadata


class FakeSFTP:
    def __init__(self, files):
        self.files = files
        self.modes = {}
        self.sizes = {}
        self.opened = []
        self.error = None

    def lstat(self, path):
        return attrs(self.sizes.get(path, len(self.files[path])), self.modes.get(path, stat.S_IFREG | 0o644))

    def open(self, path, mode):
        self.opened.append(path)
        if self.error:
            raise self.error
        return RemoteFile(self.files[path], self.lstat(path))


class TransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / 'cache'

    def download(self, fake, paths, progress=None):
        with patch.object(transfer, 'open_sftp', return_value=contextlib.nullcontext(fake)):
            return transfer.download('my-host', paths, self.cache, progress)

    def test_special_names_duplicates_empty_file_and_progress(self):
        names = ['/one/a \"\' $`*?;\n雪.txt', '/two/a \"\' $`*?;\n雪.txt', '/empty']
        fake = FakeSFTP(dict(zip(names, [b'first', b'second', b''])))
        progress = []
        result = self.download(fake, names, lambda *args: progress.append(args))
        self.assertEqual([p.read_bytes() for p in result], [b'first', b'second', b''])
        self.assertNotEqual(result[0], result[1])
        self.assertEqual(result[0].name, result[1].name)
        self.assertEqual(progress[-1], ('/empty', 0, 0))
        self.assertEqual(fake.opened, names)
        self.assertEqual(list(self.cache.glob('.partial-*')), [])
        self.assertTrue((result[0].parents[1] / '.complete').exists())
        self.assertEqual(stat.S_IMODE(result[0].stat().st_mode), 0o600)

    def test_directory_symlink_fifo_rejected_before_open(self):
        for mode in [stat.S_IFDIR, stat.S_IFLNK, stat.S_IFIFO]:
            with self.subTest(mode=mode):
                fake = FakeSFTP({'/file': b'content'})
                fake.modes['/file'] = mode
                with self.assertRaisesRegex(transfer.TransferError, 'regular files'):
                    self.download(fake, ['/file'])
                self.assertEqual(fake.opened, [])
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_failed_second_file_removes_entire_batch(self):
        fake = FakeSFTP({'/one': b'first', '/two': b'short'})
        fake.sizes['/two'] = 10
        with self.assertRaisesRegex(transfer.TransferError, 'incomplete'):
            self.download(fake, ['/one', '/two'])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_permission_failure_and_growing_file(self):
        fake = FakeSFTP({'/file': b'content'})
        fake.error = PermissionError('denied')
        with self.assertRaises(PermissionError):
            self.download(fake, ['/file'])
        self.assertEqual(list(self.cache.iterdir()), [])
        fake.error = None
        fake.sizes['/file'] = 2
        with self.assertRaisesRegex(transfer.TransferError, 'grew'):
            self.download(fake, ['/file'])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_invalid_request_never_connects(self):
        with patch.object(transfer, 'open_sftp') as connect:
            for paths in [[], 'x', ['relative'], ['/'], ['/a/../b'], ['/a\0b'], [None]]:
                with self.subTest(paths=paths), self.assertRaises(transfer.TransferError):
                    transfer.download('host', paths, self.cache)
            connect.assert_not_called()

    def test_cleanup_only_completed_old_batches(self):
        fake = FakeSFTP({'/file': b'content'})
        old = self.download(fake, ['/file'])[0].parents[1]
        recent = self.download(fake, ['/file'])[0].parents[1]
        os.utime(old / '.complete', (10, 10))
        os.utime(recent / '.complete', (95, 95))
        partial = self.cache / '.partial-old'
        partial.mkdir()
        unrelated = self.cache / 'other'
        unrelated.mkdir()
        link = self.cache / 'transfer-link'
        link.symlink_to(unrelated, target_is_directory=True)
        self.assertEqual(transfer.cleanup_cache(self.cache, 20, now=100), [old])
        self.assertTrue(recent.exists())
        self.assertTrue(partial.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(link.is_symlink())

    def test_ssh_argv_contains_no_file_paths_and_keeps_host_literal(self):
        with patch.object(transfer.subprocess, 'Popen') as popen:
            stream = transfer.SSHStream('my-host')
            args = popen.call_args.args[0]
            self.assertEqual(args[-4:], ['-s', '--', 'my-host', 'sftp'])
            self.assertNotIn('shell', popen.call_args.kwargs)
            stream.close()
        with self.assertRaises(transfer.TransferError):
            transfer.SSHStream('-oProxyCommand=bad')


if __name__ == '__main__':
    unittest.main()
