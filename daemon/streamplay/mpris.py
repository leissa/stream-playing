"""MPRIS2 D-Bus interface, so KDE's Now Playing / media keys drive the daemon.

dbus-python needs a GLib main loop, which does not coexist with asyncio in one
thread. The service therefore runs its own thread: incoming D-Bus calls are
forwarded to the asyncio loop with ``run_coroutine_threadsafe`` and state
updates are pushed back with ``GLib.idle_add``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

log = logging.getLogger(__name__)

BUS_NAME = "org.mpris.MediaPlayer2.streamplay"
OBJECT_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

TRACK_PATH_PREFIX = "/org/kde/streamplay/track/"
NO_TRACK = "/org/mpris/MediaPlayer2/TrackList/NoTrack"

STATUS_TO_MPRIS = {"playing": "Playing", "paused": "Paused", "stopped": "Stopped"}
LOOP_TO_MPRIS = {"none": "None", "all": "Playlist", "one": "Track"}
LOOP_FROM_MPRIS = {"None": "none", "Playlist": "all", "Track": "one"}

_UNSAFE = re.compile(r"[^A-Za-z0-9_]")


class MprisObject(dbus.service.Object):
    """The exported ``/org/mpris/MediaPlayer2`` object.

    Only ever touched from the GLib thread.
    """

    def __init__(self, bus_name: dbus.service.BusName, bridge: "MprisService") -> None:
        super().__init__(bus_name, OBJECT_PATH)
        self._bridge = bridge
        self._state: dict[str, Any] = {}
        self._state_at = time.monotonic()

    # -------------------------------------------------------------- helpers

    def _dispatch(self, coro_factory: Callable[[], Any]) -> None:
        self._bridge.dispatch(coro_factory)

    @property
    def _status(self) -> str:
        return STATUS_TO_MPRIS.get(self._state.get("status", "stopped"), "Stopped")

    def _position_us(self) -> int:
        position = float(self._state.get("position") or 0.0)
        if self._state.get("status") == "playing":
            # Interpolate so scrubbers move smoothly between daemon updates.
            position += max(0.0, time.monotonic() - self._state_at)
            duration = float(self._state.get("duration") or 0.0)
            if duration:
                position = min(position, duration)
        return int(position * 1_000_000)

    def _metadata(self) -> dbus.Dictionary:
        track = self._state.get("track")
        if not track:
            return dbus.Dictionary(
                {"mpris:trackid": dbus.ObjectPath(NO_TRACK)}, signature="sv")

        uid = _UNSAFE.sub("_", str(track.get("uid") or track.get("id") or "0"))
        meta: dict[str, Any] = {
            "mpris:trackid": dbus.ObjectPath(TRACK_PATH_PREFIX + uid),
            "xesam:title": dbus.String(track.get("title") or ""),
        }
        duration = float(self._state.get("duration") or track.get("duration") or 0)
        if duration:
            meta["mpris:length"] = dbus.Int64(int(duration * 1_000_000))
        if track.get("artist"):
            meta["xesam:artist"] = dbus.Array(
                [dbus.String(track["artist"])], signature="s")
            meta["xesam:albumArtist"] = dbus.Array(
                [dbus.String(track["artist"])], signature="s")
        if track.get("album"):
            meta["xesam:album"] = dbus.String(track["album"])
        if track.get("trackNo"):
            meta["xesam:trackNumber"] = dbus.Int32(int(track["trackNo"]))
        if track.get("genre"):
            meta["xesam:genre"] = dbus.Array(
                [dbus.String(track["genre"])], signature="s")
        if track.get("year"):
            meta["xesam:contentCreated"] = dbus.String(f"{int(track['year'])}-01-01")

        art = self._state.get("artUrl")
        if art:
            meta["mpris:artUrl"] = dbus.String(art)
        return dbus.Dictionary(meta, signature="sv")

    def _root_props(self) -> dict[str, Any]:
        return {
            "CanQuit": dbus.Boolean(False),
            "CanRaise": dbus.Boolean(False),
            "HasTrackList": dbus.Boolean(False),
            "Identity": dbus.String("Stream Playing"),
            "DesktopEntry": dbus.String("org.kde.plasma.streamplay"),
            "SupportedUriSchemes": dbus.Array([], signature="s"),
            "SupportedMimeTypes": dbus.Array([], signature="s"),
        }

    def _player_props(self) -> dict[str, Any]:
        caps = self._state.get("capabilities") or {}
        has_track = self._state.get("track") is not None
        return {
            "PlaybackStatus": dbus.String(self._status),
            "LoopStatus": dbus.String(
                LOOP_TO_MPRIS.get(self._state.get("repeat", "none"), "None")),
            "Rate": dbus.Double(1.0),
            "MinimumRate": dbus.Double(1.0),
            "MaximumRate": dbus.Double(1.0),
            "Shuffle": dbus.Boolean(bool(self._state.get("shuffle"))),
            "Metadata": self._metadata(),
            "Volume": dbus.Double(float(self._state.get("volume") or 0.0)),
            "Position": dbus.Int64(self._position_us()),
            "CanGoNext": dbus.Boolean(bool(self._state.get("canNext"))),
            "CanGoPrevious": dbus.Boolean(bool(self._state.get("canPrevious"))),
            "CanPlay": dbus.Boolean(bool(self._state.get("queueLength"))),
            "CanPause": dbus.Boolean(has_track),
            "CanSeek": dbus.Boolean(has_track and bool(caps.get("seek", True))),
            "CanControl": dbus.Boolean(True),
        }

    def _props_for(self, interface: str) -> dict[str, Any]:
        if interface == ROOT_IFACE:
            return self._root_props()
        if interface == PLAYER_IFACE:
            return self._player_props()
        raise dbus.exceptions.DBusException(
            f"No such interface {interface}",
            name="org.freedesktop.DBus.Error.UnknownInterface")

    # ----------------------------------------------------------- properties

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        try:
            return self._props_for(str(interface))[str(prop)]
        except KeyError:
            raise dbus.exceptions.DBusException(
                f"No such property {prop}",
                name="org.freedesktop.DBus.Error.UnknownProperty") from None

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return dbus.Dictionary(self._props_for(str(interface)), signature="sv")

    @dbus.service.method(PROPS_IFACE, in_signature="ssv")
    def Set(self, interface, prop, value):
        if str(interface) != PLAYER_IFACE:
            return
        prop = str(prop)
        if prop == "Volume":
            self._dispatch(lambda: self._bridge.player_call("set_volume", float(value)))
        elif prop == "LoopStatus":
            mode = LOOP_FROM_MPRIS.get(str(value), "none")
            self._dispatch(lambda: self._bridge.player_call("set_repeat", mode))
        elif prop == "Shuffle":
            self._dispatch(lambda: self._bridge.player_call("set_shuffle", bool(value)))

    @dbus.service.signal(PROPS_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    # -------------------------------------------------------------- methods

    @dbus.service.method(ROOT_IFACE)
    def Raise(self):
        pass

    @dbus.service.method(ROOT_IFACE)
    def Quit(self):
        pass

    @dbus.service.method(PLAYER_IFACE)
    def Next(self):
        self._dispatch(lambda: self._bridge.player_call("next"))

    @dbus.service.method(PLAYER_IFACE)
    def Previous(self):
        self._dispatch(lambda: self._bridge.player_call("previous"))

    @dbus.service.method(PLAYER_IFACE)
    def Pause(self):
        self._dispatch(lambda: self._bridge.player_call("pause"))

    @dbus.service.method(PLAYER_IFACE)
    def PlayPause(self):
        self._dispatch(lambda: self._bridge.player_call("play_pause"))

    @dbus.service.method(PLAYER_IFACE)
    def Stop(self):
        self._dispatch(lambda: self._bridge.player_call("stop"))

    @dbus.service.method(PLAYER_IFACE)
    def Play(self):
        self._dispatch(lambda: self._bridge.player_call("play"))

    @dbus.service.method(PLAYER_IFACE, in_signature="x")
    def Seek(self, offset):
        self._dispatch(
            lambda: self._bridge.player_call("seek_relative", int(offset) / 1_000_000))

    @dbus.service.method(PLAYER_IFACE, in_signature="ox")
    def SetPosition(self, track_id, position):
        self._dispatch(
            lambda: self._bridge.player_call("seek", int(position) / 1_000_000))

    @dbus.service.method(PLAYER_IFACE, in_signature="s")
    def OpenUri(self, uri):
        pass

    @dbus.service.signal(PLAYER_IFACE, signature="x")
    def Seeked(self, position):
        pass

    # ---------------------------------------------------------------- input

    def apply_state(self, state: dict[str, Any]) -> None:
        """Replace the cached state and announce whatever actually changed."""
        previous = self._props_for(PLAYER_IFACE) if self._state else {}
        self._state = state
        self._state_at = time.monotonic()
        current = self._props_for(PLAYER_IFACE)

        changed = {
            key: value for key, value in current.items()
            # Position must never be announced; the spec uses Seeked for that.
            if key != "Position" and previous.get(key) != value
        }
        if changed:
            self.PropertiesChanged(PLAYER_IFACE,
                                   dbus.Dictionary(changed, signature="sv"), [])

    def emit_seeked(self, position: float) -> None:
        self.Seeked(dbus.Int64(int(position * 1_000_000)))


class MprisService:
    """Owns the GLib thread and marshals between it and the asyncio loop."""

    def __init__(self, hub) -> None:
        self._hub = hub
        self._loop: asyncio.AbstractEventLoop | None = None
        self._glib_loop: GLib.MainLoop | None = None
        self._thread: threading.Thread | None = None
        self._object: MprisObject | None = None
        self._ready = threading.Event()
        self._error: Exception | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._thread = threading.Thread(
            target=self._run, name="mpris", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)
        if self._error:
            raise self._error

    def _run(self) -> None:
        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SessionBus()
            # ReplaceExisting keeps a restarted daemon from ending up unnamed.
            name = dbus.service.BusName(
                BUS_NAME, bus, allow_replacement=True, replace_existing=True)
            self._object = MprisObject(name, self)
            self._glib_loop = GLib.MainLoop()
            log.info("MPRIS2 service registered as %s", BUS_NAME)
        except Exception as exc:
            self._error = exc
            log.error("cannot register MPRIS service: %s", exc)
            self._ready.set()
            return

        self._ready.set()
        try:
            self._glib_loop.run()
        except Exception:
            log.exception("MPRIS main loop failed")

    def stop(self) -> None:
        if self._glib_loop is not None:
            GLib.idle_add(self._glib_loop.quit)
        if self._thread is not None:
            self._thread.join(timeout=3)

    # ----------------------------------------------------- GLib -> asyncio

    def dispatch(self, coro_factory: Callable[[], Any]) -> None:
        """Run a coroutine on the asyncio loop from the GLib thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def schedule() -> None:
            asyncio.ensure_future(self._guard(coro_factory()))

        loop.call_soon_threadsafe(schedule)

    @staticmethod
    async def _guard(coro) -> None:
        try:
            await coro
        except Exception as exc:
            log.warning("MPRIS command failed: %s", exc)

    async def player_call(self, method: str, *args) -> None:
        player = self._hub.player
        if player is None:
            return
        await getattr(player, method)(*args)

    # ----------------------------------------------------- asyncio -> GLib

    def push_state(self, state: dict[str, Any]) -> None:
        if self._object is None:
            return
        GLib.idle_add(self._apply, dict(state))

    def _apply(self, state: dict[str, Any]) -> bool:
        if self._object is not None:
            try:
                self._object.apply_state(state)
            except Exception:
                log.exception("failed to publish MPRIS state")
        return False  # run once

    def push_seeked(self, position: float) -> None:
        if self._object is None:
            return
        GLib.idle_add(self._seeked, float(position))

    def _seeked(self, position: float) -> bool:
        if self._object is not None:
            try:
                self._object.emit_seeked(position)
            except Exception:
                log.exception("failed to emit Seeked")
        return False


def art_url(path: Path | None) -> str | None:
    return path.as_uri() if path else None
