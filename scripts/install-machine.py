#!/usr/bin/env python3
"""Install all components for this machine without touching live Herdr sessions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    print('+ ' + shlex.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def target(system=None, machine=None):
    pair = (system or platform.system(), machine or platform.machine())
    platforms = {('Linux', 'x86_64'): 'linux-x86_64', ('Darwin', 'arm64'): 'macos-aarch64'}
    if pair not in platforms:
        raise ValueError('No tested patched Herdr binary for %s/%s' % pair)
    return platforms[pair]


def backup(path, follow_symlinks=False):
    if path.exists() or path.is_symlink():
        destination = path.with_name(path.name + '.herdr-yazi-backup-' + str(time.time_ns()))
        shutil.copy2(path, destination, follow_symlinks=follow_symlinks)
        print('Backup: ' + str(destination))


def link(path, destination):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() and path.resolve() == destination.resolve():
        return
    backup(path)
    temporary = path.with_name('.' + path.name + '.' + str(os.getpid()))
    try:
        temporary.symlink_to(destination)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(url, destination, expected=None):
    """A download is never installed until fully received and verified."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            print('Download: ' + url, flush=True)
            with urllib.request.urlopen(url, timeout=60) as response:
                shutil.copyfileobj(response, stream)
            stream.close()
            if expected and digest(temporary) != expected:
                raise ValueError('SHA256 mismatch: ' + url)
            temporary.chmod(0o755)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)



def install_herdr(root, manifest, selected):
    binary = root / '.build/bin/herdr'
    entry = manifest['herdr'][selected]
    if not binary.exists() or digest(binary) != entry['sha256']:
        fetch(entry['url'], binary, entry['sha256'])
    binary.chmod(0o755)
    run([binary, '--version'])
    return binary


def compatible_yazi(binary="yazi", ya="ya"):
    if not shutil.which(str(binary)) or not shutil.which(str(ya)):
        return False
    result = subprocess.run([str(binary), '--version'], capture_output=True, text=True)
    version = re.search(r'\b(26)\.(\d+)\.(\d+)', result.stdout)
    return result.returncode == 0 and bool(version) and tuple(map(int, version.groups())) >= (26, 8, 15)


def install_yazi(root, selected, manifest):
    if compatible_yazi():
        return
    entry = manifest['yazi'][selected]
    archive = root / '.build/downloads/yazi.zip'
    fetch(entry['url'], archive, entry.get('sha256'))
    with zipfile.ZipFile(archive) as source:
        for name in ('yazi', 'ya'):
            matches = [item for item in source.infolist() if Path(item.filename).name == name and not item.is_dir()]
            if len(matches) != 1:
                raise ValueError('Unexpected Yazi archive contents')
            destination = root / '.build/yazi/bin' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.open(matches[0]) as src, destination.open('wb') as dst:
                shutil.copyfileobj(src, dst)
            destination.chmod(0o755)
            link(Path.home() / '.local/bin' / name, destination)
    if not compatible_yazi(root / '.build/yazi/bin/yazi', root / '.build/yazi/bin/ya'):
        raise ValueError('Downloaded Yazi could not run on this OS')
    if not compatible_yazi():
        print('Your PATH selects an older Yazi. Herdr file panes will use the managed Yazi; shell PATH priority stays unchanged.')


def packages(names):
    if platform.system() == 'Darwin':
        if not shutil.which('brew'):
            script = ROOT / '.build/downloads/homebrew-install.sh'
            fetch('https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh', script)
            run(['/bin/bash', script])
        run(['brew', 'install', *names['brew']])
    elif shutil.which('apt-get'):
        run(['sudo', 'apt-get', 'update'])
        run(['sudo', 'apt-get', 'install', '-y', *names['apt']])
    elif shutil.which('dnf'):
        run(['sudo', 'dnf', 'install', '-y', *names['dnf']])
    elif shutil.which('pacman'):
        run(['sudo', 'pacman', '-S', '--needed', '--noconfirm', *names['pacman']])
    else:
        raise ValueError('Supported Linux package managers: apt-get, dnf, pacman')


