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
        with patch.dict(os.environ, {"YAZI_LINK_PATH": value}), patch.object(links.sys, "argv", ["open.py", "run"]), patch.object(links.os, "execvp") as execute:
            links.main()
        execute.assert_called_once_with("yazi", ["yazi", value])


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
