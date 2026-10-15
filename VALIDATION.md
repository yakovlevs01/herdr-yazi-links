# 0.6.0 release preparation, 2026-10-15

- The user confirmed that selecting text on the saved Mac connection now copies successfully to the PC clipboard after the Mac deployment below.
- Bump the plugin manifest from 0.5.0 to 0.6.0 and pin the optional build to the verified Herdr 0.9.5 revision. The PC's installed binary and running server remain 0.9.4.
- Final release checks: all 132 Python tests passed; shell syntax, release metadata and `git diff --check` passed. The patch and Linux candidate hashes match the previously validated builds below. Log: `.build/release-0.6.0-python.log`.

# Mac-only deployment, 2026-10-15

- The user subsequently authorized updating **Mac only**. Installed the verified ARM64 0.9.5 candidate and matching patch, pin and build receipt on `my-mac-m1`.
- Production live handoff completed. All **13 pane IDs, shell PIDs and foreground process group IDs** were preserved. Existing clients reconnected; no agent processes were restarted. The installed executable and running server report 0.9.5/protocol 22, with no stale server binary.
- The PC client/server remain **0.9.4**. The PC's existing 0.9.4 executable passed the saved-Mac SSH mouse-selection and Yazi link smoke checks against the installed Mac 0.9.5 server. The Mac installation check passed all dependencies and the patched-build receipt.
- Mac rollback files: `/Users/yakovlevs/pets/herdr-yazi-links/.build/before-clipboard-0.9.5/`. Mac process snapshots: `.build/clipboard-095-before.json` and `.build/clipboard-095-after.json`. Local logs: `.build/audit-mac-production-handoff.log` and `.build/audit-mac-post-install-095.log`.
- Existing native Mac UI processes were allowed to reconnect without being forcibly closed; a newly launched client uses 0.9.5. The clipboard correction runs in the updated server and also works with the existing 0.9.4 clients.

# Clipboard and 0.9.5 compatibility audit, 2026-10-15

The following records the investigation before deployment. The later Mac deployment and user confirmation are recorded above.

