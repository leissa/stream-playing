"""Plain data objects shared by backends, players and the wire protocol.

Everything that crosses the WebSocket is built from these, so the applet only
ever has to understand one shape of track/album/artist regardless of whether it
came from Subsonic or Kodi.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class Track:
    id: str
    title: str
    artist: str = ""
    album: str = ""
    duration: float = 0.0
    backend: str = ""
    #: Profile id of the service this came from; ids are only unique within one.
    source: str = ""
    artist_id: str | None = None
    album_id: str | None = None
    track_no: int | None = None
    disc_no: int | None = None
    year: int | None = None
    genre: str | None = None
    cover_id: str | None = None
    # Opaque per-backend payload (stream URL hints, Kodi file path, ...).
    extra: dict[str, Any] = field(default_factory=dict)
    # Assigned by the queue; stable for the lifetime of the entry so the UI and
    # MPRIS can identify a specific queue slot even after reordering.
    uid: str = ""

    def to_json(self) -> dict[str, Any]:
        return _clean(
            {
                "id": self.id,
                "uid": self.uid,
                "title": self.title,
                "artist": self.artist,
                "album": self.album,
                "duration": self.duration,
                "backend": self.backend,
                "source": self.source,
                "artistId": self.artist_id,
                "albumId": self.album_id,
                "trackNo": self.track_no,
                "discNo": self.disc_no,
                "year": self.year,
                "genre": self.genre,
                "coverId": self.cover_id,
            }
        )

    def copy(self) -> "Track":
        return dataclasses.replace(self, extra=dict(self.extra))


@dataclass
class Album:
    id: str
    name: str
    artist: str = ""
    source: str = ""
    artist_id: str | None = None
    year: int | None = None
    track_count: int = 0
    duration: float = 0.0
    genre: str | None = None
    cover_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _clean(
            {
                "id": self.id,
                "name": self.name,
                "artist": self.artist,
                "source": self.source,
                "artistId": self.artist_id,
                "year": self.year,
                "trackCount": self.track_count,
                "duration": self.duration,
                "genre": self.genre,
                "coverId": self.cover_id,
            }
        )


@dataclass
class Artist:
    id: str
    name: str
    source: str = ""
    album_count: int = 0
    cover_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return _clean(
            {
                "id": self.id,
                "name": self.name,
                "source": self.source,
                "albumCount": self.album_count,
                "coverId": self.cover_id,
            }
        )
