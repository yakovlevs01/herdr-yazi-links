# Changelog

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
