#!/usr/bin/env python3
"""Install the Yazi Ctrl+G handler without replacing other key bindings."""
import argparse
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import tomllib

ROOT = Path(__file__).resolve().parents[1]
HEADER = re.compile(r"(?m)^[ \t]*\[\[?[^\n]*?\]\]?[ \t]*(?:#[^\n]*)?$")
BINDING = '\n[[mgr.prepend_keymap]]\non = "<C-g>"\nrun = "plugin herdr-drag"\ndesc = "Send files to local ripdrag"\n'
INIT_BEGIN = '-- BEGIN herdr-yazi-links progress'
INIT_END = '-- END herdr-yazi-links progress'
INIT_BLOCK = INIT_BEGIN + '\nrequire("herdr-drag"):setup()\n' + INIT_END


def update_init(source):
    if source.count(INIT_BEGIN) != source.count(INIT_END) or source.count(INIT_BEGIN) > 1:
        raise ValueError('Invalid managed herdr-drag block in init.lua; configuration was not changed')
    if INIT_BEGIN in source:
        start, end = source.index(INIT_BEGIN), source.index(INIT_END) + len(INIT_END)
        if end < start:
            raise ValueError('Invalid managed herdr-drag block order in init.lua')
        return source[:start] + INIT_BLOCK + source[end:]
    return source + ('\n' if source and not source.endswith('\n') else '') + INIT_BLOCK + '\n'


def update_keymap(source):
    """Change only the existing Ctrl+G run value, or append one binding."""
    parsed = tomllib.loads(source)
    entries = parsed.get('mgr', {}).get('prepend_keymap', [])
    targets = [entry for entry in entries if entry.get('on') in ('<C-g>', ['<C-g>'])]
    if len(targets) > 1:
        raise ValueError('Multiple mgr.prepend_keymap Ctrl+G bindings; resolve the duplicate first')
    if not targets:
        result = source.rstrip('\n') + '\n' + BINDING
        tomllib.loads(result)
        return result
    if targets[0].get('run') == 'plugin herdr-drag':
        return source
    headers = list(HEADER.finditer(source))
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(source)
        block = source[header.start():end]
        try:
            entries = tomllib.loads(block).get('mgr', {}).get('prepend_keymap', [])
        except tomllib.TOMLDecodeError:
            continue
        if not entries or entries[0].get('on') not in ('<C-g>', ['<C-g>']):
            continue
        # Handle the normal string and string-array spelling, including multiline.
        # Parsing the replacement verifies that nothing else changed semantically.
        run = re.search(r'(?m)^[ \t]*run[ \t]*=', block)
        if not run:
            raise ValueError('Ctrl+G binding has no editable run assignment')
        value_start = run.end()
        for value_end in range(value_start + 1, len(block) + 1):
            try:
                value = tomllib.loads('run = ' + block[value_start:value_end])
            except tomllib.TOMLDecodeError:
                continue
            if value != {'run': entries[0].get('run')}:
                continue
            result = source[:header.start() + value_start] + ' "plugin herdr-drag"' + source[header.start() + value_end:]
            expected = tomllib.loads(source)
            for entry in expected['mgr']['prepend_keymap']:
                if entry.get('on') in ('<C-g>', ['<C-g>']):
                    entry['run'] = 'plugin herdr-drag'
            if tomllib.loads(result) != expected:
                continue
            return result
    raise ValueError('Use [[mgr.prepend_keymap]] blocks for Ctrl+G before installing; configuration was not changed')


def lua_string(value):
    """A Lua quoted UTF-8 string, including control characters and backslashes."""
    return '"' + ''.join('\\' + c if c in '\\"' else ('\\%03d' % ord(c) if ord(c) < 32 or ord(c) == 127 else c) for c in value) + '"'


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(content)
        if path.exists():
            shutil.copymode(path, temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(config_dir, root=ROOT):
    config_dir = Path(config_dir).expanduser()
    keymap = config_dir / 'keymap.toml'
    source = keymap.read_text(encoding='utf-8') if keymap.exists() else ''
    updated = update_keymap(source)
    init = config_dir / 'init.lua'
    init_source = init.read_text(encoding='utf-8') if init.exists() else ''
    init_updated = update_init(init_source)
    template = (ROOT / 'yazi/herdr-drag.yazi/main.lua').read_text(encoding='utf-8')
    plugin = template.replace('"@HERDR_DRAG_HELPER@"', lua_string(str((root / 'drag.py').resolve())))
    backup = None
    if source != updated and keymap.exists():
        backup = keymap.with_name('keymap.toml.herdr-drag-backup-' + str(time.time_ns()))
        shutil.copy2(keymap, backup)
    destination = config_dir / 'plugins/herdr-drag.yazi/main.lua'
    if not destination.exists() or destination.read_text(encoding='utf-8') != plugin:
        atomic_write(destination, plugin)
    if source != updated:
        atomic_write(keymap, updated)
    if init_source != init_updated:
        if init.exists():
            shutil.copy2(init, init.with_name('init.lua.herdr-drag-backup-' + str(time.time_ns())))
        atomic_write(init, init_updated)
    return destination, backup


def main():
    default = os.environ.get('YAZI_CONFIG_HOME') or str(Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'yazi')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config-dir', default=default, help='Yazi config directory; default respects YAZI_CONFIG_HOME and XDG_CONFIG_HOME')
    parser.add_argument('--root', type=Path, default=ROOT, help='Checkout path on the target machine; permits preparing a remote install locally')
    args = parser.parse_args()
    try:
        destination, backup = install(args.config_dir, args.root)
    except (OSError, ValueError) as exc:
        parser.exit(1, 'Install failed: ' + str(exc) + '\n')
    print('Installed ' + str(destination))
    if backup:
        print('Previous keymap: ' + str(backup))
    print('New Yazi processes use Ctrl+G. Existing processes were not restarted.')


if __name__ == '__main__':
    main()
