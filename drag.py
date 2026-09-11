#!/usr/bin/env python3
"""Session-scoped file requests. SSH carries JSON; SFTP carries file contents."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time
import uuid

LIMIT = 65536


def state_root():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'herdr-yazi-drag'


def session_name():
    # The owning socket wins over potentially inherited environment defaults.
    sock = os.environ.get('HERDR_SOCKET_PATH')
    return Path(sock).parent.name if sock else os.environ.get('HERDR_SESSION')


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
    if not isinstance(value, dict) or set(value) != {'paths'}:
        raise ValueError('Only file path requests are accepted')
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
            sys.stdout.buffer.write(packet({'ready': token, 'owner': owner}))
            sys.stdout.buffer.flush()
            last = time.monotonic()
            buffered = b''
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
                                (state / 'status.json').write_text(json.dumps(feedback, ensure_ascii=True))
                    if listener in ready:
                        with listener.accept()[0] as client:
                            client.settimeout(2)
                            try:
                                with client.makefile('rb') as stream:
                                    value = json.loads(stream.readline(LIMIT + 1))
                                paths = validate(value)
                                job = {'id': uuid.uuid4().hex, 'receiver': token, 'paths': paths}
                                sys.stdout.buffer.write(packet(job))
                                sys.stdout.buffer.flush()
                                client.sendall(packet({'message': 'Queued for ' + owner, 'id': job['id']}))
                            except (ValueError, OSError) as error:
                                try:
                                    client.sendall(packet({'error': str(error)}))
                                except OSError:
                                    pass  # A cancelled sender must not kill the receiver.
            finally:
                address.unlink(missing_ok=True)


def submit(paths):
    paths = [os.path.abspath(path) for path in paths]
    validate({'paths': paths})
    session = session_name()
    if session:
        state, address = locations(session)
        if (state / 'remote').exists():
            try:
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(3)
                    client.connect(str(address))
                    client.sendall(packet({'paths': paths}))
                    response = json.loads(client.makefile('rb').readline(LIMIT))
            except OSError as error:
                raise RuntimeError('No active local receiver. Reconnect with herdr-yazi --remote HOST.') from error
            if 'error' in response:
                raise RuntimeError(response['error'])
            return response
    subprocess.Popen(['ripdrag', '-x', '-a', '-n', '-b', *paths], start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {'message': 'Opened local ripdrag'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    broker = sub.add_parser('serve')
    broker.add_argument('session')
    broker.add_argument('owner')
    send = sub.add_parser('submit')
    send.add_argument('paths', nargs='+')
    status = sub.add_parser('status')
    status.add_argument('session', nargs='?', default=session_name())
    args = parser.parse_args()
    if args.command == 'serve':
        serve(args.session, args.owner)
    elif args.command == 'submit':
        print(json.dumps(submit(args.paths)))
    else:
        state, _ = locations(args.session)
        print((state / 'status.json').read_text() if (state / 'status.json').exists() else '{"message":"No transfer status"}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print('Herdr drag: ' + str(error), file=sys.stderr)
        sys.exit(1)
