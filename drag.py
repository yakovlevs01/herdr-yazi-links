#!/usr/bin/env python3
"""Session-scoped file requests. SSH carries JSON; SFTP carries file contents."""
import argparse
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import select
import socket
import subprocess
import sys
import tempfile
import time
import uuid

LIMIT = 65536
TERMINAL = ('done', 'error', 'cancelled')


def state_root():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'herdr-yazi-drag'


def session_name():
    # The owning socket wins over potentially inherited environment defaults.
    sock = os.environ.get('HERDR_SOCKET_PATH')
    if sock:
        parent = Path(sock).parent
        return 'default' if parent.name in ('herdr', 'herdr-dev') else parent.name
    return os.environ.get('HERDR_SESSION')


def locations(session):
    if not session:
        raise ValueError('No Herdr session context')
    key = hashlib.sha256(session.encode()).hexdigest()[:24]
    state = state_root() / key
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime = Path('/tmp') / ('herdr-drag-' + str(os.getuid()))
    runtime.mkdir(mode=0o700, exist_ok=True)
    if runtime.is_symlink() or runtime.stat().st_uid != os.getuid() or runtime.stat().st_mode & 0o077:
        raise RuntimeError('Unsafe runtime directory: ' + str(runtime))
    return state, runtime / (key + '.sock')


def validate(value):
    if not isinstance(value, dict) or not set(value) <= {'paths', 'watched', 'action'} or 'paths' not in value:
        raise ValueError('Only file path requests are accepted')
    if 'watched' in value and value['watched'] is not True:
        raise ValueError('Invalid watcher flag')
    if value.get('action', 'drag') not in ('drag', 'open'):
        raise ValueError('Only drag and open actions are accepted')
    paths = value['paths']
    if not isinstance(paths, list) or not 1 <= len(paths) <= 256:
        raise ValueError('Select between 1 and 256 files')
    for path in paths:
        if not isinstance(path, str) or not path.startswith('/') or '\0' in path:
            raise ValueError('Expected absolute file paths without NUL')
    if len(json.dumps(value).encode()) > LIMIT:
        raise ValueError('Request is too large')
    return paths


def packet(value):
    return (json.dumps(value, ensure_ascii=True) + '\n').encode()


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(packet(value))
    temporary.replace(path)


def job_path(state, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'[0-9a-f]{32}', job_id):
        raise ValueError('Invalid transfer id')
    return state / ('job-' + job_id + '.json')


def watch(job_id, session=None, heartbeat=False):
    """Stream one transfer, including a terminal error when its receiver is gone."""
    state, _ = locations(session or session_name())
    path = job_path(state, job_id)
    if not path.exists():
        raise ValueError('Unknown transfer id')
    previous = None
    while True:
        value = json.loads(path.read_text())
        if value.get('state') not in TERMINAL:
            online = False
            with (state / 'receiver.lock').open('a+') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    online = True
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)
            receiver = state / 'receiver.json'
            current = json.loads(receiver.read_text()) if receiver.exists() else {}
            if not online or current.get('receiver') != value.get('receiver'):
                value = dict(value, state='error', level='error',
                             message='Receiver disconnected. Reconnect Herdr and submit again.')
        if value != previous or heartbeat:
            yield value
            previous = value
        if value.get('state') in TERMINAL:
            return
        time.sleep(0.2)


