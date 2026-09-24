# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Plasma 6 widget for self-hosted music libraries (Navidrome/Subsonic and Kodi),
split into a Python user service (`daemon/`) and a pure-QML applet
(`plasmoid/`). The split is not optional: MPRIS2 and audio playback cannot be
driven from QML, and keeping them in a daemon means music survives a
plasmashell restart. See `README.md` for the user-facing description.

## Commands

```sh
# Tests — self-contained: they generate their own audio and stub the services,
# so no music server is needed. They are plain scripts, not pytest.
cd daemon
python3 tests/test_player.py      # queue, shuffle, repeat, output switching, real mpv
python3 tests/test_protocol.py    # control protocol, two services connected

# Run the daemon by hand (stop the service first if it is installed)
systemctl --user stop streamplay
PYTHONPATH=daemon python3 -m streamplay -vv       # -v info, -vv debug
# --port --host --no-mpris --config are the other options

# Install / remove everything for the current user
./install.sh
./install.sh uninstall

# Reinstall just the applet after editing QML
kpackagetool6 --type Plasma/Applet --upgrade plasmoid/package
```

There is no build step, no linter configured, and no test runner. To run a
single check, comment out the others in the test file or add an early `return`.

## Verifying QML changes

**`qmllint` is useless here** — it silently skips the Plasma/Kirigami modules
and reports nothing, including for types that do not exist. Plasma also logs
QML errors to the journal rather than the terminal, and `console.log` from QML
does not reach the terminal at all. The working loop is:

```sh
kpackagetool6 --type Plasma/Applet --upgrade plasmoid/package
STAMP=$(date '+%Y-%m-%d %H:%M:%S'); sleep 1
QT_QPA_PLATFORM=offscreen timeout 12 plasmoidviewer -a org.kde.plasma.streamplay -f planar >/dev/null 2>&1
journalctl --user --since "$STAMP" --no-pager | grep streamplay
```

Empty output means it loaded cleanly. One bad type name kills the whole applet
via a cascade of "Type X unavailable", so always check this after touching QML.
`QT_QPA_PLATFORM=offscreen` keeps a window from appearing.

Config pages are loaded separately and can fail on their own. Check them with
`qml6` on the installed copy and read the journal the same way; `i18n is not
defined` is expected standalone and can be ignored, anything about a type
cannot.

Plasma type locations are easy to get wrong. `SearchField`, `Heading`,
`DescriptiveLabel`, `PlaceholderMessage` and `ListSectionHeader` live in
`org.kde.plasma.extras`; `TabBar`, `ComboBox`, `ScrollView`, `ItemDelegate` and
friends in `org.kde.plasma.components`. Check the module's `qmldir` before
using a type that is not already used somewhere in this repo.

## Architecture

### The central split: libraries, outputs, and one queue

The thing to understand before changing anything in `daemon/`:

- A **backend** (`backends/base.py: Backend`) is a library you can browse and
  get a `StreamTarget` out of.
- A **sink** (`backends/base.py: Sink`) is somewhere audio comes out. It plays
  one target at a time and reports eof; it knows nothing about queues.
- **`player.py: UnifiedPlayer`** owns the one and only queue, the play order,
  shuffle and repeat, and drives whichever sink is selected.
- **`hub.py: Hub`** holds every connected backend and sink, and acts as the
  player's *resolver*: `stream_target(track)` and `scrobble(track, submission)`
  dispatch to whichever service a track came from. The player never imports a
  backend.

Neither the library nor the output owns the queue, and that is deliberate — it
is what lets a Navidrome album and a Kodi album sit in one queue and play
through either destination. Do not move queue state into a backend or a sink.

Kodi appears **twice**: `KodiBackend` (library) and `KodiSink` (output), which
are independent. The sink drives Kodi one track at a time with `Player.Open`
and deliberately leaves Kodi's own playlist alone, because our queue is the
source of truth. `_expect_stop` distinguishes our own stop from the user
stopping playback on the Kodi box; `Player.OnStop` with `end: true` is the
end-of-track signal.

### Sources and ids

Every `Track`/`Album`/`Artist` carries a `source`, which is the profile id it
came from. **Library ids are only unique within one service**, so any call that
takes an id needs a source too. `library.*` methods without a `source` fan out
across all connected services and merge; with one, they target it. `Backend.tag()`
stamps the source on an item.

### Threading and event flow

- Everything in the daemon runs on one asyncio loop, except MPRIS.
- **MPRIS runs in its own GLib thread** (`mpris.py`) because dbus-python needs a
  GLib main loop. Crossing in: `MprisService.dispatch()` →
  `loop.call_soon_threadsafe`. Crossing out: `push_state`/`push_seeked` →
  `GLib.idle_add`. Never touch the D-Bus object from the asyncio loop or the
  player from the GLib thread.
- **mpv events must not be handled inside the socket reader.** `mpvproc.py`
  puts them on an `asyncio.Queue` consumed by a separate task. Handling them
  inline deadlocks: an end-of-file handler issues a new mpv command and then
  waits for a reply that only the blocked reader could deliver. This was a real
  bug; keep the queue.
- mpv reports the play position many times a second. `UnifiedPlayer._on_sink_changed`
  diffs the state and emits a small rate-limited `position` event when only
  progress changed, and a full `state` push otherwise. Use `_changed()` for
  genuine state transitions, not for progress.

### Applet ↔ daemon

One WebSocket on `127.0.0.1:8760` carries JSON-RPC-ish calls
(`{"id", "method", "params"}` → `{"id", "ok", "result"|"error"}`) plus pushed
`state`, `position`, `queue`, `sources`, `profiles` and `seeked` events. The
same port serves cover art over plain HTTP at `/cover?src=…&id=…&size=…` via
`websockets`' `process_request` hook, so QML's `Image` can load artwork and the
applet never holds any credentials.

`Client.qml` is the whole transport. Two things there matter:

- `_adopt()` compares before assigning `sources`/`outputs`. The daemon repeats
  those lists in every state push, and a plain assignment to a `property var`
  fires a change signal every time, which made `LibraryPane` reload the library
  several times a second. Keep the comparison.
- `displayPosition` is interpolated by a timer between the daemon's ~1 Hz
  updates, and `scrubbing` suppresses that while the user drags the seek bar.

### QML scoping

The panes reference `root.client` and `root.track` across file boundaries. That
works because QML resolves ids through the *creation context*, and every pane is
instantiated from `main.qml`. Config pages are a separate QML context, so
`ConfigServers.qml` creates its **own** `Client` (`import ".." as Sp`) and reads
the daemon host/port from plain `cfg_*` properties that Plasma fills in.

## Configuration and secrets

`~/.config/streamplay/config.json` holds all profiles and settings, written
0600 because it contains backend passwords in plain text. Two rules:

- `Config.upsert()` treats a missing or empty `password` as "keep the stored
  one", so the applet can save an edited profile without ever holding the
  secret.
- `Profile.redacted()` is what goes over the wire — it strips `password` and
  replaces it with a `hasPassword` boolean. Never send a raw profile to the
  applet.

Playback settings (volume, shuffle, repeat) are written back on a delay by
`Hub._schedule_settings_flush` so a volume drag does not thrash the file.