- Live PC and Mac clients/servers are still **0.9.4**, protocol 22. Installed SHA256 hashes match the final October 14 desktop-routing deployment below. The PC UI has a native Wayland environment; the persistent PC server still has old SSH variables, which the client routing deliberately ignores.
- **132 Python tests passed.** The installed 0.9.4 desktop PTY suite passed A/B/A gestures, Enter routing, distinct image paste, ambiguous OSC 52 refusal, disconnect/reconnect and plain-SSH isolation.
- Added `smoke.py --expect-selection-copy`: real SGR mouse drag selects `OSC_LINK`, a clipboard-tool recorder verifies the exact bytes and the writer's ancestry under the client process. Added `--saved-machine` using an isolated endpoint catalog. Production clipboard tools are not invoked by these smoke tests. The normal build now includes the local selection check.
- Selection and file links passed on installed 0.9.4 in four configurations: local PC, PC client with direct SSH to Mac, PC client with saved Mac, and Mac client with saved PC. Only fresh UUID sessions were used. This did **not** reproduce the reported wrong-machine copy.
- Saved-Mac Yazi Ctrl+G/SFTP checks passed for hovered files, multiselection, Unicode, quotes, newlines and duplicate basenames; remote originals remained unchanged. Artifact directory: `/tmp/herdr-drag-smoke-i3zq1d73`.
- Separately tested real `/usr/bin/wl-copy` followed by `/usr/bin/wl-paste` with the live PC client's environment. A multiline Unicode marker round-tripped exactly, and the previous text was restored and verified. Clipboard contents were not logged. This checks the native backend separately, not mouse interaction in the user's existing Ghostty window.
- Built upstream **0.9.5**, commit `2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01`, with the existing patch unchanged. **247 selected Rust tests passed, one ignored.** Release build, local/SSH-context Yazi tests and the desktop PTY suite including live handoff passed. Additional real mouse-selection checks passed locally and against the existing Mac 0.9.4 server through a saved machine. This is Linux candidate validation, not a full Rust-suite run or a macOS 0.9.5 build.
- Candidate: `.build/candidates/2ecf19a92fc3a7fff75b6ce3655ef04f4625ec01/bin/herdr`. The production pin, installed binaries, running servers and user panes were not replaced or restarted. Logs: `.build/audit-0.9.5*.log`, `.build/audit-2026-10-15-*.log`, `.build/audit-*-selection.log`, `.build/audit-native-clipboard.json`.
- Initial selection checks above covered Herdr-owned selection. The user confirmed their failure persisted. Live Mac server logs at 08:31:28, 08:34:48 and 08:34:58 UTC recorded `OSC 52 ignored: pane has multiple active viewers` for runtime pane 3, the Codex pane `w2:p1`. A temporary wrapper observed no local `wl-copy` call during reproduction and was then removed. Codex owns mouse selection here and emits OSC 52; the October 14 patch rejected it because another client viewed the pane. Its input-owner tracking also excluded mouse gestures.
- Added a failing-before/fixed-after Rust regression and a real two-client PTY probe that enables application mouse reporting and emits OSC 52 on mouse release. Mouse down/drag/up now establish the clipboard owner. Shared panes require an unambiguous input owner from the last five seconds; passive motion does not change it. Interleaved input remains blocked until that interval expires, and disconnected owners never fall back to another viewer.
- Fixed 0.9.5 candidates passed the build's Python/Rust checks and all PTY checks on both Linux and macOS ARM64. macOS Python ran 132 tests with two platform skips. The full desktop suite now uses native-tool recorders for both platforms, including macOS PNG reads, without touching the real pasteboard. Installer test fixtures now normalize symlinked temporary paths and explicitly mock Linux for the mocked systemd installer test.
- Isolated upgrades from the installed 0.9.4 to fixed 0.9.5 passed on both platforms, preserving pane IDs, shell PIDs and foreground process groups. The Linux fixed binary SHA256 is `8752ca7ebad7f06248b53e70eee8216ada36e5b286d9fba084d81a5e9b4c79ee`; Mac SHA256 is `cbddff6401c8f8cae506f32f28400f0f9ac28148738e4294cf19d301c5a77991`; patch SHA256 is `055fe7d908e4728146d966d36ec654091fb411483c1a7f19be0988bd944add57`. Mac candidate: `.build/clipboard-0.9.5/.build/bin/herdr`. Logs on each host include `.build/audit-fixed-0.9.5.log` and `.build/audit-handoff-094-095-{linux,mac}.log`.
- **Deployment declined by the user for now.** Leave the change in code and staged builds only. Production PC/Mac servers and clients remain 0.9.4; the live clipboard failure remains until a separately authorized deployment. The temporary diagnostic wrapper was removed. No commits or pushes were made.
- Separate remaining limitation: Herdr-owned `SelectionCopy` shows success feedback before `write_osc52_bytes` runs, and the dispatcher ignores its boolean result. Upstream 0.9.5 leaves this code unchanged. Application-owned selection can also display its own success message without knowing whether the server forwarded OSC 52.

# Expanded desktop regressions, 2026-10-14

This completes the test follow-up to the client routing rollout below.

