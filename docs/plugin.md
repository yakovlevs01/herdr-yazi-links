# Open file links in Yazi

A community Herdr plugin that opens a clicked file hyperlink in a Yazi pane on the right. Yazi selects the target file or opens the target directory. Press `q` to close it.

[Русский](plugin.ru.md) · [Repository overview](../README.md)

## Install

Install Herdr with a compatible plugin API, Python 3 and Yazi. Python and Yazi must be in the Herdr server's PATH.

```sh
herdr plugin install yakovlevs01/herdr-yazi-links
```

No custom Herdr binary or wrapper is required for this mode. We verified it on stock Linux Herdr 0.9.0. Later versions need the checks below. See the remote guide for SSH checks.

For development, clone the repository and link it:

```sh
herdr plugin link /absolute/path/to/herdr-yazi-links
```

## What the application must output

The clickable item must be a terminal OSC 8 hyperlink whose target is an absolute file URI:

```text
file:///home/user/project/README.md
```

The protocol format is `ESC ] 8 ; ; URI ST LABEL ESC ] 8 ; ; ST`. Here `ESC` is byte `0x1b` and `ST` is `ESC` followed by a backslash. Use percent encoding for URI characters such as spaces, `#` and `%`. The file or directory must exist on the machine running the Herdr server. Empty authority, `localhost`, or that server's hostname are accepted.

An agent can write this Markdown:

```markdown
[README.md](file:///home/user/project/README.md)
```

It works only if the agent application renders it as OSC 8 and preserves the `file://` target. Markdown text alone is not enough. Neither a code span such as `README.md` nor printing the literal URI guarantees a clickable hyperlink. The label can be a relative filename, but the URI target must contain an absolute path.

## Try it without an agent

Clone this repository, enter it in a Herdr pane, and run:

```sh
python3 scripts/demo.py
```

Ctrl-click the file hyperlink. Yazi should open beside the source pane. The demo also prints ordinary paths for comparison; stock Herdr does not recognize those through this plugin.

Run automated checks from the checkout:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/smoke.py --herdr /usr/bin/herdr
```

The smoke test uses an isolated configuration and session, sends real terminal Ctrl-click events, and checks that real Yazi selects the target file. Herdr and Yazi must be installed. It also verifies that ordinary paths do not invoke the plugin on stock Herdr. Run the demo to check your particular terminal and keybindings.

## Troubleshooting and limits

If a click does nothing, test the demo first. If the demo works, check whether your application emits OSC 8 file hyperlinks. If a click reaches the plugin but Yazi does not open, inspect:

```sh
herdr plugin log list --plugin local.yazi-links
```

Yazi runs on the Herdr server that owns the clicked pane. A remote server would need the plugin, Python and Yazi installed there. Opening remote Yazi does not transfer a file to your local computer.

The plugin validates the path and passes it as an argument, without evaluating it as a shell command. Ordinary paths in prose require the [optional Herdr patch](patched-herdr.md).

## Publishing this plugin

Publish this repository on GitHub with public visibility, keep `herdr-plugin.toml` on the default branch and add the topic `herdr-plugin`. The root manifest installs this plugin only. Users do not need the optional patch or its build dependencies for file hyperlinks.

Update the manifest version and changelog for each release, and tag it `vMAJOR.MINOR.PATCH`. The community marketplace automatically indexes eligible repositories and excludes forks. A listing is not an official endorsement. See [the marketplace documentation](https://herdr.dev/docs/marketplace/).

Licensed under [Apache-2.0](../LICENSE).

GitHub Actions runs unit tests and the stock smoke test against Herdr 0.9.0 and the latest release on changes and weekly.

For SSH host installation and agent-free tests, see [remote operation](remote.md).
