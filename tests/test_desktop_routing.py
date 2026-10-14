"""Desktop routing contract: real API sockets, fail-closed routing and GUI argv."""

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("desktop_drag", ROOT / "drag.py")
drag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drag)


@contextmanager
def endpoint(reply):
    """A single-use Unix API endpoint; record the actual request on the wire."""
    with (
        tempfile.TemporaryDirectory() as tmp,
        socket.socket(socket.AF_UNIX) as listener,
    ):
        address = str(Path(tmp) / "herdr.sock")
        listener.bind(address)
        listener.listen(1)
        listener.settimeout(4)
        requests, errors = [], []

        def respond():
            try:
                with listener.accept()[0] as connection:
                    connection.settimeout(4)
                    with connection.makefile("rb") as stream:
                        requests.append(json.loads(stream.readline()))
                    connection.sendall(
                        reply if isinstance(reply, bytes) else drag.packet(reply)
                    )
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=respond, daemon=True)
        thread.start()
        try:
            with patch.dict(
                os.environ,
                {"HERDR_SOCKET_PATH": address, "HERDR_PANE_ID": "w1:p9"},
                clear=True,
            ):
                yield requests
        finally:
            thread.join(5)
            if thread.is_alive():
                raise AssertionError("API fixture did not stop")
            if errors:
                raise errors[0]


class RoutingApiTests(unittest.TestCase):
    def test_both_actions_send_the_owning_pane_and_return_exact_context(self):
        context = {"local_to_server": False, "receiver_id": "a" * 32, "desktop_env": {}}
        for action in ("drag", "open"):
            with (
                self.subTest(action=action),
                endpoint({"result": {"context": context}}) as requests,
            ):
                self.assertEqual(drag.desktop_route(action), context)
                self.assertEqual(requests[0]["method"], "pane.desktop.take")
                self.assertEqual(
                    requests[0]["params"], {"pane_id": "w1:p9", "action": action}
                )

    def test_no_server_or_no_pane_keeps_standalone_legacy_behavior(self):
        for env in ({}, {"HERDR_SOCKET_PATH": "/missing"}, {"HERDR_PANE_ID": "w1:p1"}):
            with (
                self.subTest(env=env),
                patch.dict(os.environ, env, clear=True),
                patch.object(drag.socket, "socket") as connect,
            ):
                self.assertIsNone(drag.desktop_route())
                connect.assert_not_called()

    def test_only_an_unknown_method_allows_old_server_fallback(self):
        for code, message in (
            ("unknown_method", "Unknown method pane.desktop.take"),
            ("unknown_method", "unknown method: pane.desktop.take"),
            ("invalid_request", "unknown variant `pane.desktop.take`, expected `ping`"),
        ):
            with (
                self.subTest(code=code),
                endpoint(
                    {
                        "error": {
                            "code": code,
                            "message": message,
                        }
                    }
                ),
            ):
                self.assertIsNone(drag.desktop_route())

    def test_errors_on_new_server_never_start_a_local_program(self):
        errors = [
            ("desktop_unavailable", "Originating client disconnected"),
            ("desktop_unavailable", "Desktop request expired"),
            ("desktop_unavailable", "Overlapping requests"),
            ("invalid_request", "Malformed pane identifier"),
            ("invalid_request", "Malformed params for pane.desktop.take"),
            ("invalid_request", "unknown variant `other`, expected `pane.desktop.take`"),
            ("permission_denied", "pane.desktop.take denied"),
            ("unknown_method", "Some other missing method"),
        ]
        for code, message in errors:
            with (
                self.subTest(code=code, message=message),
                endpoint({"error": {"code": code, "message": message}}),
                patch.object(drag.subprocess, "Popen") as spawn,
            ):
                with self.assertRaisesRegex(RuntimeError, message):
                    drag.submit(["/tmp/file"])
                spawn.assert_not_called()

    def test_malformed_api_context_never_reenters_legacy_routing(self):
        replies = [
            None,
            [],
            {"result": None},
            {"result": {}},
            {"result": {"context": None}},
            {"result": {"context": {}}},
            {"result": {"context": {"local_to_server": "false"}}},
            {"result": {"context": {"local_to_server": True, "desktop_env": []}}},
            {"error": "unstructured error"},
            {"error": {"code": "invalid_request", "message": None}},
        ]
        for reply in replies:
            with (
                self.subTest(reply=reply),
                endpoint(reply),
                patch.object(drag.subprocess, "Popen") as spawn,
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "Invalid desktop routing response"
                ):
                    drag.submit(["/tmp/file"])
                spawn.assert_not_called()

    def test_missing_socket_and_truncated_reply_fail_closed(self):
        with (
            patch.dict(
                os.environ,
                {
                    "HERDR_SOCKET_PATH": "/no-such-desktop-api.sock",
                    "HERDR_PANE_ID": "w1:p1",
                },
                clear=True,
            ),
            patch.object(drag.subprocess, "Popen") as spawn,
        ):
            with self.assertRaises(OSError):
                drag.submit(["/tmp/file"])
            spawn.assert_not_called()
        with endpoint(b'{"result":\n'), patch.object(drag.subprocess, "Popen") as spawn:
            with self.assertRaises(ValueError):
                drag.submit(["/tmp/file"])
            spawn.assert_not_called()


