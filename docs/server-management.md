# Managed desktop server

On Linux with systemd and zsh, opt in with `./install.sh --managed-server`.
Subsequent installations preserve this choice. Existing installations can run
`python3 scripts/install-server.py` without downloading binaries.
The default installation remains usable on headless hosts and other shells.

The installer registers `herdr-yazi-server.service`, links `~/.local/bin/herdr`
to the managed entry point, and adds its PATH entry to `.zshenv` for SSH discovery.
It does not change `/usr/bin/herdr` or stop running servers. Both `herdr-yazi` and
remote clients targeting `yazi-links` use the pinned binary through the service.
Other session names retain their original startup behavior.

The service starts on demand, using the user manager's desktop environment.
It drops SSH and inherited pane/session variables and requires a local display
socket. Import your compositor's environment into `systemd --user` at desktop
login if it does not already do so. A local graphical launcher also imports its
display variables. SSH callers never import theirs. Missing display access fails
without falling back to a server launched from SSH.

## Migrate an existing session

Legacy servers remain running with a warning until you explicitly migrate them.
Save work first: stopping the server ends all pane processes. From a separate
local terminal outside Herdr:

```sh
/usr/bin/herdr --session yazi-links server stop
python3 ~/pets/herdr-yazi-links/scripts/server-manager.py ensure
herdr-yazi
```

Resume agent conversations using their own resume commands. Restart the Mac
client so it rediscovers `~/.local/bin/herdr` instead of its previously selected
system executable. Check discovery with `ssh HOST 'command -v herdr'`. Saved
machine profiles must target the `yazi-links` session.

## Maintenance

```sh
systemctl --user status herdr-yazi-server.service
journalctl --user -u herdr-yazi-server.service
./install.sh --check
python3 scripts/smoke-server.py
```

The smoke test uses a disposable service and configuration. It checks actual
server startup, display environment, absence of SSH variables, cgroup ownership
and detached SID from both local and SSH-like caller environments. It does not
verify Mac UI behavior or image paste into agents.

Use the project's pinned build/install workflow for updates. The managed entry
rejects `update` and `channel` to prevent upstream's updater overwriting the
patched binary. Direct executable paths bypass this protection. Running servers
are not restarted by installation. `build.sh` records the binary hash, upstream
revision and patch hash after successful checks; the installer preserves local
builds with a matching receipt. This receipt is local build metadata, not a
cryptographic signature. Published downloads keep their release SHA256 checks.

A user service is not a logind graphical session. Desktop features require a
running desktop, and already-running processes do not inherit subsequent
compositor environment changes.

To remove the integration, save work and stop the service, remove the managed
`~/.local/bin/herdr` link and restore its backup if present, remove the added
`.zshenv` block, `.build/server-management.json`, and the unit file, then run
`systemctl --user daemon-reload`.
