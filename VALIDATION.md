# Plugin-only validation

- Platform: Linux.
- Executable: `/usr/bin/herdr`, version 0.9.0, unmodified system binary.
- SHA-256: `a1b71f046f269aad0ec4531a337198392502398f0c4c2eff1bc6bac380ec1abb`.
- Plugin: `local.yazi-links`, version 0.1.0.
- Isolated session: `stock-yazi-link-check`, stopped after testing.

A shell emitted an OSC 8 hyperlink labelled `Open-in-Yazi` targeting this
repository's `README.md`, followed by a plain `README.md` on the next line.
The test sent SGR mouse events for Control + left-button press and release
through the client terminal input, not just a direct plugin/API invocation.

The hyperlink click produced one successful plugin action with exit code 0,
opened a Yazi pane, and Yazi's status line showed `README.md` selected.
After closing Yazi, the plain filename click left one source pane and produced
no additional plugin invocation.

This validates Herdr hyperlink dispatch and the plugin launch. It does not
validate whether a particular agent harness converts Markdown file links into
OSC 8 hyperlinks. Remote sessions and macOS were not tested.

## Repeatable checks

Run `python3 -m unittest discover -s tests -v` for URI, argument passing and atomic build safety checks. Run `python3 scripts/smoke.py --herdr /usr/bin/herdr` for stock Herdr, or pass `--expect-paths` with the patched executable. These Linux checks send real SGR Ctrl-click events through a PTY and verify the selected file in real Yazi, without an agent. Configurations and sessions are isolated.

GitHub Actions checks stock 0.9.0 and the latest release on changes and weekly. `scripts/check-upstream.py --revision FULL_COMMIT` builds and tests a separate patched candidate before adoption. See the bilingual guides in `docs/`.

## 0.2.0 remote checks

Verified from a stock Linux Herdr 0.9.0 client over real `--remote` SSH connections to Linux x86_64 and macOS ARM64 servers. Both used the pinned patched Herdr server and installed Yazi. OSC 8, relative paths and absolute paths opened Yazi with the target selected; nonexistent paths did not invoke the plugin. The macOS build also passed all 76 focused Herdr action tests. Python runtime was the existing system Python, including Python 3.9.6 on macOS.

Run the command in `docs/remote.md` to repeat these checks against your host. Public CI covers local Linux operation only. The test fixture uses a unique remote session and shuts down only that session.

## 0.2.1 launcher arguments

The SSH smoke test also passed using the actual `herdr-yazi` launcher as the client with `--remote-keybindings server` against macOS ARM64. Launcher regression tests cover unchanged argv, flags in different positions, equals syntax, unknown future flags, explicit sessions, literal arguments after `--`, no SSH for help/version, and exit status propagation.

## 0.2.2 daemon preparation

The earlier remote smoke used `start_new_session=True` directly and therefore missed the preparation helper’s `nohup`-only startup. A dedicated preparation test now checks SID == PID and verifies that an existing server is not restarted. On both macOS ARM64 and Linux x86_64, fresh UUID sessions started through the actual helper report `capabilities.detached_server_daemon: true`. Existing working sessions were left untouched.

## 0.2.3 command audit

Verified current-pane stable identifiers match stock Herdr when invoked from a real managed pane. Help/version/default-config/skill/completion/API-schema output matches the direct patched binary under the same session. Mac SSH click smoke with server keybindings still passes. Tests cover preserved socket and pane context, explicit environment sessions, PATH priority and side-effect-free informational requests. Update behavior was reviewed in source, not executed. See `docs/compatibility.md` for remaining differences.

## 0.3.0 remote drag

Validated 2026-09-11 from this Linux graphical desktop with Yazi 26.9.1 and local ripdrag. Both `my-mac-m1` macOS ARM64 and `iw-my-ubuntu` Linux x86_64 ran Yazi 26.8.15. The sender works with macOS system Python 3.9.6. The receiver uses an isolated Paramiko environment and system OpenSSH.

The new `scripts/drag-smoke.py` starts the actual `herdr-yazi --remote HOST --remote-keybindings server --session UUID` launcher. Its normal `prepare.sh` creates the new detached server; the test does not prestart one. It opens real Yazi in a plugin pane and sends Ctrl+G through the local PTY. Both hosts passed hovered file and multiselection downloads, Unicode, quotes, embedded newline, shell punctuation, retained copies with repeated basenames and unchanged originals. A local ripdrag argv recorder verifies exact completed-cache paths. UUID test sessions alone were stopped.

Retained repeat-run evidence on the test desktop:

- macOS: `/tmp/herdr-drag-smoke-lpv19vme/result.json`
- Ubuntu: `/tmp/herdr-drag-smoke-kket2o30/result.json`

