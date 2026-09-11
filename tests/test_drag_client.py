import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    with patch.object(sys, 'path', [str(ROOT / 'scripts'), *sys.path]):
        spec.loader.exec_module(result)
    return result


client = module('drag_client', ROOT / 'scripts/drag-client.py')
launcher = module('drag_launcher', ROOT / 'scripts/launch.py')


class RemoteClientTests(unittest.TestCase):
    def receiver(self, greeting=b'READY\n'):
        return Mock(stdout=io.BytesIO(greeting), returncode=0)

    def invoke(self):
        return launcher.remote_client('/patched/herdr', ['--remote', 'host', '--future', 'a b'],
                                      {'PATH': '/user/bin'}, 'host', 'session', '/venv/python')

    def test_startup_refusal_never_launches_herdr_and_cleans_receiver(self):
        receiver = self.receiver(b'')
        with patch.object(launcher.subprocess, 'Popen', return_value=receiver) as spawn, \
                patch.object(launcher.select, 'select', return_value=([receiver.stdout], [], [])):
            with self.assertRaisesRegex(SystemExit, 'could not start'):
                self.invoke()
        self.assertEqual(spawn.call_count, 1)
        receiver.terminate.assert_called_once()
        receiver.wait.assert_called_once()

    def test_normal_exit_preserves_argv_and_exit_code_and_stops_receiver(self):
        receiver = self.receiver()
        herdr = Mock(returncode=23)
        herdr.poll.return_value = 23
        with patch.object(launcher.subprocess, 'Popen', side_effect=[receiver, herdr]) as spawn, \
                patch.object(launcher.select, 'select', return_value=([receiver.stdout], [], [])):
            self.assertEqual(self.invoke(), 23)
        self.assertEqual(spawn.call_args_list[1].args[0],
                         ['/patched/herdr', '--remote', 'host', '--future', 'a b'])
        self.assertEqual(spawn.call_args_list[1].kwargs['env'], {'PATH': '/user/bin'})
        receiver.terminate.assert_called_once()
        herdr.terminate.assert_not_called()

    def test_receiver_failure_detaches_client_and_reaps_both(self):
        receiver = self.receiver()
        receiver.poll.return_value = 1
        herdr = Mock()
        herdr.poll.return_value = None
        herdr.wait.side_effect = lambda: setattr(herdr.poll, 'return_value', 0)
        with patch.object(launcher.subprocess, 'Popen', side_effect=[receiver, herdr]), \
                patch.object(launcher.select, 'select', return_value=([receiver.stdout], [], [])):
            with self.assertRaisesRegex(SystemExit, 'receiver disconnected'):
                self.invoke()
        herdr.terminate.assert_called_once()
        herdr.wait.assert_called_once()
        receiver.terminate.assert_called_once()
        receiver.wait.assert_called_once()

    def test_sigterm_runs_cleanup_and_restores_signal_handlers(self):
        receiver = self.receiver()
        receiver.poll.return_value = None
        herdr = Mock()
        herdr.poll.return_value = None
        original = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
        def interrupt(_):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        with patch.object(launcher.subprocess, 'Popen', side_effect=[receiver, herdr]), \
                patch.object(launcher.select, 'select', return_value=([receiver.stdout], [], [])), \
                patch.object(launcher.time, 'sleep', side_effect=interrupt):
            with self.assertRaises(SystemExit) as error:
                self.invoke()
        self.assertEqual(error.exception.code, 128 + signal.SIGTERM)
        herdr.terminate.assert_called_once()
        herdr.wait.assert_called_once()
        receiver.terminate.assert_called_once()
        receiver.wait.assert_called_once()
        self.assertEqual({sig: signal.getsignal(sig) for sig in original}, original)


class ReceiverTests(unittest.TestCase):
    def test_startup_conflict_never_downloads_or_opens_ripdrag(self):
        with tempfile.TemporaryDirectory() as cache:
            ssh = Mock(stdout=io.BytesIO(), stdin=io.BytesIO())
            with patch.dict(os.environ, {'HERDR_DRAG_CACHE': cache}), \
                    patch.object(sys, 'argv', ['drag-client.py', 'host', 'session']), \
                    patch.object(client.shutil, 'which', return_value='/usr/bin/ripdrag'), \
                    patch.object(client.subprocess, 'Popen', return_value=ssh) as spawn, \
                    patch.object(client.select, 'select', return_value=([ssh.stdout], [], [])), \
                    patch.object(client, 'download') as download:
                with self.assertRaisesRegex(RuntimeError, 'possible receiver conflict'):
                    client.main()
            self.assertEqual(spawn.call_count, 1)
            download.assert_not_called()
            ssh.wait.assert_called_once()

    def test_maximum_job_reaches_download_and_failure_never_launches_ripdrag(self):
        overhead = len(json.dumps({'paths': ['/']}).encode())
        paths = ['/' + 'x' * (client.LIMIT - overhead)]
        job = {'paths': paths, 'receiver': 'token', 'id': 'job'}
        failed = threading.Event()
        packets = [client.packet({'ready': 'token'}), client.packet(job)]
        class Output:
            def close(self):
                pass

            def readline(self, limit):
                if packets:
                    return packets.pop(0)[:limit]
                if not failed.wait(timeout=3):
                    raise AssertionError('Worker never attempted download')
                return b''
        def fail_download(*args):
            failed.set()
            raise RuntimeError('incomplete SFTP transfer')
        with tempfile.TemporaryDirectory() as cache:
            ssh = Mock(stdout=Output(), stdin=io.BytesIO())
            with patch.dict(os.environ, {'HERDR_DRAG_CACHE': cache}), \
                    patch.object(sys, 'argv', ['drag-client.py', 'host', 'session']), \
                    patch.object(client.shutil, 'which', side_effect=lambda name: '/bin/ripdrag' if name == 'ripdrag' else None), \
                    patch.object(client.subprocess, 'Popen', return_value=ssh) as spawn, \
                    patch.object(client.select, 'select', return_value=([ssh.stdout], [], [])), \
                    patch.object(client, 'download', side_effect=fail_download) as download, \
                    patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError, 'SSH connection closed'):
                    client.main()
            download.assert_called_once()
            self.assertEqual(download.call_args.args[1], paths)
            self.assertEqual(spawn.call_count, 1, 'Failed downloads must not launch ripdrag')
            self.assertIn('incomplete SFTP transfer', (Path(cache) / 'receiver.log').read_text())


if __name__ == '__main__':
    unittest.main()