def install_receiver(root):
    if not shutil.which('ripdrag'):
        packages({'apt': ['libgtk-4-dev', 'build-essential', 'pkg-config', 'curl', 'ca-certificates'],
                  'dnf': ['gtk4-devel', 'gcc', 'gcc-c++', 'pkgconf-pkg-config', 'curl', 'ca-certificates'],
                  'pacman': ['gtk4', 'base-devel', 'curl', 'ca-certificates'],
                  'brew': ['gtk4', 'pkg-config', 'rust']})
        cargo = shutil.which('cargo')
        if not cargo:
            installer = root / '.build/downloads/rustup-init.sh'
            fetch('https://sh.rustup.rs', installer)
            run(['sh', installer, '-y', '--profile', 'minimal', '--no-modify-path'])
            cargo = str(Path.home() / '.cargo/bin/cargo')
        run([cargo, 'install', '--locked', 'ripdrag', '--version', '0.4.12', '--root', root / '.build/ripdrag'])
        link(Path.home() / '.local/bin/ripdrag', root / '.build/ripdrag/bin/ripdrag')
    python = root / '.build/drag-venv/bin/python'
    if not python.exists():
        try:
            run([sys.executable, '-m', 'venv', root / '.build/drag-venv'])
        except subprocess.CalledProcessError:
            packages({'apt': ['python3-venv'], 'dnf': ['python3-pip'], 'pacman': ['python-pip'], 'brew': ['python@3.13']})
            run([sys.executable, '-m', 'venv', root / '.build/drag-venv'])
    run([python, '-m', 'pip', 'install', 'paramiko>=3.4,<6'])
    run([python, '-c', 'import paramiko'])


def configure_path(home):
    marker = '# herdr-yazi-links: preserve existing PATH priority'
    snippet = '\n' + marker + '\ncase ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$PATH:$HOME/.local/bin" ;; esac\n'
    for name in ('.profile', '.bashrc', '.zshrc'):
        path = home / name
        text = path.read_text() if path.exists() else ''
        if marker not in text:
            backup(path, follow_symlinks=True)
            path.write_text(text + snippet)
    # Fish does not read the POSIX shell startup files.
    if Path(os.environ.get('SHELL', '')).name == 'fish':
        path = home / '.config/fish/conf.d/herdr-yazi-links.fish'
        content = '# herdr-yazi-links\ncontains -- "$HOME/.local/bin" $PATH; or set -gx PATH $PATH "$HOME/.local/bin"\n'
        if not path.exists() or path.read_text() != content:
            path.parent.mkdir(parents=True, exist_ok=True)
            backup(path, follow_symlinks=True)
            path.write_text(content)


def configure_checkout(root):
    canonical = Path.home() / 'pets/herdr-yazi-links'
    if canonical.resolve() == root.resolve():
        return
    if canonical.exists() or canonical.is_symlink():
        raise ValueError('Remote launcher expects ' + str(canonical) + '. Another checkout already occupies it. Run its install.sh or move it explicitly first.')
    link(canonical, root)


