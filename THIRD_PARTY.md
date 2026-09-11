# Third-party code

`patches/herdr-path-click.patch` contains modifications and context from
[Herdr](https://github.com/herdrdev/herdr), distributed under Apache-2.0 at the
revision recorded in `patches/upstream.toml`.

The patch adds path recognition to the click handler in `src/app/actions.rs`
and adds tests. It does not change the server protocol or the plugin API.

The build script downloads Herdr separately. Its sources, vendored dependencies,
build outputs and executable are excluded from this repository. Their original
licenses continue to apply; this repository does not relicense them.

The plugin and build support in this repository are distributed under Apache-2.0.
