# Stream Playing

A Plasma 6 widget for self-hosted music libraries. It connects to
**Navidrome / Subsonic-compatible** servers, to **Kodi** and to **MPD** —
several of them at the same time — and puts everything into a single shared
queue that can be played on this computer or on any connected Kodi or MPD
instance. It registers itself with KDE as an MPRIS2 player, so Now Playing, the
media keys and the lock screen all control it.

## What it does

- **Several services at once.** Each server has its own on/off switch; browsing
  merges the connected ones into one library, with a badge on every row saying
  where it came from. A filter narrows it back to a single service.
- **One queue for all of them.** A Navidrome album and a Kodi album can sit next
  to each other in the same queue and play one after the other.
- **Pick where it plays.** The queue can go to this computer's speakers (via
  mpv), to a Kodi instance or to MPD. Switching mid-track carries the position
  over.
- **The usual transport.** Play, pause, stop, next, previous, seek, rewind by
  dragging the progress bar, volume, shuffle and three repeat modes.
- **Queue editing.** Enqueue, play next, replace, remove, drag to reorder,
  clear, and jump to any entry.
- **Browsing.** By album, artist, genre or server-side playlist, plus search
  across every connected service at once.
- **KDE integration.** MPRIS2 means media keys, Now Playing in the system tray,
  and the volume OSD all work without any extra setup.

## How it is put together

MPRIS and audio playback cannot be done from QML alone, so the work is split in
two. A small user service owns everything stateful; the widget is a view onto
it. That also means music keeps playing if plasmashell is restarted.

```
┌─────────────────────────────┐
│  Plasma applet (pure QML)   │   panel icon, popup, settings pages
└──────────────┬──────────────┘
               │  WebSocket + HTTP on 127.0.0.1:8760
┌──────────────▼──────────────┐
│  streamplay (Python)        │
│  ┌───────────────────────┐  │
│  │ one queue             │  │   order, shuffle, repeat, current track
│  ├───────────┬───────────┤  │
│  │ libraries │  outputs  │  │
│  │ Subsonic  │  mpv      │  │   any library can play on any output
│  │ Kodi      │  Kodi     │  │
│  │ MPD       │  MPD      │  │
│  └───────────┴───────────┘  │
│  MPRIS2 ──────> D-Bus       │
└─────────────────────────────┘
```

A *library* is something you browse; an *output* is somewhere audio comes out.
Kodi and MPD are both. Because neither owns the queue, tracks from one service
can play through the other: Kodi songs are streamed locally over Kodi's own HTTP
server, and Subsonic streams can be handed to Kodi or MPD as a URL.

MPD is the one asymmetric case. It serves no audio over its control port, so
playing its music anywhere other than on MPD itself needs the files to be
readable from this computer as well — see the music folder setting below.

## Requirements

Everything below is packaged on Arch and most other distributions:

| Needed for | Package |
| --- | --- |
| the service | `python`, `python-requests`, `python-websockets` |
| local playback | `mpv` |
| Now Playing / media keys | `python-dbus`, `python-gobject` |
| the widget | `plasma-workspace` (Plasma 6) |

## Install

```sh
./install.sh
```

This copies the service to `~/.local/share/streamplay`, adds a
`~/.local/bin/streamplayd` launcher, enables the `streamplay` systemd user
service, and installs the widget. Nothing is written outside `$HOME`.

Then add the **Stream Playing** widget to a panel or the desktop, open its
settings and add your servers.

To remove everything again (your servers and settings are kept):

```sh
./install.sh uninstall
```

## Adding servers

Open the widget's settings → **Music Servers** → *Add Navidrome / Subsonic…*,
*Add Kodi…* or *Add MPD…*.

- **Navidrome / Subsonic** needs the base URL (`https://music.example.org`, not
  the `/rest` path), a username and a password. The password is never sent in
  the clear: each request carries a salted MD5 token instead. Very old servers
  that do not understand this can be switched to the legacy format.
