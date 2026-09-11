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

    def test_init_preserves_user_setup_and_backs_up_once(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            source = '-- user settings\nrequire("other"):setup()\n'
            init = config / 'init.lua'
            init.write_text(source)
            INSTALL.install(config)
            self.assertTrue(init.read_text().startswith(source))
            self.assertEqual(init.read_text().count('require("herdr-drag"):setup()'), 1)
            backups = list(config.glob('init.lua.herdr-drag-backup-*'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), source)
            INSTALL.install(config)
            self.assertEqual(len(list(config.glob('init.lua.herdr-drag-backup-*'))), 1)

    def test_invalid_init_markers_leave_config_untouched(self):
        for source in (INSTALL.INIT_BEGIN, INSTALL.INIT_END + '\n' + INSTALL.INIT_BEGIN):
            with tempfile.TemporaryDirectory() as directory:
                config = Path(directory)
                (config / 'init.lua').write_text(source)
                with self.assertRaises(ValueError):
                    INSTALL.install(config)
                self.assertEqual((config / 'init.lua').read_text(), source)
                self.assertFalse((config / 'keymap.toml').exists())


@unittest.skipUnless(shutil.which('lua'), 'Lua interpreter unavailable')
class PluginTests(unittest.TestCase):
    def test_selection_arguments_local_fallback_and_error_notifications(self):
        # Execute the real plugin with the documented Yazi API shape; no shell
        # parsing is involved in the helper argv, including control characters.
        script = r'''
local emitted, commands, rendered = nil, {}, {}
local env, state, children = {}, {}, {}
os.getenv = function(key) return env[key] end
local frames = {}
local id = string.rep("a", 32)
local function draw()
  if children[1] then rendered[#rendered + 1] = children[1]({_area={w=100}}) end
end
ya = {
  sync = function(fn) return function(...) return fn(state, ...) end end,
  emit = function(action, args) emitted = { action, args } end,
  sleep = function() end,
  json_decode = function(text)
    if text == "submit" then return {id=id} end
    return frames[text]
  end,
}
ui = {
  render = draw,
  truncate = function(text) return text end,
  Span = function(text) return {fg=function() return text end} end,
  Line = function(parts) return table.concat(parts) end,
}
Status = {RIGHT=1, children_add=function(self, fn) children[#children+1]=fn; return #children end}
cx = { active = { selected = {}, current = { hovered = { url = "/tmp/current" } } } }
local failure, watcher_error = false, false
Command = setmetatable({PIPED=1}, {__call=function(_, program)
  assert(program == "python3")
  local captured = {}
  commands[#commands+1] = captured
  return {
    arg = function(self, args) for _, a in ipairs(args) do captured[#captured+1]=a end; return self end,
    stdout = function(self) return self end,
    stderr = function(self) return self end,
    output = function(self)
      return {status={success=not failure}, stdout="submit", stderr="No receiver"}
    end,
    spawn = function(self)
      if watcher_error then return nil, "Watch failed" end
      local lines = {"progress", "done"}
      return {
        read_line=function() if #lines == 0 then return nil, 2 end; return table.remove(lines,1), 0 end,
        wait=function() return {success=true} end,
      }
    end,
  }
end})
frames.progress={id=id, state="downloading", file_index=2, file_count=5, percent=43, bytes_done=43, bytes_total=100}
frames.done={id=id, state="done", percent=100}
local plugin = dofile(arg[1])
plugin.setup(state); plugin.setup(state)
assert(#children == 1, "setup must be idempotent")
plugin.entry()
assert(emitted[1] == "shell" and emitted[2][1] == "ripdrag -x -a -n -b %s")
assert(#commands == 0)
env.HERDR_ENV, env.HERDR_SESSION = "1", "test"
plugin.entry()
assert(commands[1][2] == "submit" and commands[1][3] == "--" and commands[1][4] == "/tmp/current")
assert(commands[2][2] == "watch" and commands[2][3] == id)
assert(table.concat(rendered):find("2/5 43%%"))
assert(table.concat(rendered):find("Drag: ready"))
assert(children[1]({_area={w=100}})=="", "success must clear")
local paths = { "/tmp/a b'\"$;\n.txt", "/tmp/путь/file.txt", "/tmp/other/file.txt" }
cx.active.selected = {}
for _, path in ipairs(paths) do table.insert(cx.active.selected, {url=path}) end
commands={}
plugin.entry()
for i,path in ipairs(paths) do assert(commands[1][i+3]==path) end
cx.active.selected = {["/tmp/old-api-selected"]=true}
commands={}; plugin.entry(); assert(commands[1][4]=="/tmp/old-api-selected")
failure=true; plugin.entry()
assert(children[1]({_area={w=100}}):find("No receiver"))
cx.active.selected, cx.active.current.hovered = {}, nil
commands={}; plugin.entry()
assert(#commands==0 and children[1]({_area={w=100}}):find("No file selected"))
-- Remote error is persistent and control characters are rendered as spaces.
failure=false; cx.active.current.hovered={url="/tmp/file"}
frames.done={id=id,state="error",message="failure\ntext"}
plugin.entry()
assert(children[1]({_area={w=100}}):find("failure text"))
watcher_error=true; plugin.entry()
assert(children[1]({_area={w=100}}):find("Watch failed"))
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
