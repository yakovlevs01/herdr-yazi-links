# Remote files to local ripdrag

[Русский](drag.ru.md)

Connect from the computer where you want to drop files:

```sh
herdr-yazi --remote my-mac-m1 --remote-keybindings server
```

In remote Yazi, select files or leave one under the cursor and press Ctrl+G. The local receiver downloads copies and opens ripdrag on the connecting computer. Ghostty and the remote Yazi pane stay in place. Yazi remains usable during downloads.

## Install

The [single installer](install.md), `./install.sh`, handles all steps below on the current machine, including progress initialization. The separate helpers remain available for targeted setup.

The remote checkout must be `~/pets/herdr-yazi-links`, as for existing remote preparation. Sender runtime needs Python 3.9+, Yazi 26.x and OpenSSH with SFTP. It needs neither ripdrag nor Paramiko.

Install the Yazi binding on each machine where you run Yazi, using Python 3.11+:

```sh
python3 scripts/install-drag.py
```

The installer backs up an existing keymap and changes only Ctrl+G. Other bindings remain. Start a new Yazi process to load it; there is no need to restart Herdr. To prepare configuration for an older server Python, copy its `~/.config/yazi` to a temporary local directory, run `python3 scripts/install-drag.py --config-dir TEMP --root /absolute/server/checkout`, then copy the generated `keymap.toml` and `plugins/herdr-drag.yazi/main.lua` back, retaining a backup on the server.

On each receiving computer, install ripdrag and run:

```sh
sh scripts/install-drag-receiver.sh
```

This installs Paramiko in `.build/drag-venv`. Its presence enables the receiver in `herdr-yazi --remote`. Existing user PATH priority stays intact. SSH host aliases, keys, ProxyJump and known-host checks use system OpenSSH. Authenticate and accept the host key with ordinary SSH first; background connections use BatchMode. The tested receiver is Linux with a graphical session and ripdrag in PATH. macOS and Ubuntu hosts can send without GTK or ripdrag. The full installer also installs the receiver and builds ripdrag on macOS; a receiving desktop needs a graphical session.

Ordinary local Yazi keeps `shell -- ripdrag -x -a -n -b %s`. The plugin also supports a local Herdr session through literal argv with the same ripdrag flags. `%s` is Yazi 26's selected-or-hovered expansion; it is not replaced with the older `$@` convention.

## Ownership and reconnects

The launcher starts a local receiver before attaching Herdr. Its SSH connection starts a small remote broker with an exclusive OS lock for the named Herdr session. A second receiver fails explicitly. Close the first client to move receiving to another computer; after an unclean disconnect allow about 15 seconds for the heartbeat lease to expire, then reconnect. There is no automatic takeover.

Yazi resolves its owning session on every request using the Herdr socket context. It does not retain a receiver address in its environment. The remote server and Yazi may outlive the local client. Once a session has been used remotely, an offline receiver produces an error instead of opening ripdrag on the server. This intent marker persists under `~/.local/state/herdr-yazi-drag`. Use a different session for purely local work.

A client exit closes the receiver, not the Herdr server. If its receiver connection fails, the launcher closes only its attached client and asks you to reconnect. Requests belong to a random receiver generation and are never replayed on another computer. Unfinished requests must be submitted again after reconnecting. Already completed copies remain local. One session has one receiver; stock Herdr clients and saved-machine navigation do not register a receiver. Use `herdr-yazi --remote HOST` on the intended receiving computer.

## Files, progress and errors

The broker accepts JSON lists of absolute paths, not shell commands. File paths travel as SFTP strings, not shell source. Up to 256 files and 64 KiB of request JSON are allowed; the receiver queues up to eight waiting requests. Queue overflow is reported locally and in remote status.

Only regular files are supported remotely. Selecting a directory, a final symbolic link, a broken link or a special file rejects the entire batch. Intermediate directory symlinks follow the server's normal path resolution, including macOS `/tmp`. SFTP v3 cannot make an atomic no-follow open; use this with a trusted SSH account and filesystem. Files should remain unchanged while copying. Size and modification-time checks detect common changes, but do not provide a filesystem snapshot.

