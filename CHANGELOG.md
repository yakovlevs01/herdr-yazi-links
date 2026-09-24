# Changelog

## 0.5.0 (2026-09-24)

- Maintain local Yazi drag receivers for enabled saved SSH machines, with independent reconnects, profile refresh, and reuse by standalone remote clients.
- Fix drag routing for Herdr's default session.
- Add opt-in Linux/systemd/zsh server management with `./install.sh --managed-server`. Local and SSH clients of `yazi-links` share the pinned server and its desktop environment, without inheriting SSH variables.
- Preserve existing servers until an explicit migration. Reject direct upstream updates through the managed entry point; document Mac rediscovery, migration, diagnostics, and rollback.
- Record tested local builds and preserve them during installation when the upstream revision, patch and binary hashes still match. Published downloads retain their SHA256 checks.
- Expand `~/` in clicked plain-text paths using the Herdr server user's home directory, with resolver and terminal Ctrl-click regression coverage.
- Add service isolation, installer idempotence, local build receipt, and saved-machine receiver tests, plus English and Russian guides.

Upgrade notes: existing installations opt into server management explicitly. Already enabled installations retain it on reinstall. The existing pinned prebuilt downloads remain unchanged; the `~/` click fix requires `./build.sh`. No running Herdr session is restarted by installation.

## 0.4.1

- Cancel remote downloads from Yazi's task manager, stop active SFTP transfers, and clean partial downloads.
- Keep progress visible in narrow panes and explain when an older drag broker needs a reconnect.

## 0.4.0

- Add progress in the Yazi status bar through its Lua API: aggregate bytes, percent, file count, persistent errors and brief completion state. No system notifications or new binary patches.
- Track progress per request, stream updates asynchronously, and detect receiver disconnects without stale replay.
- Add `./install.sh` for dependencies, verified pinned Herdr/Yazi binaries, ripdrag, receiver, configuration backups, launcher and readiness checks.
- Preserve existing PATH priority; Herdr panes can use a managed compatible Yazi when the system version is older.
- Add installer and progress tests, plus a real Yazi/SFTP progress smoke check.


## 0.3.1

- Remove all receiver system notifications. Byte progress and errors remain in the receiver log and remote status.


## 0.3.0

- Send selected or hovered remote Yazi files to local ripdrag with Ctrl+G.
- Bind one receiver to each remote session, report conflicts, and expire disconnected receivers without replaying requests.
- Transfer through SFTP over system SSH into atomic retained cache batches, with progress, errors and explicit cleanup.
- Add a Yazi installer, isolated receiver dependencies, broker/transfer/installer tests and a real launcher remote smoke test.
- Preserve local ripdrag, original Herdr argv, pane command context and existing server lifetimes.


## 0.2.3

- Preserve caller sockets, pane IDs and sessions for control commands.
- Preserve PATH priority and explicit environment sessions.
- Avoid remote preparation for informational requests and duplicate remote flags.
- Document update, completion, saved-machine and shared-config exceptions.

## 0.2.2

- Start prepared servers in a new OS process session, fixing the SSH disconnect warning.
- Test actual preparation session IDs and preserve already running servers. Existing servers started by older preparation scripts need a deliberate restart after saving work.

## 0.2.1

- Forward the original Herdr arguments unchanged, including remote keybindings and future options.
- Respect explicit remote session names and separate preparation from the Herdr CLI.
- Avoid SSH/setup side effects for help, version and local commands.

## 0.2.0

- Prepare a remote patched session with `herdr-yazi --remote HOST`.
- Add real SSH Ctrl-click smoke tests and bilingual remote installation guides.
- Include user tool locations in the launcher PATH for noninteractive SSH shells.

## 0.1.0

- Open existing `file://` hyperlinks in a Yazi split beside the source pane.
- Optional Herdr patch recognizes absolute and relative plain-text paths on Ctrl-click.
- Resolve relative paths on the pane's host, using its process working directory.
- Include a pinned upstream revision, build script and regression tests.
- Validate locally on Linux. Remote sessions and macOS have not been tested.
- Add English and Russian guides for standalone installation and optional patched builds.
- Exercise real Ctrl-clicks and Yazi in isolated sessions; check stock and latest Herdr in CI.
- Check upstream candidates separately and preserve the installed executable on failed updates.
