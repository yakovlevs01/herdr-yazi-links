#!/bin/sh
# Explicit setup helper, separate from the upstream Herdr command-line interface.
set -eu
plugin_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
binary="$plugin_dir/.build/bin/herdr"
session=${1:-yazi-links}
unset HERDR_SOCKET_PATH HERDR_CLIENT_SOCKET_PATH HERDR_ENV
unset HERDR_PANE_ID HERDR_WORKSPACE_ID HERDR_TAB_ID
PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH
"$binary" --session "$session" plugin link "$plugin_dir" >/dev/null
if ! "$binary" --session "$session" pane list >/dev/null 2>&1; then
    nohup "$binary" --session "$session" server >>"$plugin_dir/.build/session-start.log" 2>&1 </dev/null &
    attempt=0
    until "$binary" --session "$session" pane list >/dev/null 2>&1; do
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 100 ]; then
            echo "Server did not start; see $plugin_dir/.build/session-start.log" >&2
            exit 1
        fi
        sleep 0.1
    done
fi
