#!/usr/bin/env python3
"""Two real clients share one Yazi and stale-SSH server; no user's clipboard touched."""

import argparse, zlib, fcntl, json, os, pathlib, pty, shlex, socket, struct, subprocess, tempfile, termios, threading, time, uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]


def until(fn, label, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError("Timed out: " + label)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--herdr", type=pathlib.Path, required=True)
    parser.add_argument("--handoff-to", type=pathlib.Path)
    args = parser.parse_args()
    binary = str(args.herdr.resolve())
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="herdr-desktop-smoke-"))
    print("Artifacts:", tmp, flush=True)
    session = "desktop-" + uuid.uuid4().hex[:12]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR_", "SSH_"))}
    env.update(
        HOME=str(tmp),
        XDG_CONFIG_HOME=str(tmp / "config"),
        XDG_STATE_HOME=str(tmp / "state"),
        XDG_CACHE_HOME=str(tmp / "cache"),
        TERM="xterm-256color",
        SHELL="/bin/sh",
    )
    config = tmp / "config/herdr"
    config.mkdir(parents=True)
    (config / "config.toml").write_text(
        'onboarding=false\n[terminal]\ndefault_shell="/bin/sh"\n'
    )
    fixtures = tmp / "files"
    fixtures.mkdir()
    target = fixtures / "test file.txt"
    target.write_text("desktop routing fixture\n")
    bindir = tmp / "bin"
    bindir.mkdir()
    record = tmp / "desktop.jsonl"
    (bindir / "ripdrag").write_text(
        "#!/usr/bin/env python3\nimport os,sys,json\nwith open("
        + repr(str(record))
        + ',"a") as f: f.write(json.dumps({"display":os.getenv("DISPLAY"),"args":sys.argv[1:]})+"\\n")\n'
    )
    (bindir / "ripdrag").chmod(0o755)

    def png(red):
        def chunk(kind, data):
            return (
                struct.pack("!I", len(data))
                + kind
                + data
                + struct.pack("!I", zlib.crc32(kind + data))
            )

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack("!IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes([0, red, 0, 255 - red, 255])))
            + chunk(b"IEND", b"")
        )

    pngs = {":a": png(255), ":b": png(0), ":c": png(127), ":d": png(64)}
    reads = tmp / "clipboard-reads.jsonl"
    (bindir / "wl-paste").write_text(
        "#!/usr/bin/env python3\nimport os,sys\nwith open("
        + repr(str(reads))
        + ',"a") as f: f.write(os.environ["DISPLAY"]+"\\n")\nsys.stdout.buffer.write('
        + repr(pngs)
        + '[os.environ["DISPLAY"]])\n'
    )
    (bindir / "wl-paste").chmod(0o755)
    clipboard_log = tmp / "clipboard.jsonl"
    (bindir / "wl-copy").write_text(
        "#!/usr/bin/env python3\nimport os,sys,json\nwith open("
        + repr(str(clipboard_log))
        + ',"a") as f: f.write(json.dumps([os.getenv("DISPLAY"),sys.stdin.read()])+"\\n")\n'
    )
    (bindir / "wl-copy").chmod(0o755)
    env["PATH"] = str(bindir) + ":" + env["PATH"]
    yc = tmp / "config/yazi"
    (yc / "plugins/herdr-drag.yazi").mkdir(parents=True)
    (yc / "keymap.toml").write_text(
        '[[mgr.prepend_keymap]]\non="<C-g>"\nrun="plugin herdr-drag"\n'
    )
    (yc / "init.lua").write_text('require("herdr-drag"):setup()\n')
    opened = tmp / "opened.jsonl"
    opener = tmp / "open-probe.py"
    opener.write_text(
        "import sys,json\nsys.path.insert(0,"
        + repr(str(ROOT))
        + ")\nimport drag\ndef record(argv,**kw):\n with open("
        + repr(str(opened))
        + ',"a") as f: f.write(json.dumps({"argv":argv,"display":kw["env"].get("DISPLAY")})+"\\n")\ndrag.subprocess.Popen=record\ndrag.submit(sys.argv[1:],action="open")\n'
    )
    run = shlex.join(["python3", str(opener)]) + " %s"
    (yc / "yazi.toml").write_text(
        "[opener]\nprobe=[{run="
        + json.dumps(run)
        + ',orphan=true}]\n[open]\nrules=[{url="*",use="probe"}]\n'
    )

    (yc / "plugins/herdr-drag.yazi/main.lua").write_text(
        (ROOT / "yazi/herdr-drag.yazi/main.lua")
        .read_text()
        .replace('"@HERDR_DRAG_HELPER@"', json.dumps(str(ROOT / "drag.py")))
    )
    server_env = dict(
        env, SSH_CONNECTION="old ssh", DISPLAY=":old", WAYLAND_DISPLAY="old"
    )
    server = subprocess.Popen(
        [binary, "--session", session, "server"],
        env=server_env,
        stdout=(tmp / "server.log").open("w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    clients = []
    sock = config / "sessions" / session / "herdr.sock"

    def api(method, params=None):
        with socket.socket(socket.AF_UNIX) as c:
            c.settimeout(5)
            c.connect(str(sock))
            c.sendall(
                (
                    json.dumps(
                        {"id": "desktop-test", "method": method, "params": params or {}}
                    )
                    + "\n"
                ).encode()
            )
            result = json.loads(c.makefile("rb").readline(2000000))
        if "error" in result:
            raise RuntimeError(str(result["error"]))
        return result["result"]

    def client(display, **extra_env):
        m, s = pty.openpty()
        fcntl.ioctl(s, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 160, 0, 0))
        process = subprocess.Popen(
            [binary, "--session", session],
            env=dict(env, DISPLAY=display, WAYLAND_DISPLAY="test-wayland", **extra_env),
            stdin=s,
            stdout=s,
            stderr=s,
            start_new_session=True,
        )
        os.close(s)
        log = (tmp / ("client-" + display[1:] + ".log")).open("wb")

        def drain():
            try:
                while True:
                    data = os.read(m, 65536)
                    if not data:
                        break
                    log.write(data)
                    log.flush()
            except OSError:
                pass

        threading.Thread(target=drain, daemon=True).start()
        clients.append((process, m))
        return process, m

    try:
        until(sock.exists, "server socket")
        a, am = client(":a")
        time.sleep(1)
        pane = until(lambda: api("pane.list")["panes"], "initial pane")[0]["pane_id"]
        api(
            "pane.send_input",
            {
                "pane_id": pane,
                "text": shlex.join(["yazi", str(target)]),
                "keys": ["enter"],
            },
        )

        def screen():
            return api(
                "pane.read", {"pane_id": pane, "source": "visible", "format": "text"}
            )["read"]["text"]

        until(lambda: "NOR" in screen(), "Yazi")

        def count():
            return len(record.read_text().splitlines()) if record.exists() else 0

        for master, display in [(am, ":a")]:
            os.write(master, b"\x07")
            until(lambda: count() == 1, "first Ctrl-G")
            assert json.loads(record.read_text().splitlines()[-1])["display"] == display
        b, bm = client(":b")
        time.sleep(1)
        os.write(bm, b"\x07")
        until(lambda: count() == 2, "second client Ctrl-G")
        assert json.loads(record.read_text().splitlines()[-1])["display"] == ":b"
        os.write(am, b"\x07")
        until(lambda: count() == 3, "switch back Ctrl-G")
        rows = [json.loads(x) for x in record.read_text().splitlines()]
        assert [x["display"] for x in rows] == [":a", ":b", ":a"]
        assert all(x["args"][-1] == str(target) for x in rows)
        print(
            "PASS same Yazi: client A -> B -> A, stale SSH/server desktop ignored",
            flush=True,
        )
        # A consumed request cannot be re-used, even if another client is now foreground.
        try:
            api("pane.desktop.take", {"pane_id": pane})
        except RuntimeError as error:
            assert "no matching desktop request" in str(error)
        else:
            raise AssertionError("request replay accepted")
        print("PASS desktop gesture cannot be replayed", flush=True)
        for index, (master, display) in enumerate([(am, ":a"), (bm, ":b")], 1):
            # Enter has a short ambiguity lease because programs do not echo an input nonce.
            if index > 1:
                time.sleep(5.1)
            os.write(master, b"\r")
            until(
                lambda: (
                    opened.exists() and len(opened.read_text().splitlines()) == index
                ),
                "client Enter opener",
            )
            assert json.loads(opened.read_text().splitlines()[-1])["display"] == display
        print("PASS Enter uses the current client in the same Yazi pane", flush=True)

        api("pane.send_keys", {"pane_id": pane, "keys": ["q"]})
        time.sleep(0.3)
        pasted = tmp / "pasted.jsonl"
        probe = tmp / "probe.py"
        probe.write_text(
            'import sys,json,pathlib\nprint("PROBE_READY",flush=True)\nfor line in sys.stdin:\n if line.strip()=="copy": print("\\x1b]52;c;dGVzdA==\\x07",end="",flush=True)\n else:\n  with open('
            + repr(str(pasted))
            + ',"a") as f: f.write(json.dumps(line.strip())+"\\n")\n'
        )
        api(
            "pane.send_input",
            {
                "pane_id": pane,
                "text": shlex.join(["python3", str(probe)]),
                "keys": ["enter"],
            },
        )
        until(lambda: "PROBE_READY" in screen(), "image probe")
        for index, (master, display) in enumerate([(am, ":a"), (bm, ":b")], 1):
            os.write(master, b"\x16")
            time.sleep(0.5)
            os.write(master, b"\r")
            until(
                lambda: (
                    pasted.exists() and len(pasted.read_text().splitlines()) == index
                ),
                "client image paste",
            )
            path = pathlib.Path(json.loads(pasted.read_text().splitlines()[-1]))
            assert path.read_bytes() == pngs[display], "Image came from wrong clipboard"
        print(
            "PASS local image paste reads each client clipboard despite stale server environment",
            flush=True,
        )
        os.write(am, b"copy\r")
        time.sleep(0.5)
        assert not clipboard_log.exists(), (
            "Shared pane copied into an ambiguous clipboard"
        )
        b.terminate()
        b.wait(timeout=5)
        time.sleep(0.3)
        os.write(am, b"copy\r")
        until(clipboard_log.exists, "single-viewer clipboard")
        assert json.loads(clipboard_log.read_text().splitlines()[-1]) == [":a", "test"]
        print(
            "PASS OSC 52 refuses shared pane and copies to sole input owner after disconnect",
            flush=True,
        )
        a.terminate()
        a.wait(timeout=5)
        c, cm = client(":c")
        time.sleep(1)
        os.write(cm, b"\x16")
        time.sleep(0.5)
        os.write(cm, b"\r")
        until(
            lambda: len(pasted.read_text().splitlines()) == 3,
            "reconnected client image",
        )
        path = pathlib.Path(json.loads(pasted.read_text().splitlines()[-1]))
        assert path.read_bytes() == pngs[":c"]
        os.write(cm, b"copy\r")
        until(
            lambda: len(clipboard_log.read_text().splitlines()) == 2,
            "reconnected clipboard owner",
        )
        assert json.loads(clipboard_log.read_text().splitlines()[-1]) == [":c", "test"]
        print(
            "PASS reconnect uses a new desktop for image paste and text copy",
            flush=True,
        )

        ssh, ssh_master = client(
            ":ssh", SSH_CONNECTION="ssh-only", HERDR_DRAG_RECEIVER_ID="f" * 32
        )
        time.sleep(1)
        reads_before = reads.read_text()
        os.write(ssh_master, b"\x16")
        time.sleep(0.3)
        assert reads.read_text() == reads_before, "Plain SSH read a desktop clipboard"
        os.write(ssh_master, b"\x07")
        time.sleep(0.3)
        route = api("pane.desktop.take", {"pane_id": pane, "action": "drag"})["context"]
        assert (
            not route["local_to_server"]
            and not route.get("receiver_id")
            and not route.get("desktop_env")
        )
        ssh.terminate()
        ssh.wait(timeout=5)
        print(
            "PASS plain SSH cannot borrow the server desktop or an inherited receiver",
            flush=True,
        )

        if args.handoff_to:
            os.write(cm, b"\x07")
            time.sleep(0.3)
            before = api("pane.process_info", {"pane_id": pane})["process_info"]
            destination = str(args.handoff_to.resolve())
            with (tmp / "handoff.log").open("w") as log:
                subprocess.run(
                    [
                        binary,
                        "--session",
                        session,
                        "server",
                        "live-handoff",
                        "--import-exe",
                        destination,
                    ],
                    env=env,
                    check=True,
                    timeout=45,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            binary = destination
            after = api("pane.process_info", {"pane_id": pane})["process_info"]
            for key in ("pane_id", "shell_pid", "foreground_process_group_id"):
                assert before[key] == after[key], "Handoff changed " + key
            try:
                api("pane.desktop.take", {"pane_id": pane, "action": "drag"})
            except RuntimeError as error:
                assert "no matching desktop request" in str(error)
            else:
                raise AssertionError("Old desktop request survived handoff")
            c.wait(timeout=10)
            d, dm = client(":d")
            time.sleep(1)
            # Reset the probe's line buffer after the SSH key checks.
            os.write(dm, b"\x03")
            time.sleep(0.3)
            api(
                "pane.send_input",
                {
                    "pane_id": pane,
                    "text": shlex.join(["yazi", str(target)]),
                    "keys": ["enter"],
                },
            )
            until(lambda: "NOR" in screen(), "Yazi after handoff")
            before_count = count()
            os.write(dm, b"\x07")
            until(lambda: count() == before_count + 1, "new client route after handoff")
            assert json.loads(record.read_text().splitlines()[-1])["display"] == ":d"
            print(
                "PASS live handoff preserves processes, forgets old requests and registers new client",
                flush=True,
            )

    finally:
        for process, m in clients:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)
            os.close(m)
        try:
            api("server.stop")
        except Exception:
            pass
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
