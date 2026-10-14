import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("yazi_links", ROOT / "open.py")
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)


class YaziLinksTests(unittest.TestCase):
    def test_encoded_paths_and_unknown_hosts(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "отчёт #1%.txt"
            path.touch()
            self.assertEqual(links.file_path(path.as_uri()), path)
            for uri in ("https://example.com/file", "file://other-server" + str(path),
                        "file:relative.txt", "file:///missing-yazi-link", "file:///%00"):
                with self.assertRaises(ValueError):
                    links.file_path(uri)

    def test_click_targets_source_pane_and_preserves_filename_as_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "$(touch injected).txt"
            path.touch()
            env = {"HERDR_PLUGIN_CLICKED_URL": path.as_uri(),
                   "HERDR_PLUGIN_CONTEXT_JSON": json.dumps({"focused_pane_id": "w9:p7"})}
            with patch.dict(os.environ, env), patch.object(links.shutil, "which", return_value="/usr/bin/yazi"), patch.object(links, "request") as request:
                links.click()
            method, params = request.call_args.args
            self.assertEqual(method, "plugin.pane.open")
            self.assertEqual(params["target_pane_id"], "w9:p7")
            self.assertEqual(params["cwd"], tmp)
            self.assertEqual(params["env"], {"YAZI_LINK_PATH": str(path)})
            self.assertTrue(params["focus"])
            self.assertFalse((Path(tmp) / "injected").exists())

    def test_run_uses_argv_without_shell(self):
        value = "/tmp/a;echo wrong"
        with patch.dict(os.environ, {"YAZI_LINK_PATH": value}), patch.object(links.sys, "argv", ["open.py", "run"]), patch.object(links.os, "execvpe") as execute:
            links.main()
        self.assertEqual(execute.call_args.args[:2], ("yazi", ["yazi", value]))
        self.assertEqual(execute.call_args.args[2]["YAZI_LINK_PATH"], value)

    def test_click_passes_only_allowed_client_context_to_new_pane(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.html"
            path.touch()
            context = {"focused_pane_id": "w9:p7", "client_context": {
                "local_to_server": True,
                "desktop_env": {"DISPLAY": ":1", "PATH": "/untrusted", "TOKEN": "secret"}}}
            env = {"HERDR_PLUGIN_CLICKED_URL": path.as_uri(),
                   "HERDR_PLUGIN_CONTEXT_JSON": json.dumps(context)}
            with patch.dict(os.environ, env), patch.object(links.shutil, "which", return_value="/usr/bin/yazi"), patch.object(links, "request") as request:
                links.click()
            pane_env = request.call_args.args[1]["env"]
            self.assertEqual(json.loads(pane_env[links.CLIENT_CONTEXT_KEY]), {
                "local_to_server": True, "desktop_env": {"DISPLAY": ":1"}})

    def test_desktop_and_remote_clients_do_not_change_each_others_environment(self):
        server = {"DISPLAY": ":old", "WAYLAND_DISPLAY": "old", "PATH": "/bin",
                  "DBUS_SESSION_BUS_ADDRESS": "old", "SSH_CONNECTION": "old ssh",
                  "XDG_SESSION_ID": "old"}
        original = server.copy()
        for desktop in ({"DISPLAY": ":1"}, {"WAYLAND_DISPLAY": "wayland-2"}):
            local = links.yazi_environment({**server, links.CLIENT_CONTEXT_KEY: json.dumps({
                "local_to_server": True, "desktop_env": desktop})})
            self.assertEqual(local, {"PATH": "/bin", "HERDR_DRAG_LOCAL": "1", **desktop})
            remote = links.yazi_environment({**server, links.CLIENT_CONTEXT_KEY: json.dumps({
                "local_to_server": False, "desktop_env": desktop})})
            self.assertEqual(remote, {"PATH": "/bin", "HERDR_DRAG_LOCAL": "0"})
        self.assertEqual(server, original)

    def test_explicit_local_tty_clears_stale_desktop_but_legacy_keeps_it(self):
        server = {"DISPLAY": ":old", "PATH": "/bin"}
        self.assertEqual(links.yazi_environment(server), server)
        self.assertEqual(links.yazi_environment({**server, links.CLIENT_CONTEXT_KEY: json.dumps({
            "local_to_server": True, "desktop_env": {}})}), {"PATH": "/bin", "HERDR_DRAG_LOCAL": "1"})

    def test_malformed_context_is_rejected_before_exec(self):
        for value in ([], {}, {"local_to_server": "false"},
                      {"local_to_server": True, "desktop_env": []},
                      {"local_to_server": True, "desktop_env": {"DISPLAY": "a\0b"}},
                      {"local_to_server": True, "desktop_env": {"DISPLAY": 1}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                links.client_context(value)


if __name__ == "__main__":
    unittest.main()

class ManagedYaziTests(unittest.TestCase):
    def test_managed_binary_is_fallback_without_path_reordering(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / '.build/yazi/bin/yazi'
            binary.parent.mkdir(parents=True)
            binary.write_text('fixture')
            binary.chmod(0o755)
            with patch.object(links, 'ROOT', root):
                for version, expected in [('Yazi 25.5.31', str(binary)), ('Yazi 26.9.1', 'yazi')]:
                    with patch.object(links.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, version)):
                        self.assertEqual(links.yazi_command(), expected)
                with patch.object(links.subprocess, 'run', side_effect=FileNotFoundError):
                    self.assertEqual(links.yazi_command(), str(binary))
