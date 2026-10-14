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

    def test_two_clients_of_same_session_have_independent_receivers(self):
        scopes = [self.session + '@' + letter * 32 for letter in ('a', 'b')]
        brokers = [self.start(scope, owner) for scope, owner in zip(scopes, ['Mac', 'IW'])]
        greetings = [self.read(broker) for broker in brokers]
        for scope, broker, greeting, path in zip(scopes, brokers, greetings, ['/mac.txt', '/iw.txt']):
            result = self.request({'paths': [path], 'action': 'open'}, session=scope)
            job = self.read(broker)
            self.assertEqual(job['paths'], [path])
            self.assertEqual(job['action'], 'open')
            self.assertEqual(job['receiver'], greeting['ready'])
            self.assertEqual(job['id'], result['id'])
        self.assertNotEqual(greetings[0]['ready'], greetings[1]['ready'])

    def test_submit_and_watch_use_exact_client_scope_when_legacy_is_also_online(self):
        legacy = self.start()
        self.read(legacy)
        scope = self.session + '@' + 'a' * 32
        receiver = self.start(scope, 'Mac')
        self.read(receiver)
        env = dict(self.env, HERDR_SESSION=self.session, HERDR_DRAG_LOCAL='1')
        route = {'local_to_server': False, 'receiver_id': 'a' * 32}
        with patch.dict(os.environ, env, clear=True), patch.object(drag, 'desktop_route', return_value=route), patch.object(drag.subprocess, 'Popen') as spawn:
            result = drag.submit(['/server/file'], action='open')
            spawn.assert_not_called()
        self.assertEqual(result['scope'], scope)
        job = self.read(receiver)
        self.assertEqual(job['action'], 'open')
        self.assertEqual(job['id'], result['id'])
        self.assertFalse(select.select([legacy.stdout], [], [], .05)[0])
        receiver.stdin.write(drag.packet({'id': job['id'], 'state': 'done'}))
        receiver.stdin.flush()
        watched = self.cli('watch', '--session', scope, job['id'])
        self.assertEqual(watched.returncode, 0, watched.stderr)
        self.assertEqual(json.loads(watched.stdout.splitlines()[-1])['state'], 'done')
        wrong_scope = self.cli('watch', job['id'])
        self.assertNotEqual(wrong_scope.returncode, 0)

    def test_disconnected_scoped_receiver_does_not_fall_back_to_other_online_client(self):
        first_scope = self.session + '@' + 'a' * 32
        second_scope = self.session + '@' + 'b' * 32
        first, second, legacy = self.start(first_scope), self.start(second_scope), self.start()
        for broker in (first, second, legacy):
            self.read(broker)
        self.stop(first)
        with patch.dict(os.environ, dict(self.env, HERDR_SESSION=self.session), clear=True), patch.object(drag, 'desktop_route', return_value={'local_to_server': False, 'receiver_id': 'a' * 32}), patch.object(drag.subprocess, 'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'No active local receiver'):
                drag.submit(['/server/file'])
            spawn.assert_not_called()
        self.assertFalse(select.select([second.stdout, legacy.stdout], [], [], .05)[0])
        self.request({'paths': ['/still-working']}, session=second_scope)
        self.assertEqual(self.read(second)['paths'], ['/still-working'])

    def test_simultaneous_scoped_requests_never_cross_clients(self):
        scopes = [self.session + '@' + x * 32 for x in ('a', 'b')]
        brokers = [self.start(scope) for scope in scopes]
        greetings = [self.read(broker) for broker in brokers]
        addresses = [self.locations(scope)[1] for scope in scopes]
        def send(pair):
            index, address = pair
            with socket.socket(socket.AF_UNIX) as client:
                client.settimeout(3)
                client.connect(str(address))
                client.sendall(drag.packet({'paths': ['/client-' + str(index)]}))
                with client.makefile('rb') as stream:
                    return json.loads(stream.readline())
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(send, enumerate(addresses)))
        for index, broker in enumerate(brokers):
            job = self.read(broker)
            self.assertEqual(job['paths'], ['/client-' + str(index)])
            self.assertEqual(job['receiver'], greetings[index]['ready'])
            self.assertEqual(job['id'], responses[index]['id'])

    def test_killed_watcher_cancels_only_its_transfer(self):
        broker = self.start()
        greeting = self.read(broker)
        response = self.request({'paths': ['/one'], 'watched': True})
        job = self.read(broker)
        other = self.request({'paths': ['/two']})
        self.read(broker)
        watcher = subprocess.Popen([sys.executable, str(ROOT / 'drag.py'), 'watch', response['id']],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=dict(self.env, HERDR_SESSION=self.session))
        try:
            self.assertEqual(json.loads(watcher.stdout.readline())['state'], 'queued')
            # Give the broker time to observe the held lock before terminating.
            time.sleep(1.2)
            watcher.kill()
            watcher.wait(timeout=3)
            cancelled = self.read(broker)
            self.assertEqual(cancelled, {'cancel': job['id'], 'receiver': greeting['ready']})
            broker.stdin.write(drag.packet({'id': job['id'], 'state': 'cancelled'}))
            broker.stdin.flush()
            result = self.cli('watch', job['id'])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout.splitlines()[-1])['state'], 'cancelled')
            state, _ = self.locations()
            self.assertEqual(json.loads(drag.job_path(state, other['id']).read_text())['state'], 'queued')
        finally:
            if watcher.poll() is None:
                watcher.kill(); watcher.wait()
            watcher.stdout.close(); watcher.stderr.close()

    def test_missing_watcher_cancels_after_startup_grace(self):
        broker = self.start()
        self.read(broker)
        response = self.request({'paths': ['/one'], 'watched': True})
        self.read(broker)
        self.assertEqual(self.read(broker, timeout=7)['cancel'], response['id'])

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
    def test_local_client_bypasses_offline_remote_marker_without_removing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {'XDG_STATE_HOME': tmp, 'HERDR_SESSION': 'local-routing-test',
                   'HERDR_DRAG_LOCAL': '1'}
            with patch.dict(os.environ, env, clear=True):
                state, _ = drag.locations(env['HERDR_SESSION'])
                (state / 'remote').write_text(env['HERDR_SESSION'])
                with patch.object(drag.subprocess, 'Popen') as launch:
                    launch.return_value.wait.side_effect = subprocess.TimeoutExpired('ripdrag', .25)
                    drag.submit(['/tmp/example.txt'])
                    launch.assert_called_once()
                self.assertTrue((state / 'remote').exists())
                os.environ['HERDR_DRAG_LOCAL'] = '0'
                with patch.object(drag.subprocess, 'Popen') as launch:
                    with self.assertRaisesRegex(RuntimeError, 'No active local receiver'):
                        drag.submit(['/tmp/example.txt'])
                    launch.assert_not_called()

    def test_local_fallback_keeps_ripdrag_options_and_literal_arguments(self):
        paths = ['space quote\'" 雪', '-option', '$`command`']
        with patch.dict(os.environ, {}, clear=True), patch.object(drag.subprocess, 'Popen') as launch:
            launch.return_value.wait.side_effect = subprocess.TimeoutExpired('ripdrag', .25)
            result = drag.submit(paths)
        self.assertEqual(launch.call_args.args[0],
                         ['ripdrag', '-x', '-a', '-n', '-b', *map(os.path.abspath, paths)])
        self.assertTrue(launch.call_args.kwargs['start_new_session'])
        self.assertEqual(result['message'], 'Opened local ripdrag')

    def test_default_socket_maps_to_default_profile_session(self):
        with patch.dict(os.environ, {'HERDR_SOCKET_PATH': '/home/me/.config/herdr/herdr.sock'}):
            self.assertEqual(drag.session_name(), 'default')

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
