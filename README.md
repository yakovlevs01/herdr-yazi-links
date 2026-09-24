# herdr-yazi-links

Ctrl-click a file hyperlink in Herdr to open Yazi beside the source pane, with the file selected. Press `q` to close Yazi.

[Русский](README.ru.md) · [Plugin installation](docs/plugin.md) · [Optional patched Herdr](docs/patched-herdr.md)

## Install everything on this computer

```sh
git clone https://github.com/yakovlevs01/herdr-yazi-links.git ~/pets/herdr-yazi-links
cd ~/pets/herdr-yazi-links
./install.sh
```

This installs the pinned patched Herdr, Yazi plugin, Ctrl+G with progress in Yazi, ripdrag and download dependencies. No agent or manual configuration edits are needed. Missing system packages may require sudo. See the [installation guide](docs/install.md). Use `./install.sh --check` to verify an installation.

## Choose what you need

| Mode | Clickable input | Installation |
|---|---|---|
| Plugin on stock Herdr | A terminal OSC 8 hyperlink targeting `file:///absolute/path` | Install the plugin |
| Plugin with optional Herdr patch | The same hyperlinks, plus existing plain-text paths such as `README.md`, `src/main.rs` and `/home/user/report.txt` | Install the plugin and build the patched Herdr |

The manifest at the repository root installs the plugin. It does not build, download or replace Herdr. The optional patch and build tools live alongside it for users who want to click ordinary paths in agent messages and command output.

## Install the plugin

With Python 3 and Yazi available in the Herdr server's PATH:

```sh
herdr plugin install yakovlevs01/herdr-yazi-links
```

For a local checkout:

```sh
herdr plugin link /absolute/path/to/herdr-yazi-links
```

See the [standalone plugin README](docs/plugin.md) for link syntax, a demo and troubleshooting. A Markdown code span such as `README.md` is ordinary text and requires the optional patch. A Markdown link works only when the application renders it as a terminal hyperlink.

## Compatibility and checks

Plugin-only mode has been verified on unmodified Linux Herdr 0.9.0. The optional patch targets the exact revision in [patches/upstream.toml](patches/upstream.toml). Individual agent applications' Markdown rendering has not been verified. See the remote guide for SSH validation. The manifest's minimum Herdr version does not guarantee compatibility with every later version.

Run these commands from the checkout:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/smoke.py --herdr /usr/bin/herdr
python3 scripts/smoke.py --herdr .build/bin/herdr --expect-paths
```

The smoke checks exercise the terminal click route in an isolated test session without an agent. They use real Yazi and verify the selected file. GitHub Actions checks stock Herdr 0.9.0 and the latest release on changes and weekly. A manual check still helps verify your terminal’s mouse handling. For a manual demo inside Herdr, run `python3 scripts/demo.py` and Ctrl-click its examples.

Updating `/usr/bin/herdr` leaves the custom `.build/bin/herdr` unchanged. `herdr-yazi` continues to launch the pinned custom build, so new upstream features and fixes require an explicit rebuild. See the [update procedure](docs/patched-herdr.md).

## Publish and version

This repository can be published as a community plugin. Keep `herdr-plugin.toml` at the root of the default branch of a public GitHub repository and add the `herdr-plugin` topic. The marketplace indexes eligible repositories automatically; a listing is not a review or endorsement. Forks are excluded. See [Herdr's marketplace rules](https://herdr.dev/docs/marketplace/).

Before a release, run the tests, update the manifest version and [CHANGELOG.md](CHANGELOG.md), then create a matching `vMAJOR.MINOR.PATCH` tag. Describe plugin compatibility separately from the optional patch's pinned revision. Do not commit Herdr sources, caches or binaries; `.build/` is ignored.

## License

Apache-2.0. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).

For SSH host installation and agent-free tests, see [remote operation](docs/remote.md).

[Command compatibility and exceptions](docs/compatibility.md).

For Ctrl+G from remote Yazi to local ripdrag, see [remote drag](docs/drag.md).

## Managed Linux server

On Linux/zsh, `./install.sh --managed-server` opts into a user service for `yazi-links`, with
an SSH-discoverable `~/.local/bin/herdr` entry point. Both local and remote
clients use the pinned server, without inheriting SSH variables. Existing
servers are kept running until an explicit migration. See
[server setup and migration](docs/server-management.md). Test isolation with
`python3 scripts/smoke-server.py` from a running Linux desktop.