def serve(session, owner):
    state, address = locations(session)
    with (state / 'receiver.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Receiver conflict for session ' + session + '. Disconnect the existing receiver first.')
        # Persist remote intent: an offline receiver must never fall back to server ripdrag.
        (state / 'remote').write_text(session)
        address.unlink(missing_ok=True)
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(address))
            os.chmod(address, 0o600)
            listener.listen(8)
            token = uuid.uuid4().hex
            atomic_json(state / 'receiver.json', {'receiver': token, 'owner': owner})
            sys.stdout.buffer.write(packet({'ready': token, 'owner': owner}))
            sys.stdout.buffer.flush()
            last = time.monotonic()
            buffered = b''
            watched = {}
            try:
                while time.monotonic() - last < 15:
                    ready, _, _ = select.select([listener, sys.stdin.buffer], [], [], 1)
                    if sys.stdin.buffer in ready:
                        data = os.read(sys.stdin.fileno(), LIMIT)
                        if not data:
                            break
                        last = time.monotonic()
                        buffered += data
                        if len(buffered) > LIMIT:
                            raise ValueError('Oversized receiver status')
                        while b'\n' in buffered:
                            line, buffered = buffered.split(b'\n', 1)
                            feedback = json.loads(line)
                            if feedback != {'heartbeat': True}:
                                atomic_json(state / 'status.json', feedback)
                                try:
                                    path = job_path(state, feedback.get('id'))
                                except ValueError:
                                    continue  # Legacy feedback remains visible through status.
                                if path.exists():
                                    previous = json.loads(path.read_text())
                                    if previous.get('receiver') == token and previous.get('state') not in TERMINAL:
                                        update = dict(previous, **feedback)
                                        update['receiver'] = token
                                        atomic_json(path, update)
                                        if update.get('state') in TERMINAL:
                                            watched.pop(feedback['id'], None)
                    if listener in ready:
                        with listener.accept()[0] as client:
                            client.settimeout(2)
                            try:
                                with client.makefile('rb') as stream:
                                    value = json.loads(stream.readline(LIMIT + 1))
                                paths = validate(value)
                                job = {'id': uuid.uuid4().hex, 'receiver': token, 'paths': paths, 'action': value.get('action', 'drag')}
                                queued = {
                                    'id': job['id'], 'receiver': token, 'state': 'queued',
                                    'file_index': 0, 'file_count': len(paths),
                                    'bytes_done': 0, 'bytes_total': None, 'percent': 0,
                                    'message': 'Queued for ' + owner,
                                }
                                atomic_json(job_path(state, job['id']), queued)
                                atomic_json(state / 'status.json', queued)
                                if value.get('watched'):
                                    watched[job['id']] = {'deadline': time.monotonic() + 5, 'active': False}
                                sys.stdout.buffer.write(packet(job))
                                sys.stdout.buffer.flush()
                                client.sendall(packet({'message': 'Queued for ' + owner, 'id': job['id']}))
                            except (ValueError, OSError) as error:
                                try:
                                    client.sendall(packet({'error': str(error)}))
                                except OSError:
                                    pass  # A cancelled sender must not kill the receiver.
                    for job_id, meta in list(watched.items()):
                        if meta.get('cancel_sent'):
                            continue
                        with (state / ('job-' + job_id + '.watch')).open('a+') as guard:
                            try:
                                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            except BlockingIOError:
                                meta['active'] = True
                                continue
                        if meta['active'] or time.monotonic() >= meta['deadline']:
                            sys.stdout.buffer.write(packet({'cancel': job_id, 'receiver': token}))
                            sys.stdout.buffer.flush()
                            meta['cancel_sent'] = True
            finally:
                address.unlink(missing_ok=True)


def desktop_route(action="drag"):
    address, pane = os.environ.get('HERDR_SOCKET_PATH'), os.environ.get('HERDR_PANE_ID')
    if not address or not pane:
        return None
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(address)
        connection.sendall(packet({'id': 'desktop-route', 'method': 'pane.desktop.take',
                                   'params': {'pane_id': pane, 'action': action}}))
        value = json.loads(connection.makefile('rb').readline(LIMIT))
    if not isinstance(value, dict):
        raise RuntimeError('Invalid desktop routing response')
    if 'error' in value:
        error = value['error']
        if not isinstance(error, dict):
            raise RuntimeError('Invalid desktop routing response')
        message = error.get('message', 'Desktop route failed')
        if not isinstance(message, str):
            raise RuntimeError('Invalid desktop routing response')
        # Older builds retain legacy behavior; a new server must never silently fall back.
        unknown_method = message.lower() in (
            'unknown method pane.desktop.take', 'unknown method: pane.desktop.take'
        ) or message.startswith('unknown variant `pane.desktop.take`,')
        if error.get('code') in ('unknown_method', 'invalid_request') and unknown_method:
            return None
        raise RuntimeError(message)
    result = value.get('result')
    context = result.get('context') if isinstance(result, dict) else None
    if (not isinstance(context, dict)
            or type(context.get('local_to_server')) is not bool
            or not isinstance(context.get('desktop_env', {}), dict)):
        raise RuntimeError('Invalid desktop routing response')
    return context


def local_desktop_env(route):
    env = dict(os.environ)
    if route is not None:
        for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR',
                    'DBUS_SESSION_BUS_ADDRESS', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE',
                    'SSH_CLIENT', 'SSH_CONNECTION', 'SSH_TTY'):
            env.pop(key, None)
        allowed = {'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR',
                   'DBUS_SESSION_BUS_ADDRESS', 'XDG_CURRENT_DESKTOP', 'XDG_SESSION_TYPE'}
        env.update({k: v for k, v in route.get('desktop_env', {}).items() if k in allowed and isinstance(v, str) and '\0' not in v})
    return env


