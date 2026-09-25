#!/bin/sh
# Runs the daemon bundled with the applet as a transient systemd user unit, so it outlives plasmashell.
# Exit codes: 3 no bundled daemon, 2 dependencies missing (listed on stdout).

here=$(cd "$(dirname "$0")" && pwd)
unit=streamplay-applet
icon=${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/io.github.leissa.streamplay.svg

# The widget picker only looks icons up in the theme, never in the package.
[ -f "$icon" ] || install -Dm644 "$here/../icons/streamplay.svg" "$icon" 2>/dev/null

[ -d "$here/streamplay" ] || exit 3
export PYTHONPATH="$here" PYTHONDONTWRITEBYTECODE=1
python3 -m streamplay.check || exit 2
[ "${1:-}" = start ] || exit 0

systemctl --user stop "$unit" 2>/dev/null
systemctl --user reset-failed "$unit" 2>/dev/null
exec systemd-run --user --quiet --collect --unit="$unit" \
    --description="Streamplay music service (applet)" \
    --setenv=PYTHONPATH="$here" --setenv=PYTHONDONTWRITEBYTECODE=1 \
    --property=Restart=on-failure --property=RestartSec=3 \
    python3 -m streamplay