Each batch downloads to a private `.partial-*` directory, then becomes a `transfer-*` directory only after every file succeeds. Indexed subdirectories preserve identical basenames. UTF-8, spaces, quotes, newlines and shell punctuation are supported. Non-UTF-8 names are rejected. Originals are never deleted or synchronized back. A normal transfer failure removes the incomplete batch; an abrupt process or machine crash can leave a `.partial-*` directory, which is never handed to ripdrag.

Yazi shows a progress line in its status bar: queued state, file count, aggregate percentage and, when there is space, a bar and byte totals. Each request has its own status; simultaneous requests cannot overwrite each other. Success appears for three seconds, errors remain until the next request. Closing Yazi during a running plugin task uses Yazi's normal unfinished-task confirmation. The receiver sends no system notifications. Full byte progress and ripdrag errors are in `~/.cache/herdr-yazi-drag/receiver.log`. On the server:

```sh
python3 ~/pets/herdr-yazi-links/drag.py status yazi-links
```

Set `HERDR_DRAG_CACHE` on the receiving computer to choose another cache. Copies survive ripdrag exit because the drop target may still be reading them. Cleanup is manual, only after receiving applications finish:

```sh
python3 scripts/drag-cache.py --older-than-days 7
```

Cleanup removes only completed batches older than the specified age. It does not touch active partial downloads. After a crash, inspect leftover `.partial-*` directories and remove them manually when no receiver is using them.

## Checks and references

`python3 -m unittest discover -s tests -v` covers broker requests, ownership, reconnects, errors, transfer completion, cache cleanup and installer behavior. `scripts/drag-smoke.py --remote HOST` exercises the actual launcher, a new remote session, Yazi key input and downloaded bytes with a recording ripdrag substitute. A process launch check is separate from an actual GUI drop into another application.

The queue/receiver separation is similar to [yazi-ssh.yazi](https://github.com/affromero/yazi-ssh.yazi), which wraps SSH itself. [drag.yazi](https://github.com/Joao-Queiroga/drag.yazi) handles local drag. This module uses [ripdrag](https://github.com/nik012003/ripdrag) locally and adds session ownership around Herdr's existing remote launch. It needs no additional Herdr binary patch.

Use `python3 scripts/drag-smoke.py --remote HOST --progress-check` to verify intermediate percentages and persistent errors in real Yazi with throttled SFTP. Add `--shell-yazi` to launch `yazi` from an ordinary shell pane instead of opening it through the link plugin.

## A queued popup appears, but no progress

A disappearing `Queued for ...` popup comes from the older Yazi plugin. A Yazi process started before the upgrade can keep that Lua code loaded even after the installer replaces files on disk. Reconnecting the Herdr client does not restart remote Yazi.

After any active transfer finishes, quit only that Yazi with `q` and run `yazi` again in the same pane. Leave the Herdr server and other panes running. The current plugin shows `Drag 1/1 42%` on the right of Yazi's bottom status line, with a bar if the pane is wide enough, and no queued popup. Starting Yazi manually in a shell pane is supported.

## Cancel a transfer

Press `w` in Yazi to open its task manager, select `Download to local ripdrag`, and press `x`. The receiver stops that request, removes its incomplete batch and does not open ripdrag. Queued requests can also be cancelled. The status line changes to `Drag: cancelled` after the receiver acknowledges cancellation; other requests continue normally. Detection normally takes about a second, with a five-second grace period if the watcher could not start.

Once ripdrag has opened, the transfer is finished and cancellation cannot revoke the files. Fully downloaded copies remain in the cache, including a batch cancelled just after it was committed. Remote originals are never removed. Escape outside the task manager is not a transfer cancellation command.

This uses Yazi's custom task API and requires Yazi/ya 26.8.15 or later within 26.x; the single installer handles the version check. After upgrading, restart only Yazi and reconnect the local `herdr-yazi` client so both the sender and receiver load the cancellation code. Do not restart the Herdr server.

Run `python3 scripts/drag-smoke.py --remote HOST --progress-check --shell-yazi --cancel-check` to test actual task-manager keys, stopped SFTP, partial-cache cleanup, absence of a ripdrag launch, and a subsequent successful transfer.
