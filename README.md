# herdr-yazi-links

Open a file in Yazi with Ctrl-click inside Herdr. Yazi opens beside the source
pane and selects the file. Press `q` to close Yazi.

This is a community plugin, not an official Herdr component. [Русский](README.ru.md).

## Two modes

| Input | Requirements |
|---|---|
| OSC 8 `file://` hyperlink | Plugin and a Herdr version that dispatches file hyperlinks to plugins |
| Plain-text `src/main.rs` or `README.md` | Plugin **and the optional Herdr patch** in this repository |

Installing the plugin alone does not make plain-text paths clickable. The
patched build was tested on Linux with Herdr 0.9.0 at the revision recorded in
[patches/upstream.toml](patches/upstream.toml). The plugin-only mode was also verified on the unmodified system Herdr 0.9.0:
Ctrl-click on an OSC 8 file hyperlink opened Yazi with the target selected;
Ctrl-click on a plain filename did not invoke the plugin. macOS, remote sessions
and Markdown-to-OSC-8 conversion in agent harnesses remain untested.

## Install the plugin

Clone this repository, then run:

```sh
herdr plugin link /absolute/path/to/herdr-yazi-links
```

Requirements: Herdr 0.9.0 or newer with a compatible plugin API, Python 3 and
Yazi in the **Herdr server's** PATH. The manifest minimum is an API requirement,
not a promise that all future Herdr versions have been tested.

## Enable plain-text paths

Install Rust 1.98.1, Zig 0.16.0, Python 3.11+, Git and Bash 4+. From this repository:

```sh
./build.sh
# Or: ZIG=/absolute/path/to/zig ./build.sh
./herdr-yazi
```

The launcher registers the plugin and starts a separate `yazi-links` session.
It does not replace the system Herdr or restart existing sessions. Source and
binary output live in ignored `.build/` storage.

Run `printf '%s\n' README.md` in a pane whose working directory is this
repository, then Ctrl-click the filename. No agent instructions or special
Markdown are necessary. Optional launcher installation:

```sh
mkdir -p ~/.local/bin
ln -s "$PWD/herdr-yazi" ~/.local/bin/herdr-yazi
```

## Recognition and limits

- Absolute paths, `./file`, `../file`, `src/file.rs` and bare filenames work when
  they refer to an existing regular file or directory.
- Relative paths use the source pane's process working directory. A same-named
  file in that directory can be opened even if the author meant another project.
- Terminal hyperlinks take priority. Plain HTTP(S) URLs keep their existing behavior.
- Unicode and soft-wrapped lines use Herdr's existing terminal-cell mapping.
- Quoted paths containing `/` can include spaces. Unquoted spaces and
  `:line:column` suffixes are not supported.
- File existence is checked on a click, never during rendering.
- Filenames are passed through environment variables and argv, never evaluated
  as shell code. Launch errors appear in `herdr plugin log list --plugin local.yazi-links`.

Yazi runs on the server owning the clicked pane. This leaves room for
`--remote`, but the patch and plugin must be installed there too. Remote
operation is not tested or deployed by the launcher. A nested manual SSH session
is not detected. Remote Yazi does not provide local RipDrag.

## Versioning and upstream updates

The plugin version is in `herdr-plugin.toml`; changes go in [CHANGELOG.md](CHANGELOG.md).
Release tags use `vMAJOR.MINOR.PATCH`.

Keep the plugin and small patch together. Do not commit Herdr sources, caches or
binaries. `patches/upstream.toml` records the exact source revision and toolchain;
`patches/herdr-path-click.patch` records the change.

Update the pin and patch together, run tests, build a candidate, and verify
Ctrl-click in an isolated session. Patch failure must stop the upgrade: do not
apply with fuzzy matching or silently fall back to an unpatched binary.
`build.sh` checks the pin, runs tests and replaces the executable atomically only
after a successful build. Running servers keep their old executable until
explicitly restarted. Arbitrary upstream changes are not guaranteed compatible.

```sh
python3 -m unittest discover -s tests -v
```

## Marketplace publication

Publish a public GitHub repository with the manifest on its default branch and
add the topic `herdr-plugin`. Herdr indexes eligible repositories automatically;
a listing is not review or endorsement. Forks are excluded, so this plugin has
its own repository rather than being a fork of Herdr. Users can install with
`herdr plugin install OWNER/REPO`.

Keep the two-mode limitation in the description and release notes. Publishing
the plugin does not distribute or install the patched binary.
See [Herdr's marketplace documentation](https://herdr.dev/docs/marketplace/).

## License

Apache-2.0. See [LICENSE](LICENSE) and [THIRD_PARTY.md](THIRD_PARTY.md).
