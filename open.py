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


def yazi_command():
    managed = ROOT / '.build/yazi/bin/yazi'
    if managed.is_file() and os.access(managed, os.X_OK):
        try:
            result = subprocess.run(['yazi', '--version'], capture_output=True, text=True, timeout=5)
            match = re.search(r'\b(\d+)\.(\d+)\.(\d+)', result.stdout)
            version = tuple(map(int, match.groups())) if match else ()
            if result.returncode != 0 or not (version >= (26, 5, 6) and version < (27,)):
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
    return request("plugin.pane.open", {
        "plugin_id": "local.yazi-links",
        "entrypoint": "yazi",
        "placement": "split",
        "target_pane_id": pane_id,
        "direction": "right",
        "cwd": str(path if path.is_dir() else path.parent),
        "focus": True,
        "env": {"YAZI_LINK_PATH": str(path)},
    })


def main():
    if sys.argv[1:] == ["click"]:
        click()
    elif sys.argv[1:] == ["run"]:
        # argv, not shell source: punctuation in a filename cannot execute code.
        path = os.environ["YAZI_LINK_PATH"]
        command = yazi_command()
        os.execvp(command, [command, path])
    else:
        raise ValueError("Usage: open.py click|run")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError) as error:
        print(f"Yazi: {error}", file=sys.stderr)
        sys.exit(1)
