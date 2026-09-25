"""Backend registry."""

from __future__ import annotations

from typing import Any

from .base import (Backend, BackendError, Sink, SinkState, SourceUnavailable,
                   StreamTarget)
from .kodi import KodiBackend, KodiSink
from .subsonic import SubsonicBackend

__all__ = [
    "Backend", "BackendError", "Sink", "SinkState", "SourceUnavailable",
    "StreamTarget",
    "KodiBackend", "KodiSink", "SubsonicBackend",
    "BACKEND_TYPES", "create_backend", "create_sink",
]

BACKEND_TYPES = {
    "subsonic": SubsonicBackend,
    "kodi": KodiBackend,
}


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
    return None
