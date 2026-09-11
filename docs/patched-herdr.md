# Optional Herdr patch for plain-text paths

The patch lets you Ctrl-click an existing path in ordinary terminal text. This covers agent messages containing `README.md` or `src/main.rs` without a hyperlink. The plugin then opens Yazi in the pane on the right.

[Русский](patched-herdr.ru.md) · [Plugin without a patch](plugin.md)

## Build and launch

Install the toolchain versions recorded in [patches/upstream.toml](../patches/upstream.toml), plus Python 3.11+, Git and Bash 4+. The current pin uses Rust 1.98.1 and Zig 0.16.0. The build and automated checks require Linux, Yazi in PATH, rustup, a C/C++ compiler and pkg-config. From the repository:

```sh
./build.sh
# If Zig is outside PATH:
# ZIG=/absolute/path/to/zig ./build.sh
./herdr-yazi
```

The launcher registers the plugin and opens a separate `yazi-links` session using `.build/bin/herdr`. It does not replace `/usr/bin/herdr` or restart existing sessions. To put the launcher in PATH:

```sh
mkdir -p ~/.local/bin
ln -s "$PWD/herdr-yazi" ~/.local/bin/herdr-yazi
```

Run `python3 scripts/demo.py` inside that session. Ctrl-click both the hyperlink and the ordinary paths. Run the automated check from the checkout:

```sh
python3 scripts/smoke.py --herdr .build/bin/herdr --expect-paths
```

## How recognition works

Herdr first checks for an existing terminal hyperlink. Otherwise the patch uses the terminal's cell mapping to find text under Ctrl-click, including soft-wrapped lines and Unicode. It extracts a candidate path, removes surrounding punctuation and checks whether it names an existing regular file or directory.

Absolute paths use their own location. Relative paths, including bare filenames, resolve against the source pane process's working directory. A word like `tests` can therefore open a directory of that name. If the agent meant another project, existence alone cannot detect that mistake.

Quoted paths containing `/` can include spaces. Unquoted paths with spaces and `:line:column` suffixes are unsupported. The plugin passes the resulting path as an argument and does not execute the clicked text. Existing terminal hyperlinks take priority; HTTP(S) links keep their usual behavior.

## What happens when Herdr updates

| Action | Result |
|---|---|
| Update system Herdr | `/usr/bin/herdr` changes; `.build/bin/herdr` stays unchanged |
| Run `herdr-yazi` afterward | Uses the same custom binary and `yazi-links` session |
| Run `build.sh` without changing the pin | Rebuilds the pinned revision, not the latest upstream |
| Build a newer pinned revision | Installs the new custom executable after successful build checks |
| Keep an existing server running | That server continues running its old executable until deliberately restarted |

You need no extra action to keep using the existing custom build after a system update. To receive upstream fixes or features in that build, you must update its source pin and patch, test, rebuild, and restart the custom session when you are ready. The scripts do not stop your working server automatically.

## Check an upstream candidate

Use a full commit hash, not a moving branch name:

```sh
python3 scripts/check-upstream.py --revision <full-commit-hash>
```

This checks a candidate in an isolated ignored build directory. It checks patch application, runs tests, builds Herdr and runs the patched smoke check. It stores the candidate under `.build/candidates/<hash>/bin/herdr`; it does not replace `.build/bin/herdr` or change the committed source pin. Set `ZIG` to the required Zig executable; optional `--rust` and `--zig-version` arguments select candidate toolchain requirements. A failure is a reason to inspect the upstream change before upgrading. Successful tests cover the behaviors under test; they do not guarantee compatibility with every terminal or future release.

For a release that uses the candidate:

1. Review the upstream changes and toolchain requirements.
2. Update `patches/upstream.toml` and adapt `patches/herdr-path-click.patch` as needed. Keep both in one commit.
3. Run the candidate check, plugin tests and a manual demo with real Yazi.
4. Rebuild using `./build.sh` and run the patched smoke check.
5. Save work in the old `yazi-links` session, then deliberately shut it down and relaunch `herdr-yazi` using Herdr's session controls. Closing a client alone may leave its server running.

Each revision gets its own `.build/source-<hash>` checkout. A checkout with an unexpected Git revision is rejected. Older checkouts are left intact for diagnosis. Never use an unreviewed patch with fuzzy matching or replace the working build after a failed check.

## Repository boundaries

Version the plugin, patch, pin, tests and build scripts together. Keep Herdr sources, caches and binaries in ignored `.build/`. The standalone plugin remains useful on stock Herdr even while the optional patch needs maintenance.

Remote operation remains untested. The plugin uses the owning Herdr server's socket, so Yazi would run there. The launcher does not deploy the plugin or patch to a remote host. A manual nested SSH connection is not detected.
