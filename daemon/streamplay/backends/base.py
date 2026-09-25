"""Interfaces for the two kinds of thing the daemon plugs together.

A *backend* is a music library you can browse and get a playable stream out of.
A *sink* is somewhere that stream can come out of -- this machine's speakers via
mpv, or a Kodi box across the room.

Keeping them apart is what lets several services be connected at once and share
a single queue: the queue holds tracks from any backend, and whichever sink is
selected plays them one after another.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..models import Album, Artist, Track

REPEAT_MODES = ("none", "all", "one")


class BackendError(RuntimeError):
    """Raised for anything the user should see as a connection/API failure."""


class SourceUnavailable(BackendError):
    """The service a track came from is not connected at the moment.

    Distinct from a playback failure: the track may be perfectly fine, so the
    player skips it instead of treating it as a broken file.
    """


@dataclass
class StreamTarget:
    """How to play one track.

    ``url`` is something any player can open. ``native`` is an optional
    backend-specific handle -- a Kodi song id, say -- that the matching sink can
    use instead to get better metadata than a bare URL would give.
    """

    url: str | None = None
    native: dict[str, Any] | None = None
    source: str = ""
    mime: str | None = None


class Backend(abc.ABC):
    """Read-only access to a music library."""

    #: ``subsonic`` / ``kodi``; also stamped onto every Track.
    kind: str = ""

    def __init__(self, profile: dict[str, Any]) -> None:
        self.profile = profile
        self.source = str(profile.get("id") or self.kind)
        self.name = profile.get("name") or profile.get("id") or self.kind

    @abc.abstractmethod
    async def connect(self) -> None:
        """Verify the configuration works. Raise BackendError otherwise."""

    async def close(self) -> None:
        return None

    # ------------------------------------------------------------- browsing

    @abc.abstractmethod
    async def artists(self) -> list[Artist]: ...

    @abc.abstractmethod
    async def artist_albums(self, artist_id: str) -> list[Album]: ...

    @abc.abstractmethod
    async def albums(self, sort: str = "alphabetical", offset: int = 0,
                     limit: int = 100) -> list[Album]: ...

    @abc.abstractmethod
    async def album_tracks(self, album_id: str) -> list[Track]: ...

    @abc.abstractmethod
    async def search(self, query: str, limit: int = 40) -> dict[str, list]: ...

    async def genres(self) -> list[str]:
        return []

    async def genre_albums(self, genre: str, offset: int = 0,
                           limit: int = 100) -> list[Album]:
        return []

    async def playlists(self) -> list[dict[str, Any]]:
        return []

    async def playlist_tracks(self, playlist_id: str) -> list[Track]:
        return []

    # ---------------------------------------------------------------- media

    @abc.abstractmethod
    async def stream_target(self, track: Track) -> StreamTarget:
        """Work out how the given track can actually be played."""

    def cover_request(self, cover_id: str, size: int) -> tuple[str, dict, dict] | None:
        """``(url, params, headers)`` to fetch cover art, or None if unsupported."""
        return None

    async def scrobble(self, track: Track, submission: bool) -> None:
        return None

    # -------------------------------------------------------------- helpers

    def tag(self, item):
        """Stamp an item with the profile it came from and hand it back."""
        item.source = self.source
        return item


@dataclass
class SinkState:
    """What a sink reports back about the one track it is playing."""

    status: str = "stopped"          # playing / paused / stopped
    position: float = 0.0
    duration: float = 0.0
    volume: float = 1.0
    buffering: bool = False
    error: str | None = None


class Sink(abc.ABC):
    """Somewhere audio comes out.

    The sink knows nothing about queues: it plays one target, reports progress,
    and tells the player when the track ended so the player can pick the next.
    """

    #: Identifier used on the wire, e.g. ``local`` or ``kodi:livingroom``.
    id: str = "sink"
    name: str = "Sink"
    #: False when the sink can only play media from its own service.
    accepts_any_url: bool = True

    def __init__(self) -> None:
        self.state = SinkState()
        self._on_ended: Callable[[str], Awaitable[None]] | None = None
        self._on_changed: Callable[[], None] | None = None

    def wire(self, on_ended: Callable[[str], Awaitable[None]],
             on_changed: Callable[[], None]) -> None:
        """``on_ended(reason)`` for eof/error, ``on_changed()`` for state."""
        self._on_ended = on_ended
        self._on_changed = on_changed

    async def _ended(self, reason: str) -> None:
        if self._on_ended is not None:
            await self._on_ended(reason)

    def _changed(self) -> None:
        if self._on_changed is not None:
            self._on_changed()

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    @abc.abstractmethod
    async def play(self, target: StreamTarget, track: Track) -> None: ...

    @abc.abstractmethod
    async def resume(self) -> None: ...

    @abc.abstractmethod
    async def pause(self) -> None: ...

    @abc.abstractmethod
    async def stop(self) -> None: ...

    @abc.abstractmethod
    async def seek(self, position: float) -> None: ...

    @abc.abstractmethod
    async def set_volume(self, volume: float) -> None: ...

    def capabilities(self) -> dict[str, bool]:
        return {"seek": True, "volume": True}
