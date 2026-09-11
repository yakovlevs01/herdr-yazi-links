# Yazi through Herdr --remote

[Русский](remote.ru.md) · [Plugin without a patch](plugin.md)

The local client sends Ctrl-click coordinates to the owning Herdr server. That server resolves the path and invokes its plugin, which opens Yazi on the same host. Relative paths use the remote pane's working directory. Files are not copied to your computer.

## Installation

Each remote host needs Herdr, Yazi and Python 3. Plain-text paths also require a patched Herdr executable built for that host's OS and architecture. A Linux x86_64 executable cannot run on an ARM64 Mac.

For the standalone plugin, run on the server:

```sh
herdr plugin install yakovlevs01/herdr-yazi-links
```

File OSC 8 hyperlinks should then work through ordinary `herdr --remote HOST`. For plain-text paths, put this checkout at `~/pets/herdr-yazi-links` on the server and its patched executable at `.build/bin/herdr`. From your local machine:

```sh
herdr-yazi --remote HOST
```

The launcher calls remote `herdr-yazi --prepare`, registers the plugin, and starts a separate `yazi-links` server if needed. It then attaches the local client through `--remote`. It does not copy dependencies or executables, or replace an existing server. An existing server keeps using its previous executable until deliberately restarted after an update.

The launcher adds `~/.local/bin`, `/opt/homebrew/bin` and `/usr/local/bin` to the server's PATH. Noninteractive SSH commands may not inherit an interactive shell's PATH. Configure the server's PATH if Yazi is elsewhere.

## Test without an agent

From a local Linux checkout, with working SSH access and an installed remote patched build:

```sh
python3 scripts/smoke.py --herdr /usr/bin/herdr \
  --remote HOST --remote-root /absolute/path/to/herdr-yazi-links \
  --expect-paths
```

The test creates a temporary remote file and a unique `smoke-<random ID>` session. It launches a real local `herdr --remote` client, sends Ctrl-clicks, and checks the selected file in remote Yazi. It covers OSC 8, relative and absolute paths, and a nonexistent file. Cleanup stops only the test session. Installed plugin registration remains. SSH Unix-socket forwarding is required.

GitHub Actions checks local operation. Remote checks run explicitly against an accessible SSH host; public CI does not access personal computers.

## Python

Python decodes file URIs, validates files, parses JSON invocation context, and sends `plugin.pane.open` over the Unix socket. No third-party Python packages are required. Plugin runtime supports Python 3.9+; build scripts need Python 3.11+ with `tomllib`.

A native helper could replace Python, but would need separate releases for Linux and macOS on x86_64 and ARM64. This release keeps the Python implementation.

Running `ssh HOST` inside an ordinary pane does not change its owning Herdr server. Nested SSH host detection is not implemented.

Verified with a stock Linux Herdr 0.9.0 client and patched Linux x86_64 / macOS ARM64 servers. See [validation](../VALIDATION.md).
