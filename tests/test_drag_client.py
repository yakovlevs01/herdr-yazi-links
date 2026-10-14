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

    def test_saved_receiver_is_reused_without_spawning_a_second_receiver(self):
        with patch.object(launcher, 'managed_receiver', return_value=True), \
                patch.object(launcher.subprocess, 'call', return_value=0) as call, \
                patch.object(launcher.subprocess, 'Popen') as spawn:
            self.assertEqual(self.invoke(), 0)
        spawn.assert_not_called()
        self.assertEqual(call.call_args.args[0], ['/patched/herdr', '--remote', 'host', '--future', 'a b'])

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

    def test_scoped_client_never_borrows_a_legacy_saved_receiver(self):
        receiver = self.receiver()
        herdr = Mock(returncode=0)
        herdr.poll.return_value = 0
        env = {'HERDR_DRAG_RECEIVER_ID': 'a' * 32}
        with patch.object(launcher, 'managed_receiver', return_value=True) as legacy, patch.object(launcher.subprocess, 'Popen', side_effect=[receiver, herdr]) as spawn, patch.object(launcher.select, 'select', return_value=([receiver.stdout], [], [])):
            self.assertEqual(launcher.remote_client('/herdr', [], env, 'host', 'work', '/python'), 0)
            legacy.assert_not_called()
            self.assertTrue(all(call.kwargs['env'] == env for call in spawn.call_args_list))
        receiver.terminate.assert_called_once()

    def test_local_ui_exit_reaps_owned_receiver_and_preserves_exit_status(self):
        receiver, herdr = Mock(), Mock()
        herdr.wait.return_value = 23
        herdr.poll.return_value = 23
        env = {'HERDR_DRAG_RECEIVER_ID': 'b' * 32}
        with patch.object(launcher.subprocess, 'Popen', side_effect=[receiver, herdr]) as spawn:
            self.assertEqual(launcher.local_client(['/herdr', '--session', 'work'], env), 23)
            self.assertIn('--parent-pid', spawn.call_args_list[0].args[0])
            self.assertTrue(all(call.kwargs['env'] == env for call in spawn.call_args_list))
        receiver.terminate.assert_called_once()
        receiver.wait.assert_called_once()
        herdr.terminate.assert_not_called()

    def test_local_ui_spawn_failure_still_reaps_receiver(self):
        receiver = Mock()
        original = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
        with patch.object(launcher.subprocess, 'Popen', side_effect=[receiver, OSError('missing client')]):
            with self.assertRaisesRegex(OSError, 'missing client'):
                launcher.local_client(['/missing'], {})
        receiver.terminate.assert_called_once()
        receiver.wait.assert_called_once()
        self.assertEqual({sig: signal.getsignal(sig) for sig in original}, original)