- **132 Python tests passed.** Real Unix sockets exercise desktop API requests and failures; actual broker processes cover two client scopes, simultaneous requests, disconnect without fallback and scoped watchers. Both opener entry points are executed as subprocesses. Launcher tests cover fresh receiver identities, cleanup, and explicit session attach. Receiver tests cover Linux/macOS open actions and failure of any file in a batch. Lua tests verify scoped watcher arguments. A real delayed-stderr child reproduces and guards against an already opened drag window dying after its helper exits.
- **4050 Rust tests passed across 19 test binaries; 14 skipped by upstream.** Run with nextest, four workers, and temporary Git signing overrides for fixture repositories. This replaces the earlier incomplete single-process cargo test results. Nextest isolates global signal handlers. The stale-path SSH test fixture now explicitly locates its replacement binary instead of accidentally discovering the developer's stable `/usr/bin/herdr`.
- Rust regression cases cover pane/workspace/action isolation, exact request expiry, overlap and retry, disconnect/reconnect, unknown clients, key release/repeat/modifiers, registration tied to the connection and boot, inactive saved endpoints, shared active viewers, disconnected clipboard owners and direct terminal attachment.
- Maintenance, hot-path architecture, integration-asset and documentation contract recipes passed. Strict `just check` remains unavailable as one green aggregate: Rust 1.98 Clippy reports three lint categories in unchanged upstream code (`chunks_exact_to_as_chunks`, `byte_char_slices`, `some_filter`), and the Windows SDK is not installed. Clippy passed with only those three command-line exceptions; no blanket warning suppression or source allow attributes were added. Windows cross-validation was not performed.
- The expanded PTY test passed with a release binary: A/B/A drag, A/B Enter, distinct clipboard PNGs, shared-viewer text refusal, copy after disconnect, a new client after reconnect, plain SSH rejecting inherited desktop/receiver access, and live handoff preserving process IDs while discarding old desktop requests. Artifacts: `/tmp/herdr-desktop-smoke-n93fuizw`.
- Tests found and fixed five additional behaviors: inactive saved endpoints counted as clipboard viewers, successful reporting despite one failed remote opener, explicit session attachment retaining an inherited pane socket, local ripdrag retaining a stderr pipe whose reader had closed, and malformed API contexts allowing legacy routing. Unknown actions are rejected before consuming routing context or downloading. Only an explicit unknown-method response permits old-server fallback.
- Deployed the regression fixes on all three machines. SHA256 Linux: `9acf734e67215426b5dfefb898dcd72efe0d1b396c305e3603990eaf7a36938d`; Mac: `bd2b2e5ba01f6470cfd3abff1964aa28f4b87a32df3b8ee59805ddcb1eefc1cd`. Live handoff again preserved all 19 PC, 8 IW and 13 Mac pane IDs, shell PIDs and foreground process group IDs. Fresh native clients loaded the receiver changes. The saved-machine IW smoke test passed again with real Yazi input and SFTP, including literal filenames and preserved originals; artifacts: `/tmp/herdr-drag-smoke-mdpup9ur`.

