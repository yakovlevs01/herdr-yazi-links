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

Release 0.4.0 distributes the already tested patched Herdr binaries for Linux
x86_64 and macOS ARM64. Their upstream revision is
`48292af8e33a08c8030b7f1512c8d0da739f5ab1`; the changes are in
`patches/herdr-path-click.patch`. The repository LICENSE contains Apache-2.0.
Upstream source and dependency notices remain available in
[the pinned Herdr source](https://github.com/herdrdev/herdr/tree/48292af8e33a08c8030b7f1512c8d0da739f5ab1).
The installer downloads Yazi from its official release and installs ripdrag
through Cargo; their respective upstream licenses apply.