class ReceiverTests(unittest.TestCase):
    def test_running_and_queued_cancellation_skip_ripdrag_and_keep_receiver_alive(self):
        running = threading.Event()
        finished = threading.Event()
        frames, attempted = [], []
        first, second, third = ['a' * 32, 'b' * 32, 'c' * 32]
        packets = [client.packet({'ready': 'token'})]
        for job_id in (first, second):
            packets.append(client.packet({'id': job_id, 'receiver': 'token', 'paths': ['/' + job_id]}))
        packets.extend([client.packet({'cancel': second, 'receiver': 'token'}),
                        client.packet({'cancel': first, 'receiver': 'token'}),
                        client.packet({'id': third, 'receiver': 'token', 'paths': ['/' + third]})])
        class Input(io.BytesIO):
            def write(self, data):
                frame = json.loads(data)
                frames.append(frame)
                if frame.get('id') == third and frame.get('state') == 'error':
                    finished.set()
                return super().write(data)
        class Output:
            def close(self):
                pass
            def readline(self, limit):
                if packets:
                    if 'cancel' in json.loads(packets[0]):
                        if not running.wait(3):
                            raise AssertionError('First transfer did not start')
                    return packets.pop(0)
                if not finished.wait(3):
                    raise AssertionError('Receiver did not process next request')
                return b''
        def download(host, paths, directory, batch_progress, cancel):
            attempted.extend(paths)
            if paths == ['/' + third]:
                raise RuntimeError('test next request')
            running.set()
            for _ in range(300):
                client.check_cancel(cancel)
                threading.Event().wait(.01)
            raise AssertionError('Transfer ignored cancellation')
        with tempfile.TemporaryDirectory() as cache:
            ssh = Mock(stdout=Output(), stdin=Input())
            with patch.dict(os.environ, {'HERDR_DRAG_CACHE': cache}), \
                    patch.object(sys, 'argv', ['drag-client.py', 'host', 'session']), \
                    patch.object(client.shutil, 'which', return_value='/bin/ripdrag'), \
                    patch.object(client.subprocess, 'Popen', return_value=ssh) as spawn, \
                    patch.object(client.select, 'select', return_value=([ssh.stdout], [], [])), \
                    patch.object(client, 'download', side_effect=download), patch('builtins.print'):
                with self.assertRaisesRegex(RuntimeError, 'SSH connection closed'):
                    client.main()
            self.assertEqual(spawn.call_count, 1, 'Cancelled requests must not open ripdrag')
        self.assertEqual(attempted, ['/' + first, '/' + third])
        self.assertEqual({f['id'] for f in frames if f.get('state') == 'cancelled'}, {first, second})

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
        def fail_download(*args, **kwargs):
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

    def test_progress_reaches_100_only_after_ripdrag_launch(self):
        for exit_code in (None, 2):
            with self.subTest(ripdrag_exit=exit_code), tempfile.TemporaryDirectory() as cache:
                finished = threading.Event()
                frames = []
                job = {'paths': ['/one', '/two'], 'receiver': 'token', 'id': 'a' * 32}
                packets = [client.packet({'ready': 'token'}), client.packet(job)]
                class Input(io.BytesIO):
                    def write(self, data):
                        frame = json.loads(data)
                        frames.append(frame)
                        if frame.get('state') in ('done', 'error'):
                            finished.set()
                        return super().write(data)
                class Output:
                    def close(self):
                        pass

                    def readline(self, limit):
                        if packets:
                            return packets.pop(0)
                        if not finished.wait(timeout=3):
                            raise AssertionError('Worker did not finish')
                        return b''
                def download(host, paths, directory, batch_progress, cancel):
                    batch_progress({'file_index': 2, 'file_count': 2,
                                    'bytes_done': 12, 'bytes_total': 12, 'percent': 99})
                    self.assertFalse(any(f.get('percent') == 100 for f in frames))
                    return [Path(cache) / 'transfer-test/0000/one',
                            Path(cache) / 'transfer-test/0001/two']
                ssh = Mock(stdout=Output(), stdin=Input())
                window = Mock(returncode=exit_code)
                window.poll.return_value = exit_code
                with patch.dict(os.environ, {'HERDR_DRAG_CACHE': cache}), \
                        patch.object(sys, 'argv', ['drag-client.py', 'host', 'session']), \
                        patch.object(client.shutil, 'which', return_value='/bin/ripdrag'), \
                        patch.object(client.subprocess, 'Popen', side_effect=[ssh, window]), \
                        patch.object(client.select, 'select', return_value=([ssh.stdout], [], [])), \
                        patch.object(client, 'download', side_effect=download), patch('builtins.print'):
                    with self.assertRaisesRegex(RuntimeError, 'SSH connection closed'):
                        client.main()
                logged = [json.loads(line) for line in (Path(cache) / 'receiver.log').read_text().splitlines()]
                self.assertTrue(any(item.get('bytes_done') == 12 and item.get('percent') == 99 for item in logged))
                terminal = [f for f in frames if f.get('state') in ('done', 'error')]
                self.assertEqual(len(terminal), 1)
                if exit_code is None:
                    self.assertEqual(terminal[0]['state'], 'done')
                    self.assertEqual(terminal[0]['percent'], 100)
                    self.assertEqual(terminal[0]['bytes_done'], 12)
                else:
                    self.assertEqual(terminal[0]['state'], 'error')
                    self.assertFalse(any(f.get('percent') == 100 for f in frames))


