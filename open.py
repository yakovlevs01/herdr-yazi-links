#!/usr/bin/env python3
"""Open a clicked file in a Yazi pane on the server that owns the source pane."""

import json
import os
from pathlib import Path
import shutil
import socket
import sys
from urllib.parse import unquote, urlsplit


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
    if shutil.which("yazi") is None:
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
        os.execvp("yazi", ["yazi", path])
    else:
        raise ValueError("Usage: open.py click|run")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, OSError, RuntimeError) as error:
        print(f"Yazi: {error}", file=sys.stderr)
        sys.exit(1)
