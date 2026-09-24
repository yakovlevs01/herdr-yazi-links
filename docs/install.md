# Install on a computer

[Русский](install.ru.md)

From a checkout of this repository, run:

```sh
./install.sh
```

For a fresh computer with Git available:

```sh
git clone https://github.com/yakovlevs01/herdr-yazi-links.git ~/pets/herdr-yazi-links
cd ~/pets/herdr-yazi-links
./install.sh
```

The script installs the patched Herdr, Yazi file-link plugin, Ctrl+G handler and progress display, local ripdrag, SSH download dependencies, and the `herdr-yazi` command. Open a new terminal afterward and reopen Yazi. No agent or manual editing of configuration files is required. The script may ask for your system password to install missing packages. Run it as your normal user.

Supported release binaries are Linux x86_64 and macOS Apple Silicon. Linux dependency installation supports apt, dnf and pacman. On macOS, the script uses Homebrew and installs it if missing. Building ripdrag from Cargo can take several minutes and requires GTK4 development libraries. The script installs these dependencies when ripdrag is missing. A graphical desktop is needed to receive files in ripdrag.

Run the same script once on each participating machine. A machine used only as an SSH server can skip the local GUI and receiver:

```sh
./install.sh --sender-only
```

Then connect from the receiving computer:

```sh
herdr-yazi --remote my-mac-m1 --remote-keybindings server
```

SSH host aliases and authentication remain your SSH configuration. The installer does not create credentials or change SSH trust. If you clone elsewhere, it creates `~/pets/herdr-yazi-links` as a symlink for remote discovery. It refuses to replace another checkout already occupying that path.

## What it changes

- `.build/bin/herdr` receives the exact patched release binary from `install-assets.json`, verified with SHA256. This includes the existing plain-path patch; progress requires no additional binary patch.
- Missing or incompatible Yazi gets a verified Yazi 26.9.1 download under `.build/yazi`. Compatible Yazi 26.8.15 or newer within 26.x already in PATH is reused. If an older system Yazi takes precedence, Herdr's file pane uses the managed copy. Your shell's PATH priority remains unchanged.
- `.build/drag-venv` contains Paramiko for the local receiver. Missing ripdrag is built under `.build/ripdrag` and linked from `~/.local/bin`.
- Yazi's Ctrl+G binding and a managed `init.lua` setup block enable the plugin and progress line. The installer respects `YAZI_CONFIG_HOME` and `XDG_CONFIG_HOME` and backs up changed configuration files.
- `~/.local/bin/herdr-yazi` points to this checkout. Shell configuration appends `~/.local/bin` only when missing. Existing launcher files are backed up before replacement.
- Herdr registers this checkout's plugin. The installer never starts, stops or restarts a Herdr server and never runs `herdr-yazi update`.

Keep the checkout in place: the launcher and plugin refer to it. You can rerun the script after updating the repository. Existing Herdr sessions keep running, and previously downloaded drag copies remain in the cache.

## Check an installation

```sh
./install.sh --check
# On a sender-only installation:
./install.sh --sender-only --check
```

This checks dependencies, the patched binary checksum, installed plugin content, Ctrl+G and progress initialization without changing files. It does not perform a GUI drag. See [remote drag](drag.md) for transfer tests and cache management.

Python 3.11+ is required by the installation/configuration tools. The bootstrap script installs it from your package manager when missing. If your OS repository only provides an older Python, it reports that limitation; use an OS release with Python 3.11+.

## Optional desktop server management

On Linux/systemd with zsh, use `./install.sh --managed-server` to run the shared
`yazi-links` server independently of SSH. Existing enabled installations retain
this mode on reinstall. Headless hosts and other shells can use the ordinary
installer. See [migration and maintenance](server-management.md).