def check(root, manifest, selected, sender_only):
    binary = root / '.build/bin/herdr'
    checks = {
        'Python 3.11+': sys.version_info >= (3, 11),
        'pinned patched Herdr': binary.exists() and digest(binary) == manifest['herdr'][selected]['sha256'],
        'Yazi >=26.8.15, <27 and ya': compatible_yazi() or compatible_yazi(root / '.build/yazi/bin/yazi', root / '.build/yazi/bin/ya'),
        'SSH': bool(shutil.which('ssh')),
        'remote checkout path': (Path.home() / 'pets/herdr-yazi-links').resolve() == root.resolve(),
        'launcher': (Path.home() / '.local/bin/herdr-yazi').resolve() == (root / 'herdr-yazi').resolve(),
    }
    if (root / '.build/server-management.json').exists():
        checks['managed server unit'] = (Path.home() / '.config/systemd/user/herdr-yazi-server.service').exists()
        checks['managed server entry'] = (Path.home() / '.local/bin/herdr').resolve() == (root / 'scripts/herdr-entry.py').resolve()
        checks['managed server enabled in launcher'] = (root / '.build/server-management.json').exists()
    if not sender_only:
        python = root / '.build/drag-venv/bin/python'
        checks['ripdrag'] = bool(shutil.which('ripdrag'))
        checks['receiver Paramiko'] = python.exists() and subprocess.run([python, '-c', 'import paramiko'], capture_output=True).returncode == 0
    config = Path(os.environ.get('YAZI_CONFIG_HOME') or Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'yazi')
    plugin = config / 'plugins/herdr-drag.yazi/main.lua'
    expected = (root / 'yazi/herdr-drag.yazi/main.lua').read_text()
    # Install-drag renders only this path placeholder; compare the remaining code too.
    import importlib.util
    spec = importlib.util.spec_from_file_location('herdr_install_drag', root / 'scripts/install-drag.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    expected = expected.replace('"@HERDR_DRAG_HELPER@"', installer.lua_string(str((root / 'drag.py').resolve())))
    checks['Yazi drag plugin'] = plugin.exists() and plugin.read_text() == expected
    keymap = config / 'keymap.toml'
    try:
        entries = tomllib.loads(keymap.read_text()).get('mgr', {}).get('prepend_keymap', [])
        bindings = [entry for entry in entries if entry.get('on') in ('<C-g>', ['<C-g>'])]
        checks['Ctrl+G binding'] = len(bindings) == 1 and bindings[0].get('run') == 'plugin herdr-drag'
    except (OSError, ValueError):
        checks['Ctrl+G binding'] = False
    init = config / 'init.lua'
    checks['Yazi progress setup'] = init.exists() and installer.INIT_BLOCK in init.read_text()
    for name, ready in checks.items():
        print(('OK      ' if ready else 'MISSING ') + name)
    return all(checks.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sender-only', action='store_true', help='Skip local ripdrag/receiver on a machine used only as a remote sender')
    parser.add_argument('--check', action='store_true', help='Read-only installation check')
    parser.add_argument('--managed-server', action='store_true', help='Opt into Linux/systemd/zsh desktop server management')
    args = parser.parse_args()
    try:
        selected = target()
        manifest = json.loads((ROOT / 'install-assets.json').read_text())
        sender_only = args.sender_only
        if args.managed_server and (not sys.platform.startswith('linux') or Path(os.environ.get('SHELL', '')).name != 'zsh'):
            raise ValueError('--managed-server requires Linux, systemd --user and zsh')
        if args.check:
            return 0 if check(ROOT, manifest, selected, sender_only) else 1
        if os.geteuid() == 0:
            raise ValueError('Run ./install.sh as your normal user; it uses sudo only for system packages.')
        configure_checkout(ROOT)
        print('Installing ' + ('sender only' if sender_only else 'sender and local receiver') + ' on ' + selected)
        if not shutil.which('ssh'):
            packages({'apt': ['openssh-client'], 'dnf': ['openssh-clients'], 'pacman': ['openssh'], 'brew': ['openssh']})
        install_yazi(ROOT, selected, manifest)
        binary = install_herdr(ROOT, manifest, selected)
        link(ROOT / '.build/python', Path(sys.executable))
        if not sender_only:
            install_receiver(ROOT)
        run([sys.executable, ROOT / 'scripts/install-drag.py'])
        link(Path.home() / '.local/bin/herdr-yazi', ROOT / 'herdr-yazi')
        configure_path(Path.home())
        if args.managed_server or (ROOT / '.build/server-management.json').exists():
            run([sys.executable, ROOT / 'scripts/install-server.py'])
        env = {key: value for key, value in os.environ.items() if not key.startswith('HERDR_')}
        run([binary, '--session', 'yazi-links', 'plugin', 'link', ROOT], env=env)
        if not check(ROOT, manifest, selected, sender_only):
            raise ValueError('Installation check failed')
        print('Installed. Open a new terminal, run herdr-yazi, and open a new Yazi. Existing sessions were not restarted.')
        print('For remote use, run this same script once on the SSH host at ~/pets/herdr-yazi-links, then connect with herdr-yazi --remote HOST --remote-keybindings server.')
        return 0
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print('Install failed: ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
