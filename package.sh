#!/usr/bin/env bash
#
# Build the .plasmoid for the KDE Store: the applet with the daemon bundled in contents/code.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$HERE/build"

die() { printf '\033[31m==>\033[0m %s\n' "$*" >&2; exit 1; }

applet=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["KPlugin"]["Version"])' \
         "$HERE/plasmoid/package/metadata.json")
daemon=$(PYTHONPATH="$HERE/daemon" python3 -c 'import streamplay; print(streamplay.__version__)')
# The applet restarts a bundled daemon whose version differs, so a mismatch would restart it forever.
[ "$applet" = "$daemon" ] || die "Version mismatch: applet $applet, daemon $daemon"

stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cp -r "$HERE/plasmoid/package/." "$stage/"
cp -r "$HERE/daemon/streamplay" "$stage/contents/code/streamplay"
find "$stage" -name __pycache__ -type d -prune -exec rm -rf {} +

mkdir -p "$OUT"
target="$OUT/streamplay-$applet.plasmoid"
rm -f "$target"
(cd "$stage" && zip -qr "$target" .)
printf '\033[1m==>\033[0m %s\n' "$target"
