"""Exercise the real request broker with pipes, Unix sockets and its CLI."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('drag', ROOT / 'drag.py')
drag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drag)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = dict(os.environ, XDG_STATE_HOME=self.temp.name)
        self.env.pop('HERDR_SOCKET_PATH', None)
        self.env.pop('HERDR_SESSION', None)
        self.session = 'drag-test-' + uuid.uuid4().hex

    def locations(self, session=None):
        with patch.dict(os.environ, self.env, clear=True):
            return drag.locations(session or self.session)

    def start(self, session=None, owner='test computer'):
        session = session or self.session
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'drag.py'), 'serve', session, owner],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.env, bufsize=0,
        )
        self.addCleanup(self.stop, process)
        self.addCleanup(self.locations(session)[1].unlink, missing_ok=True)
        return process

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        for pipe in [process.stdin, process.stdout, process.stderr]:
            pipe.close()

    def read(self, process, timeout=3):
        data = b''
        deadline = time.monotonic() + timeout
        while b'\n' not in data:
            remaining = deadline - time.monotonic()
            self.assertGreater(remaining, 0, 'Timed out reading broker output')
            self.assertTrue(select.select([process.stdout], [], [], remaining)[0],
                            'Timed out reading broker output')
            chunk = os.read(process.stdout.fileno(), 1)
            if not chunk:
                process.wait(timeout=3)
                self.fail('Broker exited before emitting a packet: ' + process.stderr.read().decode())
            data += chunk
        return json.loads(data)

    def cli(self, *args, session=None):
        env = dict(self.env, HERDR_SESSION=session or self.session)
        return subprocess.run([sys.executable, str(ROOT / 'drag.py'), *args],
                              capture_output=True, text=True, env=env, timeout=4)

    def request(self, payload, session=None):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(3)
            client.connect(str(self.locations(session)[1]))
            client.sendall(drag.packet(payload))
            with client.makefile('rb') as stream:
                return json.loads(stream.readline())

    def test_multiple_special_names_round_trip_without_shell(self):
        process = self.start()
        ready = self.read(process)
        paths = ['/a/space quote\'" $`*?;\n雪.txt', '/b/space quote\'" $`*?;\n雪.txt']
        result = self.cli('submit', '--', *paths)
        self.assertEqual(result.returncode, 0, result.stderr)
        job = self.read(process)
        self.assertEqual(job['paths'], paths)
        self.assertEqual(job['receiver'], ready['ready'])
        self.assertEqual(job['id'], json.loads(result.stdout)['id'])
        self.assertIn('test computer', json.loads(result.stdout)['message'])

    def test_rejects_commands_and_invalid_paths_but_keeps_serving(self):
        process = self.start()
        self.read(process)
        for payload in [{'command': 'touch /tmp/unwanted'},
                        {'paths': ['/file'], 'command': 'anything'},
                        {'paths': []}, {'paths': ['relative']},
                        {'paths': ['/has\0nul']}, {'paths': [42]}, ['anything']]:
            with self.subTest(payload=payload):
                self.assertIn('error', self.request(payload))
        response = self.request({'paths': ['/valid']})
        self.assertNotIn('error', response)
        self.assertEqual(self.read(process)['paths'], ['/valid'])

    def test_second_receiver_conflict_does_not_displace_owner(self):
        first = self.start(owner='first computer')
        ready = self.read(first)
        second = self.start(owner='second computer')
        second.wait(timeout=3)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('Receiver conflict', second.stderr.read().decode())
        response = self.request({'paths': ['/file']})
        self.assertIn('first computer', response['message'])
        self.assertEqual(self.read(first)['receiver'], ready['ready'])

    def test_disconnected_request_peer_does_not_stop_broker(self):
        process = self.start()
        self.read(process)
        with socket.socket(socket.AF_UNIX) as client:
            client.connect(str(self.locations()[1]))
        response = self.request({'paths': ['/still-alive']})
        self.assertNotIn('error', response)
        self.assertEqual(self.read(process)['paths'], ['/still-alive'])
        self.assertIsNone(process.poll())

    def test_largest_accepted_request_round_trip(self):
        process = self.start()
        self.read(process)
        overhead = len(json.dumps({'paths': ['/']}).encode())
        paths = ['/' + 'x' * (drag.LIMIT - overhead)]
        self.assertEqual(len(json.dumps({'paths': paths}).encode()), drag.LIMIT)
        with ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(self.read, process)
            response = self.request({'paths': paths})
            job = reading.result(timeout=4)
        self.assertNotIn('error', response)
        self.assertEqual(job['paths'], paths)
        self.assertEqual(job['id'], response['id'])

    def test_disconnect_reconnect_preserves_session_context_without_replay(self):
        first = self.start()
        old = self.read(first)
        self.request({'paths': ['/old']})
        self.read(first)
        first.stdin.close()
        first.wait(timeout=3)
        self.assertFalse(self.locations()[1].exists())
        offline = self.cli('submit', '/offline')
        self.assertNotEqual(offline.returncode, 0)
        self.assertIn('No active local receiver', offline.stderr)
        second = self.start(owner='new computer')
        current = self.read(second)
        self.assertNotEqual(old['ready'], current['ready'])
        self.assertFalse(select.select([second.stdout], [], [], 0.15)[0])
        response = self.cli('submit', '/new')
        self.assertEqual(response.returncode, 0, response.stderr)
        job = self.read(second)
        self.assertEqual(job['paths'], ['/new'])
        self.assertEqual(job['receiver'], current['ready'])

    def test_independent_sessions_route_only_to_their_receiver(self):
        other_session = self.session + '-other'
        first = self.start()
        second = self.start(session=other_session)
        first_ready = self.read(first)
        second_ready = self.read(second)
        self.assertEqual(self.cli('submit', '/first').returncode, 0)
        self.assertEqual(self.cli('submit', '/second', session=other_session).returncode, 0)
        first_job = self.read(first)
        second_job = self.read(second)
        self.assertEqual(first_job['receiver'], first_ready['ready'])
        self.assertEqual(first_job['paths'], ['/first'])
        self.assertEqual(second_job['receiver'], second_ready['ready'])
        self.assertEqual(second_job['paths'], ['/second'])
        self.assertFalse(select.select([first.stdout, second.stdout], [], [], 0.1)[0])

    def test_receiver_heartbeat_expiry_removes_socket(self):
        process = self.start()
        self.read(process)
        process.wait(timeout=17)
        self.assertEqual(process.returncode, 0, process.stderr.read().decode())
        self.assertFalse(self.locations()[1].exists())
        result = self.cli('submit', '/file')
        self.assertIn('No active local receiver', result.stderr)

    def test_status_reports_receiver_feedback_and_ignores_heartbeat(self):
        process = self.start()
        self.read(process)
        feedback = {'id': 'job', 'state': 'error', 'message': 'download failed 雪'}
        process.stdin.write(drag.packet(feedback) + drag.packet({'heartbeat': True}))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            result = self.cli('status', self.session)
            if json.loads(result.stdout) == feedback:
                break
            time.sleep(0.02)
        self.assertEqual(json.loads(result.stdout), feedback)

    def start_watch(self, job_id):
        process = subprocess.Popen(
            [sys.executable, str(ROOT / 'drag.py'), 'watch', job_id],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(self.env, HERDR_SESSION=self.session), bufsize=0)
        self.addCleanup(self.stop, process)
        return process

    def test_watch_isolates_queued_jobs_and_finishes_on_terminal_feedback(self):
        broker = self.start()
        self.read(broker)
        first = self.request({'paths': ['/first']})['id']
        self.read(broker)
        second = self.request({'paths': ['/second']})['id']
        self.read(broker)
        watcher = self.start_watch(first)
        queued = self.read(watcher)
        self.assertEqual(queued['state'], 'queued')
        self.assertEqual(queued['percent'], 0)
        broker.stdin.write(drag.packet({'id': second, 'state': 'downloading', 'percent': 45}))
        self.assertFalse(select.select([watcher.stdout], [], [], 0.4)[0])
        broker.stdin.write(drag.packet({'id': first, 'state': 'downloading', 'percent': 99,
                                       'bytes_done': 10, 'bytes_total': 10}))
        progress = self.read(watcher)
        self.assertEqual(progress['percent'], 99)
        self.assertEqual(progress['file_count'], 1)
        broker.stdin.write(drag.packet({'id': first, 'state': 'done', 'percent': 100}))
        self.assertEqual(self.read(watcher)['state'], 'done')
        watcher.wait(timeout=2)
        self.assertEqual(watcher.returncode, 0)
        with patch.dict(os.environ, self.env, clear=True):
            second_state = json.loads(drag.job_path(self.locations()[0], second).read_text())
        self.assertEqual(second_state['percent'], 45)

    def test_watch_disconnect_and_receiver_replacement_do_not_hang_or_replay(self):
        first = self.start()
        self.read(first)
        job = self.request({'paths': ['/file']})['id']
        self.read(first)
        watcher = self.start_watch(job)
        self.assertEqual(self.read(watcher)['state'], 'queued')
        # Even SIGKILL leaves a stale socket; lock ownership is the liveness check.
        first.kill()
        first.wait(timeout=2)
        second = self.start()
        self.read(second)
        error = self.read(watcher)
        self.assertEqual(error['state'], 'error')
        self.assertIn('disconnected', error['message'])
        watcher.wait(timeout=2)
        self.assertFalse(select.select([second.stdout], [], [], 0.2)[0])

    def test_watch_rejects_unknown_ids_and_path_traversal(self):
        for job_id in ['../status', 'job', '0' * 32]:
            result = self.cli('watch', job_id)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('transfer id', result.stderr)


class LocalTests(unittest.TestCase):
    def test_local_fallback_keeps_ripdrag_options_and_literal_arguments(self):
        paths = ['space quote\'" 雪', '-option', '$`command`']
        with patch.dict(os.environ, {}, clear=True), patch.object(drag.subprocess, 'Popen') as launch:
            result = drag.submit(paths)
        self.assertEqual(launch.call_args.args[0],
                         ['ripdrag', '-x', '-a', '-n', '-b', *map(os.path.abspath, paths)])
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertEqual(result['message'], 'Opened local ripdrag')

    def test_owning_socket_overrides_inherited_session(self):
        with patch.dict(os.environ, {'HERDR_SOCKET_PATH': '/tmp/herdr/actual/control.sock',
                                     'HERDR_SESSION': 'inherited'}, clear=True):
            self.assertEqual(drag.session_name(), 'actual')

    def test_validation_bounds(self):
        for value in [{'paths': ['/file'] * 257}, {'paths': ['/' + 'x' * drag.LIMIT]}]:
            with self.subTest(value_length=len(str(value))):
                with self.assertRaises(ValueError):
                    drag.validate(value)


if __name__ == '__main__':
    unittest.main()
