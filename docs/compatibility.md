# Replacing herdr with herdr-yazi in commands

[Русский](compatibility.ru.md)

For application launch, `--remote`, pane/agent/workspace commands and status reads, changing the command name is usually sufficient. Arguments are forwarded unchanged. Since 0.2.3, control commands retain their caller's socket and pane IDs, including `--current` context.

This is not a fully separate Herdr installation:

| Scenario | Difference or exception |
|---|---|
| Launch without a selected session | Defaults to `yazi-links`. Existing projects and panes are not migrated |
| Control command inside a pane | Inherits that pane's socket, session and IDs, even if its server is stock Herdr |
| `--session NAME`, `session attach NAME` | Herdr selects the session. Attaching does not upgrade an existing server to the patched build |
| `herdr-yazi update` | The upstream updater may replace `.build/bin/herdr` with an official executable without the patch. Use the patched-build update procedure instead. This command is deliberately not intercepted |
| `--remote HOST` | Requires the checkout at the expected location, plugin, Python, Yazi and a suitable patched build on the host. Preparation does not install dependencies or replace a running server |
| `machine add` and saved machines | Native Herdr behavior; these do not call our `prepare.sh`. Prepare the remote session first, then select it with `--remote-session yazi-links` when adding a machine |
| Configuration and plugins | Use ordinary Herdr config directories. The session is separate, not the entire settings profile. Config/plugin/machine/channel commands can modify shared settings |
| `completion zsh` | Generates completion for `herdr`. After loading it and running `compinit`, add `compdef _herdr herdr-yazi` |
| External scripts containing literal `herdr` | Keep calling stock Herdr. Changing your interactive command does not rewrite integrations |
| New upstream features | The launcher forwards new arguments, but its pinned executable may not support them yet |

Do not run `update` as a compatibility probe: it mutates the executable. The updater source confirms it replaces the current executable.

Audit checks cover arguments and exit codes, `--current` against a real pane, help/version/default config/skill/API schema/completion output under the same session, and real SSH clicks against macOS with server keybindings. The launcher preserves existing PATH priority and appends fallback tool locations. These checks cover the exercised scenarios, not every future upstream change.