class RoutingTests(unittest.TestCase):
    def test_current_client_desktop_replaces_all_stale_panel_desktop_values(self):
        stale = {
            key: "old"
            for key in (
                "DISPLAY",
                "WAYLAND_DISPLAY",
                "XAUTHORITY",
                "XDG_RUNTIME_DIR",
                "DBUS_SESSION_BUS_ADDRESS",
                "XDG_CURRENT_DESKTOP",
                "XDG_SESSION_TYPE",
                "SSH_CONNECTION",
                "SSH_CLIENT",
                "SSH_TTY",
            )
        }
        stale.update(PATH="/bin", LANG="ru_RU.UTF-8", HERDR_PANE_ID="w1:p1")
        supplied = {
            "DISPLAY": ":new",
            "PATH": "/bad",
            "SSH_CONNECTION": "bad",
            "LD_PRELOAD": "/bad",
            "XAUTHORITY": "bad\0path",
            "XDG_SESSION_TYPE": 12,
        }
        with patch.dict(os.environ, stale, clear=True):
            env = drag.local_desktop_env({"desktop_env": supplied})
        self.assertEqual(
            env,
            {
                "DISPLAY": ":new",
                "PATH": "/bin",
                "LANG": "ru_RU.UTF-8",
                "HERDR_PANE_ID": "w1:p1",
            },
        )

    def test_empty_native_context_clears_server_display_without_mutating_process(self):
        with patch.dict(os.environ, {"DISPLAY": ":server", "PATH": "/bin"}, clear=True):
            self.assertEqual(
                drag.local_desktop_env({"desktop_env": {}}), {"PATH": "/bin"}
            )
            self.assertEqual(os.environ["DISPLAY"], ":server")

    def test_legacy_context_preserves_environment(self):
        with patch.dict(os.environ, {"DISPLAY": ":legacy", "PATH": "/bin"}, clear=True):
            self.assertEqual(drag.local_desktop_env(None), dict(os.environ))

    def test_remote_client_without_valid_receiver_never_uses_server_desktop(self):
        for receiver in (None, "", "../escape", "A" * 32, "a" * 31, "a" * 33, 123):
            for action in ("drag", "open"):
                with (
                    self.subTest(receiver=receiver, action=action),
                    patch.dict(
                        os.environ,
                        {"HERDR_SESSION": "test", "HERDR_DRAG_LOCAL": "1"},
                        clear=True,
                    ),
                    patch.object(
                        drag,
                        "desktop_route",
                        return_value={
                            "local_to_server": False,
                            "receiver_id": receiver,
                        },
                    ),
                    patch.object(drag.subprocess, "Popen") as spawn,
                ):
                    with self.assertRaisesRegex(RuntimeError, "no desktop receiver"):
                        drag.submit(["/tmp/file"], action=action)
                    spawn.assert_not_called()

    def test_no_scoped_receiver_does_not_use_legacy_receiver_or_local_window(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ, {"HERDR_SESSION": "test", "XDG_STATE_HOME": tmp}, clear=True
            ),
            patch.object(
                drag,
                "desktop_route",
                return_value={"local_to_server": False, "receiver_id": "a" * 32},
            ),
            patch.object(drag.subprocess, "Popen") as spawn,
        ):
            state, _ = drag.locations("test")
            (state / "remote").touch()
            with self.assertRaisesRegex(RuntimeError, "No active local receiver"):
                drag.submit(["/tmp/file"])
            spawn.assert_not_called()

    def test_new_local_context_overrides_old_remote_marker_and_flag(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(
                os.environ,
                {
                    "HERDR_SESSION": "test",
                    "HERDR_DRAG_LOCAL": "0",
                    "XDG_STATE_HOME": tmp,
                },
                clear=True,
            ),
            patch.object(
                drag,
                "desktop_route",
                return_value={
                    "local_to_server": True,
                    "desktop_env": {"DISPLAY": ":new"},
                },
            ),
            patch.object(drag.subprocess, "Popen") as spawn,
        ):
            state, _ = drag.locations("test")
            (state / "remote").touch()
            spawn.return_value.returncode = 0
            drag.submit(["/tmp/file"])
            self.assertEqual(spawn.call_args.kwargs["env"]["DISPLAY"], ":new")
            self.assertTrue((state / "remote").exists())

    def test_ripdrag_start_failure_is_visible(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(drag.subprocess, "Popen") as spawn,
        ):

            def failed_launch(*args, **kwargs):
                kwargs["stderr"].write(b"Failed to open display")
                kwargs["stderr"].flush()
                return spawn.return_value

            spawn.side_effect = failed_launch
            spawn.return_value.returncode = 1
            with self.assertRaisesRegex(RuntimeError, "Failed to open display"):
                drag.submit(["/tmp/file"])

    def test_running_ripdrag_is_left_alive_and_gets_literal_file_arguments(self):
        paths = ['/tmp/雪 ";$(touch NEVER)\n.txt']
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(drag.subprocess, "Popen") as spawn,
        ):
            spawn.return_value.wait.side_effect = subprocess.TimeoutExpired(
                "ripdrag", 0.25
            )
            drag.submit(paths)
            self.assertEqual(
                spawn.call_args.args[0], ["ripdrag", "-x", "-a", "-n", "-b", *paths]
            )
            spawn.return_value.terminate.assert_not_called()
            spawn.return_value.kill.assert_not_called()

    def test_local_open_uses_os_opener_with_current_desktop_and_literal_paths(self):
        for platform, program in [
            ("darwin", "/usr/bin/open"),
            ("linux", "/usr/bin/xdg-open"),
        ]:
            paths = ["/tmp/a b.html", "/tmp/雪;$(touch NEVER).png"]
            with (
                self.subTest(platform=platform),
                patch.dict(os.environ, {"DISPLAY": ":old"}, clear=True),
                patch.object(drag.sys, "platform", platform),
                patch.object(
                    drag,
                    "desktop_route",
                    return_value={
                        "local_to_server": True,
                        "desktop_env": {"DISPLAY": ":new"},
                    },
                ),
                patch.object(drag.subprocess, "Popen") as spawn,
            ):
                drag.submit(paths, action="open")
                self.assertEqual(
                    [call.args[0] for call in spawn.call_args_list],
                    [[program, p] for p in paths],
                )
                self.assertTrue(
                    all(
                        call.kwargs["env"]["DISPLAY"] == ":new"
                        for call in spawn.call_args_list
                    )
                )

    def test_unknown_action_is_rejected_before_consuming_context_or_spawning(self):
        with (
            patch.object(drag, "desktop_route") as route,
            patch.object(drag.subprocess, "Popen") as spawn,
        ):
            for action in ("sh", "", None, ["open"]):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    drag.submit(["/tmp/file"], action=action)
            route.assert_not_called()
            spawn.assert_not_called()

    def test_wire_actions_are_not_commands(self):
        self.assertEqual(
            drag.validate({"paths": ["/tmp/file"], "action": "open"}), ["/tmp/file"]
        )
        with self.assertRaises(ValueError):
            drag.validate({"paths": ["/tmp/file"], "action": "sh"})


class DesktopProcessTests(unittest.TestCase):
    def test_late_stderr_does_not_kill_an_already_open_drag_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "still-alive"
            fake = root / "ripdrag"
            fake.write_text(
                "#!"
                + sys.executable
                + '\nimport sys,time,pathlib\ntime.sleep(.4)\nprint("late GTK warning",file=sys.stderr,flush=True)\npathlib.Path('
                + repr(str(marker))
                + ").touch()\n"
            )
            fake.chmod(0o755)
            processes = []
            real_spawn = subprocess.Popen

            def spawn(*args, **kwargs):
                child = real_spawn(*args, **kwargs)
                processes.append(child)
                return child

            with (
                patch.dict(os.environ, {"PATH": tmp}, clear=True),
                patch.object(drag.subprocess, "Popen", side_effect=spawn),
            ):
                drag.submit(["/tmp/file"])
            try:
                self.assertEqual(processes[0].wait(timeout=5), 0)
                self.assertTrue(marker.exists())
            finally:
                if processes[0].poll() is None:
                    processes[0].kill()
                    processes[0].wait()