- **Kodi** needs the host, the web interface port (8080 by default) and the
  event port (9090). In Kodi, turn on *Settings → Services → Control → Allow
  remote control via HTTP* and *Allow remote control from applications on other
  systems*. A username and password are optional but recommended.
- **MPD** needs the host and port (6600 by default), and a password only if
  `password` is set in `mpd.conf`. MPD 0.21 or newer is required.

  The **music folder** is optional but worth filling in. MPD hands out no audio
  itself, so without it MPD's music can only be played on MPD; with it — the
  same path as `music_directory` in `mpd.conf`, as this computer sees it — its
  tracks play on the local speakers and on Kodi as well. For an MPD on another
  machine that means the library has to be mounted here, at whatever path you
  enter.

  If MPD listens on a unix socket, put its path under `socket` in
  `config.json`; the settings dialog has no field for it. That is worth doing
  for a local MPD, because MPD tells a socket client where its music lives and
  the music folder then fills itself in.

**Test Connection** checks the settings without touching the live connection.
**Save and Connect** applies them immediately. Each server's switch controls
whether it is connected, and several can be on at once.

## Where things are kept

| What | Where |
| --- | --- |
| servers and settings | `~/.config/streamplay/config.json` (mode 0600) |
| cover art cache | `~/.cache/streamplay/covers/` |
| the service | `~/.local/share/streamplay/` |
| the widget | `~/.local/share/plasma/plasmoids/org.kde.plasma.streamplay/` |

`config.json` holds backend passwords in plain text, which is why it is created
with owner-only permissions. It can be edited by hand while the service is
stopped.

## Running the service by hand

Useful when something is not working:

```sh
systemctl --user stop streamplay
~/.local/bin/streamplayd -vv          # -v for info, -vv for debug
```

Other options: `--port` to move it off 8760, `--host` to bind elsewhere,
`--no-mpris` to skip the D-Bus registration, `--config` for a different
configuration file.

## Troubleshooting

**The widget says the service is not running.** Check
`systemctl --user status streamplay` and `journalctl --user -u streamplay -n 50`.
If you changed the port, change it in the widget's settings too.

**A server shows as failed.** The settings page prints the reason underneath its
name. For Kodi that is usually remote control not being enabled; for Navidrome,
a wrong URL or password; for MPD, `bind_to_address` in `mpd.conf` not covering
the address you gave.

**MPD tracks will not play on the local speakers.** That is the music folder
setting: without it the daemon has no path to the files, and MPD offers none.
The widget will still play them on MPD itself.

**Media keys do nothing.** MPRIS needs `python-dbus` and `python-gobject`. Check
with `busctl --user list | grep mpris` — `org.mpris.MediaPlayer2.streamplay`
should be listed while the service runs.

**Nothing comes out of the speakers.** Local playback goes through mpv, so
`mpv some-file.flac` failing points at the audio setup rather than at this
widget.

**QML errors after editing the widget.** Plasma logs them to the journal rather
than the terminal:

```sh
journalctl --user --since "2 minutes ago" | grep streamplay
```

## Tests

```sh
cd daemon
python3 tests/test_player.py     # queue, shuffle, repeat, output switching, with real mpv
python3 tests/test_protocol.py   # the control protocol, with two services connected
python3 tests/test_mpd.py        # the MPD library and output, against a stub MPD
```

They are self-contained: they generate their own audio and use stub services,
so no music server is needed.

## Control protocol

The applet talks to the service over one WebSocket on `127.0.0.1:8760`. Requests
are `{"id": 1, "method": "queue.add", "params": {…}}` and replies are
`{"id": 1, "ok": true, "result": {…}}`. The service also pushes `state`,
`position`, `queue`, `sources`, `profiles` and `seeked` events. Cover art is
served over plain HTTP from the same port at `/cover?src=…&id=…&size=…`, so the
widget never needs any credentials.

Anything that speaks WebSocket can drive it; `library.*`, `queue.*`, `player.*`,
`sources.*`, `outputs.*` and `profiles.*` are the method groups.

## Licence

GPL-3.0-or-later.
