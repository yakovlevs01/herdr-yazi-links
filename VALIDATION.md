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
