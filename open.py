#!/usr/bin/env python3
"""Open a clicked file in a Yazi pane on the server that owns the source pane."""

import json
import os
from pathlib import Path
import shutil
import socket
import sys
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent
DESKTOP_KEYS = frozenset({
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR",
    "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE",
})
CLIENT_CONTEXT_KEY = "YAZI_LINK_CLIENT_CONTEXT"


def client_context(value):
    """Validate and minimize the optional, client-reported click context."""
    if value is None:
        return None  # Older Herdr clients retain their existing behavior.
    if not isinstance(value, dict) or type(value.get("local_to_server")) is not bool:
        raise ValueError("Некорректный контекст клиента Herdr")
    supplied = value.get("desktop_env", {})
    if not isinstance(supplied, dict):
        raise ValueError("Некорректное окружение клиента Herdr")
    desktop = {}
    if value["local_to_server"]:
        for key in DESKTOP_KEYS:
            item = supplied.get(key)
            if item is not None:
                if not isinstance(item, str) or "\0" in item or len(item) > 8192:
                    raise ValueError(f"Некорректное значение {key}")
                if item:
                    desktop[key] = item
    return {"local_to_server": value["local_to_server"], "desktop_env": desktop}


def yazi_environment(environ):
    """Build one child environment without mutating the server or other panes."""
    result = dict(environ)
    raw = result.pop(CLIENT_CONTEXT_KEY, None)
    context = client_context(json.loads(raw)) if raw is not None else None
    if context is not None:
        for key in DESKTOP_KEYS:
            result.pop(key, None)
        # The server may itself have been launched by a different SSH client.
        for key in ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY", "XDG_SESSION_ID"):
            result.pop(key, None)
        result.update(context["desktop_env"])
        result["HERDR_DRAG_LOCAL"] = "1" if context["local_to_server"] else "0"
    return result


def yazi_command():
    managed = ROOT / '.build/yazi/bin/yazi'
    if managed.is_file() and os.access(managed, os.X_OK):
        try:
            result = subprocess.run(['yazi', '--version'], capture_output=True, text=True, timeout=5)
            match = re.search(r'\b(\d+)\.(\d+)\.(\d+)', result.stdout)
            version = tuple(map(int, match.groups())) if match else ()
            if result.returncode != 0 or not (version >= (26, 8, 15) and version < (27,)):
                return str(managed)
        except (OSError, subprocess.TimeoutExpired):
            return str(managed)
    return 'yazi'


def file_path(uri):
    parsed = urlsplit(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost", socket.gethostname()):
        raise ValueError("Ожидалась ссылка на файл на машине этой панели")
    path = Path(unquote(parsed.path, errors="strict"))
    if not path.is_absolute() or "\0" in str(path):
        raise ValueError("Ожидался абсолютный путь")
    if not path.is_file() and not path.is_dir():
        raise ValueError(f"Файл не найден: {path}")
    return path


def request(method, params):
    # The socket is injected by Herdr, so --remote uses the remote server too.
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(15)
        connection.connect(os.environ["HERDR_SOCKET_PATH"])
        connection.sendall((json.dumps({"id": "yazi-link", "method": method, "params": params}) + "\n").encode())
        with connection.makefile("rb") as stream:
            response = json.loads(stream.readline(1024 * 1024))
    if "error" in response:
        raise RuntimeError(response["error"].get("message", str(response["error"])))
    return response["result"]


def click():
    path = file_path(os.environ["HERDR_PLUGIN_CLICKED_URL"])
    if shutil.which("yazi") is None and not (ROOT / '.build/yazi/bin/yazi').is_file():
        raise RuntimeError("yazi отсутствует в PATH сервера Herdr")
    context = json.loads(os.environ["HERDR_PLUGIN_CONTEXT_JSON"])
    pane_id = context["focused_pane_id"]
    pane_env = {"YAZI_LINK_PATH": str(path)}
    origin = client_context(context.get("client_context"))
    if origin is not None:
        pane_env[CLIENT_CONTEXT_KEY] = json.dumps(origin)
    return request("plugin.pane.open", {
        "plugin_id": "local.yazi-links",
        "entrypoint": "yazi",
        "placement": "split",
        "target_pane_id": pane_id,
        "direction": "right",
        "cwd": str(path if path.is_dir() else path.parent),
        "focus": True,
        "env": pane_env,
    })


def main():
    if sys.argv[1:] == ["click"]:
        click()
    elif sys.argv[1:] == ["run"]:
        # argv, not shell source: punctuation in a filename cannot execute code.
        path = os.environ["YAZI_LINK_PATH"]
        command = yazi_command()
        env = yazi_environment(os.environ)
        env["PATH"] = str(ROOT / "desktop-bin") + os.pathsep + env.get("PATH", "")
        os.execvpe(command, [command, path], env)
    else:
        raise ValueError("Usage: open.py click|run")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError) as error:
        print(f"Yazi: {error}", file=sys.stderr)
        sys.exit(1)