class DesktopReceiverTests(unittest.TestCase):
    def run_job(self, action='open', platform='linux', exit_codes=(None, None)):
        finished = threading.Event()
        frames = []
        job = {'paths': ['/server/one', '/server/two'], 'action': action,
               'receiver': 'connection-token', 'id': 'd' * 32}
        packets = [client.packet({'ready': 'connection-token'}), client.packet(job)]

        class Input(io.BytesIO):
            def write(self, data):
                frame = json.loads(data)
                frames.append(frame)
                if frame.get('state') in ('done', 'error'):
                    finished.set()
                return super().write(data)

        class Output:
            def close(self):
                pass

            def readline(self, _):
                if packets:
                    return packets.pop(0)
                if not finished.wait(5):
                    raise AssertionError('Receiver failed to complete request')
                return b''

        with tempfile.TemporaryDirectory() as cache:
            copies = [Path(cache) / 'transfer/0000/a \";$(touch NEVER).html',
                      Path(cache) / 'transfer/0001/雪\n.txt']
            ssh = Mock(stdout=Output(), stdin=Input())
            windows = [Mock(returncode=code, poll=Mock(return_value=code)) for code in exit_codes]
            with patch.dict(os.environ, {'HERDR_DRAG_CACHE': cache, 'HERDR_DRAG_RECEIVER_ID': 'a' * 32}, clear=True), patch.object(sys, 'argv', ['drag-client.py', 'host', 'work']), patch.object(sys, 'platform', platform), patch.object(client.shutil, 'which', return_value='/bin/ripdrag'), patch.object(client.subprocess, 'Popen', side_effect=[ssh, *windows]) as spawn, patch.object(client.select, 'select', return_value=([ssh.stdout], [], [])), patch.object(client, 'download', return_value=copies) as download, patch('builtins.print'):
                if action not in ('drag', 'open'):
                    with self.assertRaisesRegex(ValueError, 'Only drag and open'):
                        client.main()
                    download.assert_not_called()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'SSH connection closed'):
                        client.main()
                    self.assertEqual(download.call_args.args[1], job['paths'])
                calls = [call.args[0] for call in spawn.call_args_list]
            return calls, frames, list(map(str, copies))

    def test_remote_open_dispatches_all_downloaded_copies_to_native_opener(self):
        for platform, opener in [('linux', '/usr/bin/xdg-open'), ('darwin', '/usr/bin/open')]:
            with self.subTest(platform=platform):
                calls, frames, copies = self.run_job(platform=platform)
                self.assertIn('work@' + 'a' * 32, calls[0][-1])
                self.assertCountEqual(calls[1:], [[opener, copy] for copy in copies])
                self.assertEqual([f['state'] for f in frames if f.get('state') in ('done', 'error')], ['done'])

    def test_failure_of_any_opener_never_reports_success(self):
        for codes in [(7, None), (None, 7)]:
            with self.subTest(codes=codes):
                _, frames, _ = self.run_job(exit_codes=codes)
                self.assertEqual([f['state'] for f in frames if f.get('state') in ('done', 'error')], ['error'])
                self.assertFalse(any(f.get('percent') == 100 for f in frames))

    def test_drag_still_uses_one_window_and_all_downloaded_paths(self):
        calls, frames, copies = self.run_job(action='drag', exit_codes=(None,))
        self.assertEqual(calls[1:], [['/bin/ripdrag', '-x', '-a', '-n', '-b', *copies]])
        self.assertEqual(frames[-1]['state'], 'done')

    def test_unknown_wire_action_never_downloads_or_starts_a_window(self):
        calls, _, _ = self.run_job(action='shell', exit_codes=())
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
