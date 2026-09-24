#!/usr/bin/env bash
set -euo pipefail
plugin_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
build_dir=${HERDR_YAZI_BUILD_DIR:-"$plugin_dir/.build"}
metadata=${HERDR_YAZI_UPSTREAM_FILE:-"$plugin_dir/patches/upstream.toml"}
mapfile -t upstream < <(python3 - "$metadata" <<'PY'
import sys, tomllib
with open(sys.argv[1], 'rb') as file:
    config = tomllib.load(file)
for key in ('repository', 'revision', 'rust', 'zig', 'patch'):
    print(config[key])
PY
)
repository=${upstream[0]}
revision=${upstream[1]}
source_dir="$build_dir/source-$revision"
toolchain=${HERDR_YAZI_TOOLCHAIN:-${upstream[2]}}
patch_file="$plugin_dir/patches/${upstream[4]}"
command -v "${ZIG:-zig}" >/dev/null || { echo 'Set ZIG to the required Zig executable.' >&2; exit 1; }
test "$("${ZIG:-zig}" version)" = "${upstream[3]}" || { echo "Expected Zig ${upstream[3]}" >&2; exit 1; }
python3 -m unittest discover -s "$plugin_dir/tests" -v
mkdir -p "$build_dir/bin"
if [ ! -d "$source_dir/.git" ]; then
    git init "$source_dir"
    git -C "$source_dir" remote add origin "$repository"
    git -C "$source_dir" fetch --depth 1 origin "$revision"
    git -C "$source_dir" checkout --detach FETCH_HEAD
fi
test "$(git -C "$source_dir" rev-parse HEAD)" = "$revision"
if git -C "$source_dir" apply --check "$patch_file"; then
    git -C "$source_dir" apply "$patch_file"
else
    git -C "$source_dir" apply --reverse --check "$patch_file"
fi
cd "$source_dir"
export CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-"$build_dir/target"}
cargo +"$toolchain" test --locked --bin herdr app::actions::tests::
cargo +"$toolchain" build --locked --release
python3 "$plugin_dir/scripts/smoke.py" --herdr "$CARGO_TARGET_DIR/release/herdr" --expect-paths --expect-home-paths --plugin "$plugin_dir"
# Replace atomically; an already running server keeps its old executable.
candidate=$(mktemp "$build_dir/bin/herdr.XXXXXXXX")
trap 'rm -f -- "$candidate"' EXIT
install -m755 "$CARGO_TARGET_DIR/release/herdr" "$candidate"
mv -f -- "$candidate" "$build_dir/bin/herdr"
# A receipt lets install.sh preserve a tested local build instead of downloading
# an older release. It is checked against the current pin, patch and binary.
python3 - "$build_dir/bin/herdr" "$revision" "$patch_file" <<'RECEIPT'
import hashlib, json, pathlib, sys
binary, revision, patch = sys.argv[1:]
def digest(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
receipt = pathlib.Path(binary + '.build.json')
temporary = receipt.with_suffix('.tmp')
temporary.write_text(json.dumps({'revision': revision, 'sha256': digest(binary),
                                 'patch_sha256': digest(patch)}, indent=2) + '\n')
temporary.replace(receipt)
RECEIPT
echo "Built and tested: $build_dir/bin/herdr"