## Repeat the checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/desktop-smoke.py --herdr .build/bin/herdr --handoff-to .build/bin/herdr
```

For the patched source, use `cargo +1.98.1 nextest run --locked -j 4 --no-fail-fast` with `CARGO_TARGET_DIR` and `ZIG` set to the build directories. If your Git configuration signs tags, isolate test fixture Git operations with `GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=commit.gpgsign GIT_CONFIG_VALUE_0=false GIT_CONFIG_KEY_1=tag.gpgsign GIT_CONFIG_VALUE_1=false`; this does not change your Git configuration or the signing of the real commit.

| Boundary | Regression evidence |
|---|---|
| PC / IW / Mac, direct and saved connections | Six-direction SSH/SFTP results below; reusable `scripts/drag-smoke.py --remote HOST --isolated-config --shell-yazi`, plus `--saved-machine` |
| Persistent server with stale SSH/display state | Two-client PTY test and native environment replacement tests |
| Receiver identity / reconnection / concurrent requests | Real scoped brokers, launcher lifetime tests, Rust connection ownership |
| Text and image clipboard | Rust clipboard suite, active/inactive/shared viewer cases, actual client PTY input |
| Missing receiver, expired or conflicting request, malformed API | Fail-closed Python socket tests and Rust routing state tests |
| Local / remote Enter, multiple files, errors | Native opener dispatch tests, both wrapper entry points, PTY Enter |
| Handoff and old desktop identity | Isolated live handoff with preserved pane/PIDs and fresh client registration |
| Cancellation and unusual filenames | Existing transfer, Lua, broker and remote smoke suites |

# Client desktop routing, 2026-10-14

This section supersedes the older rollout notes below.

- Installed the new 0.9.4 build on PC, Ubuntu IW and macOS ARM64. SHA256 Linux: `4ac9088454814cfbe9493312b873c84979a17089ff443f9338596f327b3a3542`; Mac: `3a3ab7cb6c471cf1cc55888430f2d694d5a328a25950a3dd96cec47e948dc03e`.
- 100 Python tests passed. 122 selected Rust tests passed and one upstream test was ignored, covering routing, clipboard, direct terminal copy, link handling, protocol schema and client command compatibility. The full Rust suite did not complete: both parallel and serial runs terminated on SIGPIPE; the final serial run stopped at `server::headless::tests::client_shell_attach_seeds_workspace`. This is not a full-suite pass.
- Two real PTY clients shared one Yazi on a server with stale SSH/desktop variables. Ctrl+G followed A/B/A, Enter followed A/B, consumed gestures could not replay, and image paste delivered distinct valid PNGs from each client. OSC 52 shared-viewer refusal and copying after the second viewer disconnected passed. Desktop/clipboard programs were recorders, leaving the real clipboard untouched. Final artifacts: `/tmp/herdr-desktop-smoke-l066ea8x`.
- Native client file transfers passed in all six directions: PC to IW and back, PC to Mac and back, IW to Mac and back. These use real client input, Yazi, SSH and SFTP, with recorded ripdrag arguments. Saved-machine mode also passed on PC and Mac. Fixtures cover hovered file, multiselection, Unicode, quotes, newlines, duplicate basenames and unchanged originals. PC receiving from IW and Mac additionally passed progress and cancellation/retry checks.
- Installed builds pass `install.sh --check` on all three machines. Post-install transfers PC receiving from IW and Mac receiving from PC passed. Real ripdrag started on PC and Mac; the PC compositor reported its window mapped and visible. Actual mouse drop into another application remains untested. Test windows were closed after verification.
- Isolated live handoffs passed on Linux and Mac, including Mac 0.9.3 to the new 0.9.4. Production handoffs preserved 19 PC, 8 IW and 13 Mac pane IDs, shell PIDs and foreground process group IDs. Snapshots and logs: `.build/desktop-{before,after}.json`, `.build/desktop-live-handoff.log` on each machine.
- Fresh native UI clients were opened on all three computers. All six per-client saved-machine receivers reported ready. Closed the two older Linux UI clients and disabled the PC legacy `herdr-yazi-saved-drag.service`; servers and pane processes remain running. Existing unmanaged servers were not migrated to systemd during this update: desktop operations no longer depend on their inherited environment.
- Rollback binaries and checkout backups: `.build/desktop-routing-before/` on PC; `.build/before-desktop-routing/` on IW and Mac. Build receipts match the installed binary and patch. No commit, push or upstream PR was made.

Known limits and upgrade instructions are in [client desktop routing](docs/client-environment.ru.md). Plain SSH has no native desktop receiver. The GUI opener wrappers apply to Yazi launched by the link plugin; arbitrary existing shell processes retain their environment. OSC 52 from a pane with multiple active viewers is intentionally refused; use client selection for that case. Older clients and servers retain legacy routing.

# Herdr 0.9.4 rollout, 2026-10-14

- Pin: `7e26bad94044eba205033111a0ce8033ede7e24f`, Rust 1.98.1, Zig 0.16.0.
- Preserve upstream `plugin_link_failed` responses while porting client-context and plain-path patches. Pre-existing local changes were retained.
- Linux build: 93 Python tests and 189 selected Rust tests passed; one Rust test ignored by upstream.
- Local PTY tests: OSC 8, relative, absolute and home paths open real Yazi; missing paths do not. Local and SSH client-context checks passed.
- Live handoff: PC 0.9.3 to 0.9.4 preserved all 17 pane IDs, shell PIDs and foreground process groups. Ubuntu IW 0.9.2 to 0.9.4 preserved all 8. Both had isolated handoff tests before deployment.
- Both Linux installations pass `install.sh --check`. Saved profile IW is reachable. The PC saved-machine drag receiver service was enabled; IW receiver reports ready.
- IW remote PTY Ctrl-click tests passed. Ctrl+G tests passed for hovered files, multiselection, unusual filenames, repeated basenames, progress, cancellation, retry after cancellation and persistent directory rejection. Remote originals remained unchanged. Actual GUI drop into another application was not tested; ripdrag arguments were recorded.
- Logs and rollback binaries: `.build/*0.9.4*` and `.build/before-0.9.4/` on each updated host.
- Mac rollout pending network availability.

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

## Managed server integration, 2026-09-24

- Installed user unit passes `systemd-analyze --user verify`. Repeated installation preserves the entry point and shell config without restarting a server.
- Actual migration completed: the pinned 0.9.0 server runs under `herdr-yazi-server.service`, with graphical variables and no inherited SSH variables. Codex and Claude inherit its desktop environment.
- A real Mac client reconnected through the pinned `remote-client-bridge` to the same service-owned server. The server PID did not change. Agent image paste itself was not observed.
- `scripts/smoke-server.py` checks the actual pinned server under disposable services from local and SSH-like caller environments, including display variables, absence of SSH variables, service cgroup and detached SID.
- The 0.5.0 preparation adds tests for managed startup failure, update protection, installer idempotence, and local build receipts. Build and final check results are recorded below.

Final 0.5.0 checks: 87 Python tests and 77 targeted Rust tests passed. The release build passed OSC 8, relative, absolute, home, missing-home and missing-file terminal click checks. Both disposable systemd startup scenarios passed. `install.sh --check` passes every check with the generated local build receipt. Shell syntax and `git diff --check` pass. The production service remains active with PID 151035; publication did not restart it.

## Herdr 0.9.2 source update

Pinned upstream `48292af8e33a08c8030b7f1512c8d0da739f5ab1` with Rust 1.98.1 and Zig 0.16.0. On Linux, all 87 Python tests and 98 focused Herdr action tests pass. Real terminal Ctrl-click checks pass for OSC 8, relative, absolute and home paths; missing paths do not open a pane. The test terminal is 200 columns wide so the full selected filename fits in Yazi’s status line after its asynchronous metadata refresh.

The isolated 0.9.0-to-0.9.2 live handoff preserves the pane ID, shell PID and foreground process group. The old client disconnects as designed; a new client reconnects, the fixture redraws its OSC 8 link, and all click checks pass. Imported terminal IDs are regenerated and are not process identity. The systemd smoke verifies that `ExitType=cgroup` retains the service and pane IDs through handoff from local and SSH-like caller environments.

On the local managed `yazi-links` session, the 0.9.2 server is active, the current agent’s shell and foreground PIDs remain unchanged, and `install.sh --check` passes. Live handoff requires clients to reconnect; it is not a restart of pane processes.

The final Python suite passes 88 tests, including backup/idempotence for `--patched-entry` and protection against upstream updates without systemd management. macOS ARM64 also passes all 98 focused Herdr action tests. Remote Linux and macOS terminal tests pass OSC 8, relative, absolute and missing-path cases. On both hosts, real Yazi Ctrl+G/SFTP tests pass hovered and multi-selected files, Unicode and shell punctuation, repeated basenames, rendered progress, cancellation with partial-file cleanup, transfer after cancellation, and persistent directory rejection. Original files remain unchanged. The GUI drag endpoint is an argv recorder in these tests; dropping into another desktop application is not covered.

Both SSH hosts use the patched 0.9.2 entry for future discovery and report a 0.9.2 running server with no stale binary. Live handoff preserves all three Linux remote pane IDs and all eight macOS pane IDs, shell PIDs and foreground process groups. Previous dirty remote checkouts are retained in stashes named `before-herdr-0.9.2-deploy`; their code was already present upstream, while the updated documentation corrects the older local wording.

## Herdr 0.9.3 source update

Pinned upstream `7b116c05bfda646af39d2524c54e70c751f57ee8`; the existing path patch applies unchanged. The build now accepts a Git worktree's `.git` file, covered by a build-safety regression test. The final Python suite passes 89 tests. Focused Herdr action tests pass 98 cases on Linux and macOS; input tests pass 128 cases on Linux and 126 on macOS. GitHub Plugin checks also pass for the update commit.

Linux terminal smoke passes OSC 8, relative, absolute and home paths, missing-path rejection, and a 0.9.2-to-0.9.3 handoff with client reconnection. The managed service survives handoff in both local and SSH-like environments. Remote macOS Ctrl-click and Ctrl+G/SFTP checks pass, including multiselection, special filenames, progress, cancellation, transfer after cancellation, directory rejection and unchanged originals. As before, the drag tests record the ripdrag arguments rather than perform a desktop GUI drop.

The local and macOS working sessions run patched 0.9.3 without stale binaries; installation checks pass. Live handoff preserves 17 local and 8 macOS pane IDs, shell PIDs and foreground process groups. macOS additionally has the official 0.9.3 ARM64 binary at `~/.local/bin/herdr-stock`, verified against release SHA256 `5173a3e0ae42d5d1ab7ebfa5d5e6329f7c3d23f8e1a3677c7ce3231da2884157`; `herdr` and `herdr-yazi` use the patched build. IW Ubuntu is not updated in this deployment, at the user's request.