def submit(paths, watched=False, action="drag"):
    paths = [os.path.abspath(path) for path in paths]
    request = {'paths': paths}
    if action != 'drag':
        request['action'] = action
    validate(request)
    session = session_name()
    route = desktop_route(action)
    local = route.get('local_to_server') if route is not None else os.environ.get('HERDR_DRAG_LOCAL') == '1'
    if route is not None and not local:
        receiver = route.get('receiver_id')
        if not isinstance(receiver, str) or not re.fullmatch(r'[0-9a-f]{32}', receiver):
            raise RuntimeError('This client has no desktop receiver. Connect using herdr-yazi on the receiving computer, not inside plain SSH.')
        session = session + '@' + receiver
    if session:
        state, address = locations(session)
        if not local and (route is not None or (state / 'remote').exists()):
            try:
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(3)
                    client.connect(str(address))
                    request = {'paths': paths}
                    if action != 'drag': request['action'] = action
                    if watched:
                        request['watched'] = True
                    client.sendall(packet(request))
                    response = json.loads(client.makefile('rb').readline(LIMIT))
            except OSError as error:
                raise RuntimeError('No active local receiver. Check herdr-yazi-saved-drag or reconnect with herdr-yazi --remote HOST.') from error
            if 'error' in response:
                if watched and response['error'] == 'Only file path requests are accepted':
                    raise RuntimeError('Reconnect herdr-yazi: the running receiver predates task cancellation. '
                                       'Leave the Herdr server running.')
                raise RuntimeError(response['error'])
            response['scope'] = session
            return response
    env = local_desktop_env(route)
    if action == 'open':
        opener = '/usr/bin/open' if sys.platform == 'darwin' else '/usr/bin/xdg-open'
        for path in paths:
            subprocess.Popen([opener, path], env=env, start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'message': 'Opened on client desktop'}
    # The window outlives this helper. A closed stderr pipe would kill it on a
    # later GTK warning; a temporary file remains writable through the child's fd.
    with tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(['ripdrag', '-x', '-a', '-n', '-b', *paths], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errors, env=env)
        try:
            child.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
        else:
            if child.returncode:
                errors.seek(0)
                raise RuntimeError('ripdrag failed: ' + errors.read(8192).decode(errors='replace').strip())
    return {'message': 'Opened local ripdrag'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    broker = sub.add_parser('serve')
    broker.add_argument('session')
    broker.add_argument('owner')
    send = sub.add_parser('submit')
    send.add_argument('--watched', action='store_true')
    send.add_argument('--action', choices=['drag', 'open'], default='drag')
    send.add_argument('paths', nargs='+')
    watcher = sub.add_parser('watch')
    watcher.add_argument('--heartbeat', action='store_true')
    watcher.add_argument('--observe', action='store_true', help='Observe without keeping the transfer alive')
    watcher.add_argument('--session', dest='watch_session')
    watcher.add_argument('id')
    status = sub.add_parser('status')
    status.add_argument('session', nargs='?', default=session_name())
    args = parser.parse_args()
    if args.command == 'serve':
        serve(args.session, args.owner)
    elif args.command == 'submit':
        print(json.dumps(submit(args.paths, args.watched, args.action)))
    elif args.command == 'watch':
        state, _ = locations(args.watch_session or session_name())
        job_path(state, args.id)  # Validate before constructing the lock path.
        with (state / ('job-' + args.id + '.watch')).open('a+') as guard:
            if not args.observe:
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for value in watch(args.id, session=args.watch_session, heartbeat=args.heartbeat):
                print(json.dumps(value), flush=True)
    else:
        state, _ = locations(args.session)
        print((state / 'status.json').read_text() if (state / 'status.json').exists() else '{"message":"No transfer status"}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        message = 'Herdr drag: ' + str(error)
        try:
            state_root().mkdir(parents=True, exist_ok=True, mode=0o700)
            with (state_root() / 'sender.log').open('a') as log:
                log.write(json.dumps({'time': time.time(), 'session': session_name(), 'error': str(error)}) + '\n')
        except OSError:
            pass
        print(message, file=sys.stderr)
        sys.exit(1)
