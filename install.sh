#!/bin/sh
# Install this checkout on the current machine. Never starts/stops Herdr sessions.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "${1:-}" in
  -h|--help) cat <<'HELP'
Usage: ./install.sh [--sender-only] [--check]
Install the pinned patched Herdr, Yazi Ctrl+G/progress plugin and launcher.
Also installs local ripdrag and SSH download support by default.
Use --sender-only for machines that only send files. --check reports readiness without changing files.
Package installation may ask for sudo. Existing sessions are not restarted.
HELP
    exit 0 ;;
esac
for option in "$@"; do
    case "$option" in --sender-only|--check) ;; *) echo "Unknown option: $option (use --help)" >&2; exit 2 ;; esac
done
# Keep the user's PATH order; add conventional tool locations only as fallbacks.
PATH="${PATH:-/usr/bin:/bin}:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$HOME/.cargo/bin"
export PATH
python=
for candidate in python3 python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
        python=$(command -v "$candidate")
        break
    fi
done
if [ -z "$python" ]; then
    case " $* " in *' --check '*) echo 'Missing Python 3.11+' >&2; exit 1;; esac
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get update
        sudo apt-get install -y python3 python3-venv ca-certificates
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y python3 python3-pip ca-certificates
    elif command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm python python-pip ca-certificates
    elif [ "$(uname -s)" = Darwin ]; then
        if ! command -v brew >/dev/null 2>&1; then
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        brew install python@3.13
    else
        echo 'Unsupported package manager. Python 3.11+ is required.' >&2
        exit 1
    fi
    for candidate in python3 python3.13 /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
            python=$(command -v "$candidate")
            break
        fi
    done
fi
[ -n "$python" ] || { echo 'This OS does not provide Python 3.11+. Upgrade the OS/Python and rerun.' >&2; exit 1; }
exec "$python" "$root/scripts/install-machine.py" "$@"
