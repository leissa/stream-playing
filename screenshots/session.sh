#!/usr/bin/env bash
#
# Runs inside the nested KWin: session.sh OUT.png COLORSCHEME DESKTOPTHEME

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out=$1

plasma-apply-colorscheme "$2" >/dev/null 2>&1
plasma-apply-desktoptheme "$3" >/dev/null 2>&1

plasmashell --no-respawn >>"$STAGE/plasmashell.log" 2>&1 &
shell=$!
sleep 6
qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript \
    "$(cat "$HERE/layout.js")" >>"$STAGE/plasmashell.log" 2>&1
# Shot.js opens the popup a few seconds after the widget loads; covers need a moment more.
sleep 8
spectacle --background --nonotify --fullscreen --output "$out" >>"$STAGE/spectacle.log" 2>&1
kill "$shell"
