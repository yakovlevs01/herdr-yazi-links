#!/bin/sh
# Run on the computer that will display ripdrag. Sender installation is separate.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
command -v ripdrag >/dev/null || { echo 'Install ripdrag on this computer first.' >&2; exit 1; }
python3 -m venv "$root/.build/drag-venv"
"$root/.build/drag-venv/bin/python" -m pip install 'paramiko>=3.4,<6'
echo 'Receiver enabled for herdr-yazi --remote. Files stay in ~/.cache/herdr-yazi-drag.'
