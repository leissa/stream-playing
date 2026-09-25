"""Backend registry."""

from __future__ import annotations

from typing import Any

from .base import (Backend, BackendError, Sink, SinkState, SourceUnavailable,
                   StreamTarget)
from .kodi import KodiBackend, KodiSink
from .mpd import MpdBackend, MpdSink
from .subsonic import SubsonicBackend

__all__ = [
    "Backend", "BackendError", "Sink", "SinkState", "SourceUnavailable",
    "StreamTarget",
    "KodiBackend", "KodiSink", "MpdBackend", "MpdSink", "SubsonicBackend",
    "BACKEND_TYPES", "PLAYBACK_TYPES", "create_backend", "create_sink",
]

BACKEND_TYPES = {
    "subsonic": SubsonicBackend,
    "kodi": KodiBackend,
    "mpd": MpdBackend,
}

#: The services that are players as well as libraries, and so turn up in the
#: output list once connected. Kept next to the table above so the two cannot
#: drift apart.
PLAYBACK_TYPES = frozenset({"kodi", "mpd"})


def create_backend(profile: dict[str, Any]) -> Backend:
    kind = str(profile.get("type") or "subsonic")
    try:
        cls = BACKEND_TYPES[kind]
    except KeyError:
        raise BackendError(f"Unknown backend type {kind!r}") from None
    return cls(profile)


def create_sink(backend: Backend) -> Sink | None:
    """Some services can also play audio; expose those as an output."""
    if isinstance(backend, KodiBackend):
        return KodiSink(backend)
    if isinstance(backend, MpdBackend):
        return MpdSink(backend)
    return None
