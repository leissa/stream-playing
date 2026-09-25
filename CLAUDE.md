# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Plasma 6 widget for self-hosted music libraries (Navidrome/Subsonic, Kodi and
MPD), split into a Python user service (`daemon/`) and a pure-QML applet
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
python3 tests/test_mpd.py         # MPD library + output against tests/fake_mpd.py

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

**The loop above does not exercise the config pages** — they are only loaded
when the settings dialog is opened, so they can be broken while the applet
verifies clean. Two separate things to check by hand after touching them:

1. `ConfigCategory.source` in `contents/config/config.qml` is resolved relative
   to **`contents/ui/`**, not to `contents/`. Our pages live in
   `contents/ui/config/`, so the correct value is `config/ConfigGeneral.qml`.
   Getting this wrong gives categories that appear in the dialog with empty
   content and no error anywhere, because Plasma does not log the miss. Verify
   with `test -f contents/ui/$source` for each entry.
2. The page's own QML. Run `qml6` against the installed copy and read the
   journal the same way; `i18n is not defined` is expected standalone and can be
   ignored, anything about a type cannot. Beware that a failed `i18n` call also
   produces *downstream* errors that look real: a property built from `i18n()`
   ends up undefined, so every reader of it reports `TypeError: Cannot read
   property 'x' of undefined`. To tell a genuine fault from this noise, copy the
   page to a scratch directory, give the copy `i18n`/`i18nc`/`i18np` stubs that
   return their text, and run that instead — it also lets a probe call the
   page's own functions and print results with `console.warn`, which reaches
   the journal.

Plasmashell caches an applet's package per instance, so after changing anything
under `config/` the settings dialog has to be closed and reopened, and
sometimes plasmashell restarted, before the change shows up.

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

Kodi and MPD each appear **twice**: a `*Backend` (library) and a `*Sink`
(output), which are independent. Both sinks drive their service one track at a
time and deliberately leave its own playlist alone, because our queue is the
source of truth. Adding another such service means adding it to `BACKEND_TYPES`
*and* `PLAYBACK_TYPES` in `backends/__init__.py`, teaching `create_sink` about
it, and setting `Sink.source` on the sink -- that is what lets `Hub._drop_source`
tear the output down with the library without knowing any type names.

Kodi's sink uses `Player.Open` and `_expect_stop` to tell our own stop from the
user stopping playback on the Kodi box; `Player.OnStop` with `end: true` is the
end-of-track signal.

### MPD's two awkward corners

- **It cannot say why it stopped.** `status` reports a bare `state: stop`
  whether the song ran out or somebody pressed stop in ncmpcpp. `MpdSink` guesses
  from how far in the track was, carrying the last position forward by wall-clock
  time (`_note_position` / `_near_end`) -- a short track can start *and* end
  between two polls, so the raw last reading is not enough. `_changing` covers
  the opposite case: replacing the queue takes MPD through `stop`, and that
  momentary stop must not be read as the track ending.
- **It serves no audio.** There is no URL to hand to mpv or Kodi, so
  `MpdBackend._local` turns MPD's relative path into a `file://` URL using the
  profile's `musicDirectory`. Without it, MPD tracks only play on MPD, and
  `stream_target` returns a target with `native` but no `url`.

Two smaller things: `list ... group date` splits one album in two when its
tracks disagree about the date, so `_album_list` folds the duplicates back
together; and `list`/`find` match case-sensitively while `search` does not,
which is why `MpdBackend.search` filters artists and albums in Python instead
of asking MPD to.

### Sources and ids

Every `Track`/`Album`/`Artist` carries a `source`, which is the profile id it
came from. **Library ids are only unique within one service**, so any call that
takes an id needs a source too. MPD has no ids at all, so a tag value *is* the
id there: a track's id is its path inside the music directory, an artist's is
their name, and an album's is `albumartist + "\x1f" + album`. `library.*` methods without a `source` fan out
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

Cover art normally comes from `Backend.cover_request()`, an HTTP URL the
`CoverCache` fetches in a thread. MPD has no such URL -- it sends the image down
the control connection in chunks -- so it implements `Backend.cover_bytes()`
instead, which the cache tries first and runs on the event loop.

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