An additional real local ripdrag process started successfully with a downloaded macOS file and remained running after one second. This is a process launch check, not proof of a successful GUI drag-and-drop into another application. GUI drop remains unverified. The existing OSC 8/plain-path click smoke also passed through the launcher against macOS with server keybindings.

Unit/integration tests cover JSON schema and size boundaries, aborted request sockets, session routing, exclusive receiver conflicts, heartbeat expiry, reconnect without replay, receiver/launcher failure and SIGTERM cleanup, literal local ripdrag argv, SFTP errors and incomplete-batch cleanup, manual cache cleanup, and preservation of user keymaps. Remote sender configurations were installed on both hosts; local sender and receiver were installed on the desktop. The remote hosts do not have ripdrag and were tested as senders, not GUI receivers. Existing working Herdr sessions were neither stopped nor restarted.

## 0.4.0 progress and unified installation

Follow-up: `scripts/drag-smoke.py --remote my-mac-m1 --progress-check --shell-yazi`
also passed with Yazi launched from an ordinary shell pane. This exposed a narrow
pane layout issue: long errors pushed their `Drag error:` prefix outside the pane.
The plugin now reserves space for Yazi's standard status fields. The passing run
at `/tmp/herdr-drag-smoke-4zl_oqh3/` includes intermediate percentage, ready and
persistent error captures, verified downloads and ripdrag arguments. All 68 tests
passed. A queued popup in a pre-upgrade Yazi process still requires restarting
that Yazi to load the new Lua plugin; reconnecting Herdr preserves the old process.

The single `./install.sh` completed on the Linux desktop and macOS ARM64. On macOS it installed Python 3.13, GTK4, built ripdrag 0.4.12, created the Paramiko environment, and configured the Lua plugin. Ubuntu passed `./install.sh --sender-only`; its GUI receiver was not installed because that host is used as the sender in these checks. The installer supports a full Ubuntu install with the user's sudo password for missing GTK development packages.

Both hosts passed `scripts/drag-smoke.py --remote HOST --progress-check`. This uses the real launcher and Ctrl+G in real Yazi, throttles OpenSSH SFTP to make a 4 MiB transfer observable, and verifies an intermediate percentage in the rendered status line, completion, and a persistent directory error without starting ripdrag. Remote originals and retained downloaded copies were checked. Only UUID test sessions were stopped.

Evidence on the desktop:

- Ubuntu: `/tmp/herdr-drag-smoke-nhxa_m9o/`, including `progress-pane.txt`, `ready-pane.txt`, `error-pane.txt`.
- macOS: `/tmp/herdr-drag-smoke-5dr0w8o1/`, with the same captures.

These checks verify the terminal progress display and transfer/launch path, not a GUI drop into another application. No system notification is used. Herdr binaries remain the previously tested pinned build; Yazi progress uses its Lua API. Release installation CI downloads the published artifacts into a fresh Ubuntu runner, executes the full installer twice, checks configuration, and exercises real patched Herdr/Yazi clicks in an isolated session.

## Transfer cancellation follow-up

The cancellation implementation uses a named Yazi custom task, a watcher lock
owned by that task, a session-scoped cancellation message and cancellable SFTP
reads. Normal plugin-entry cancellation alone does not stop Yazi 26.8.15's
blocking plugin code. The custom task handle provides the cancellation state.
Yazi/ya 26.8.15 is now the minimum accepted by the installer.

All 73 unit/integration tests passed, including watcher termination, missing
watcher startup, active and queued cancellation, partial-cache removal, no
ripdrag launch after cancellation, and processing the next request. The macOS
run at `/tmp/herdr-drag-smoke-zyjeggmo/` passed the real launcher, shell-launched
Yazi, Ctrl+G, task-manager `w`/`x`, cancelled status, cleanup and a successful
subsequent transfer. The local ripdrag recorder checks process arguments;
GUI drag-and-drop was not part of this cancellation test. Only UUID test
sessions were stopped.

Ubuntu also passed the same cancellation and recovery check at
`/tmp/herdr-drag-smoke-znk346hs/`, including `cancelled-pane.txt`. The shell-launch
test now waits for Yazi's normal-mode status, so an echoed shell command cannot
be mistaken for a ready file manager.

## Saved-machine receivers

The Linux user service manages enabled saved profiles without a `--remote`
client. Tests cover duplicate and disabled profiles, changing sessions, removal,
independent connection retry, default-session routing, and reuse by standalone
launches. Live checks on the receiving Linux desktop used the existing Mac and
IW saved profiles, temporary remote Yazi panes, and Ctrl+G sent with
`herdr --machine LABEL pane send-keys`. Both copied the expected bytes and opened
real mapped local ripdrag windows, verified through Hyprland. Only test panes
and test GUI processes were closed. GUI drop into another application was not
part of this check. The service claims one receiver per remote session; it does
not route requests by the originating TUI client.

