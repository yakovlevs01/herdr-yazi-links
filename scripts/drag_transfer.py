#!/usr/bin/env python3
"""Receive regular files using SFTP carried by the user's OpenSSH client.

Final symlinks and directories are rejected. Intermediate directory symlinks
follow server filesystem semantics. SFTP v3 has no atomic no-follow open, so the
server and its filesystem must be trusted. Copies are retained until explicit
cleanup. Only completed, age-qualified transfer directories are cleaned.
"""
import contextlib
import os
from pathlib import Path, PurePosixPath
import select
import shutil
import stat
import subprocess
import tempfile
import time


class TransferError(RuntimeError):
    pass


class TransferCancelled(TransferError):
    pass


def check_cancel(cancel):
    if cancel and cancel():
        raise TransferCancelled('Transfer cancelled')


class SSHStream:
    """Paramiko socket interface over an OpenSSH SFTP subprocess."""

    def __init__(self, host, cancel=None):
        self.cancel = cancel
        if not isinstance(host, str) or not host or host.startswith('-') or '\0' in host:
            raise TransferError('Invalid SSH host')
        self.process = subprocess.Popen(
            ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
             '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
             '-s', '--', host, 'sftp'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0,
        )

    def get_name(self):
        return 'openssh-sftp'

    def send(self, data):
        check_cancel(self.cancel)
        return self.process.stdin.write(data)

    def recv(self, count):
        deadline = time.monotonic() + 15
        while True:
            check_cancel(self.cancel)
            if select.select([self.process.stdout], [], [], 0.2)[0]:
                break
            if time.monotonic() >= deadline:
                raise TransferError('SFTP response timed out after 15 seconds')
        return self.process.stdout.read(count)

    def close(self):
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()


@contextlib.contextmanager
def open_sftp(host, cancel=None):
    try:
        import paramiko
    except ImportError as exc:
        raise TransferError('Paramiko is required; run sh scripts/install-drag-receiver.sh') from exc
    stream = SSHStream(host, cancel)
    try:
        with paramiko.SFTPClient(stream) as client:
            yield client
    finally:
        stream.close()


def validate_paths(paths):
    if not isinstance(paths, (list, tuple)) or not paths or len(paths) > 4096:
        raise TransferError('Expected 1 to 4096 file paths')
    for path in paths:
        if (not isinstance(path, str) or not path.startswith('/') or '\0' in path
                or path.endswith('/') or any(p in ('.', '..') for p in path.split('/'))):
            raise TransferError(f'Expected an absolute file path: {path!r}')
        try:
            path.encode('utf-8')
        except UnicodeError as exc:
            raise TransferError('File names must be valid UTF-8') from exc
    return list(paths)


def download(host, paths, cache, progress=None, batch_progress=None, cancel=None):
    """Download a batch atomically; progress receives (remote_path, done, total).

    On any failure the entire unfinished batch is removed. Returned Paths are
    absolute and each preserves its original basename in an indexed directory.
    batch_progress receives aggregate counters; percent is capped at 99 until
    the caller has opened ripdrag successfully.
    """
    paths = validate_paths(paths)
    check_cancel(cancel)
    cache = Path(cache).expanduser().absolute()
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.partial-', dir=cache))
    ready = cache / ('transfer-' + staging.name.removeprefix('.partial-'))
    results = []
    try:
        with open_sftp(host, cancel=cancel) as client:
            metadata = []
            for remote_path in paths:
                check_cancel(cancel)
                before = client.lstat(remote_path)
                if not stat.S_ISREG(before.st_mode or 0):
                    raise TransferError(f'Only regular files are supported: {remote_path!r}')
                if before.st_size is None or before.st_size < 0:
                    raise TransferError(f'Server omitted file size: {remote_path!r}')
                metadata.append(before)
            batch_total = sum(item.st_size for item in metadata)
            completed_bytes = 0
            def emit(index, done):
                if batch_progress:
                    amount = completed_bytes + done
                    batch_progress({'file_index': index + 1, 'file_count': len(paths),
                                    'bytes_done': amount, 'bytes_total': batch_total,
                                    'percent': min(99, amount * 100 // batch_total) if batch_total else 0})
            for index, remote_path in enumerate(paths):
                before = metadata[index]
                if not stat.S_ISREG(before.st_mode or 0):
                    raise TransferError(f'Only regular files are supported: {remote_path!r}')
                directory = staging / f'{index:04d}'
                directory.mkdir(mode=0o700)
                target = directory / PurePosixPath(remote_path).name
                total = before.st_size
                if total is None or total < 0:
                    raise TransferError(f'Server omitted file size: {remote_path!r}')
                done = 0
                emit(index, done)
                if progress:
                    progress(remote_path, done, total)
                with client.open(remote_path, 'rb') as source, target.open('xb') as dest:
                    os.chmod(target, 0o600)
                    opened = source.stat()
                    if not stat.S_ISREG(opened.st_mode or 0) or opened.st_size != total:
                        raise TransferError(f'File changed before download: {remote_path!r}')
                    while True:
                        check_cancel(cancel)
                        block = source.read(128 * 1024)
                        if not block:
                            break
                        dest.write(block)
                        done += len(block)
                        if done > total:
                            raise TransferError(f'File grew during download: {remote_path!r}')
                        emit(index, done)
                        if progress:
                            progress(remote_path, done, total)
                    dest.flush()
                    os.fsync(dest.fileno())
                    after = source.stat()
                final = client.lstat(remote_path)
                if (done != total or after.st_size != total or final.st_size != total
                        or not stat.S_ISREG(final.st_mode or 0)
                        or after.st_mtime != before.st_mtime or final.st_mtime != before.st_mtime):
                    raise TransferError(f'File changed or download incomplete: {remote_path!r}')
                completed_bytes += done
                results.append(ready / target.relative_to(staging))
        check_cancel(cancel)
        (staging / '.complete').touch(mode=0o600)
        staging.rename(ready)
        return results
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def cleanup_cache(cache, older_than_seconds, now=None):
    """Explicitly remove completed copies older than the supplied age.

    Call only when receiving applications no longer need these copies. Active
    downloads and unrelated directories are never removed. Return removed paths.
    """
    if older_than_seconds < 0:
        raise ValueError('Cache age cannot be negative')
    now = time.time() if now is None else now
    cache = Path(cache).expanduser()
    if not cache.exists():
        return []
    removed = []
    for child in cache.iterdir():
        if child.is_symlink() or not child.is_dir() or not child.name.startswith('transfer-'):
            continue
        marker = child / '.complete'
        if marker.is_symlink() or not marker.is_file():
            continue
        if now - marker.stat().st_mtime >= older_than_seconds:
            shutil.rmtree(child)
            removed.append(child)
    return removed
