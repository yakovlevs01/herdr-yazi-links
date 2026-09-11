import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('install_drag', ROOT / 'scripts/install-drag.py')
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)


class InstallerTests(unittest.TestCase):
    def test_changes_only_ctrl_g_command_and_preserves_comments(self):
        source = '''# user configuration
[[mgr.prepend_keymap]]
on = "<C-g>"
run = 'shell -- ripdrag -x -a -n -b %s' # keep this
desc = "Drag files"

[[mgr.prepend_keymap]]
on = "<C-e>"
run = "other user command"

[[input.prepend_keymap]]
on = "<C-g>"
run = "close"
'''
        expected = source.replace("'shell -- ripdrag -x -a -n -b %s'", '"plugin herdr-drag"')
        self.assertEqual(INSTALL.update_keymap(source), expected)
        self.assertEqual(INSTALL.update_keymap(expected), expected)

    def test_multiline_run_and_list_key(self):
        source = '''[[mgr.prepend_keymap]]
on = ["<C-g>"]
run = [
    "shell -- ripdrag -x -a -n -b %s",
    "escape",
] # retained
'''
        result = INSTALL.update_keymap(source)
        self.assertIn('run = "plugin herdr-drag" # retained', result)
        self.assertEqual(tomllib.loads(result)['mgr']['prepend_keymap'][0]['run'], 'plugin herdr-drag')

    def test_appends_binding_to_new_or_existing_config(self):
        for source in ('', '[mgr]\n', '[[mgr.prepend_keymap]]\non="a"\nrun="open"\n'):
            with self.subTest(source=source):
                result = INSTALL.update_keymap(source)
                self.assertEqual(tomllib.loads(result)['mgr']['prepend_keymap'][-1]['on'], '<C-g>')

    def test_rejects_ambiguous_and_invalid_configs_before_writing(self):
        for source in ('not valid TOML', INSTALL.BINDING + INSTALL.BINDING):
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory)
                path = config / 'keymap.toml'
                path.write_text(source)
                with self.assertRaises(ValueError):
                    INSTALL.install(config)
                self.assertEqual(path.read_text(), source)
                self.assertFalse((config / 'plugins').exists())

    def test_install_backup_idempotence_and_remote_helper_path(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            keymap = config / 'keymap.toml'
            source = '[[mgr.prepend_keymap]]\non="<C-g>"\nrun="old"\n'
            keymap.write_text(source)
            root = Path('/Users/test/remote "quoted" путь')
            plugin, backup = INSTALL.install(config, root)
            self.assertEqual(backup.read_text(), source)
            self.assertIn(INSTALL.lua_string(str(root / 'drag.py')), plugin.read_text())
            self.assertNotIn('@HERDR_DRAG_HELPER@', plugin.read_text())
            _, second_backup = INSTALL.install(config, root)
            self.assertIsNone(second_backup)
            self.assertEqual(len(list(config.glob('*backup*'))), 1)


@unittest.skipUnless(shutil.which('lua'), 'Lua interpreter unavailable')
class PluginTests(unittest.TestCase):
    def test_selection_arguments_local_fallback_and_error_notifications(self):
        # Execute the real plugin with the documented Yazi API shape; no shell
        # parsing is involved in the helper argv, including control characters.
        script = r'''
local notifications, emitted, captured = {}, nil, nil
local env = {}
os.getenv = function(key) return env[key] end
ya = {
  sync = function(fn) return fn end,
  emit = function(action, args) emitted = { action, args } end,
  notify = function(message) notifications[#notifications + 1] = message end,
  json_decode = function(_) return { message = "queued" } end,
}
cx = { active = { selected = {}, current = { hovered = { url = "/tmp/current" } } } }
local failure = false
Command = function(program)
  assert(program == "python3")
  captured = {}
  return {
    arg = function(self, args)
      for _, arg in ipairs(args) do captured[#captured + 1] = arg end
      return self
    end,
    output = function(self)
      return { status = { success = not failure }, stdout = "{}", stderr = "No receiver" }
    end,
  }
end
local plugin = dofile(arg[1])
plugin.entry()
assert(emitted[1] == "shell" and emitted[2][1] == "ripdrag -x -a -n -b %s")
assert(captured == nil)
env.HERDR_ENV, env.HERDR_SESSION = "1", "test"
plugin.entry()
assert(captured[2] == "submit" and captured[3] == "--" and captured[4] == "/tmp/current")
local paths = { "/tmp/a b'\"$;\n.txt", "/tmp/путь/file.txt", "/tmp/other/file.txt" }
cx.active.selected = {}
for _, path in ipairs(paths) do table.insert(cx.active.selected, { url = path }) end
plugin.entry()
assert(#captured == 6)
for i, path in ipairs(paths) do assert(captured[i + 3] == path) end
assert(notifications[#notifications].content == "queued")
cx.active.selected = { ["/tmp/old-api-selected"] = true }
plugin.entry()
assert(captured[4] == "/tmp/old-api-selected")
failure = true
plugin.entry()
assert(notifications[#notifications].level == "error")
assert(notifications[#notifications].content == "No receiver")
cx.active.selected, cx.active.current.hovered = {}, nil
captured = nil
plugin.entry()
assert(captured == nil and notifications[#notifications].level == "warn")
'''
        result = subprocess.run(['lua', '-', str(ROOT / 'yazi/herdr-drag.yazi/main.lua')], input=script, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_lua_path_literal_round_trip(self):
        path = '/tmp/path "quoted" \\ newline\n123\t Unicode путь/drag.py'
        result = subprocess.run(['lua', '-'], input='io.write(' + INSTALL.lua_string(path) + ')', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, path)


if __name__ == '__main__':
    unittest.main()
