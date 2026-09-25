"""On-disk cover art cache.

The applet and the MPRIS ``artUrl`` both need a URL they can load without
knowing any backend credentials, so the daemon fetches art once, stores it under
the XDG cache directory and hands out a local path or a localhost URL.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

import requests

from .config import CACHE_DIR

log = logging.getLogger(__name__)

COVER_DIR = CACHE_DIR / "covers"

#: Magic-byte sniffing, so the cached file gets a sensible extension.
_SIGNATURES = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF8", ".gif"),
    (b"RIFF", ".webp"),
)

MAX_BYTES = 8 * 1024 * 1024


def _extension(data: bytes) -> str:
    for signature, ext in _SIGNATURES:
        if data.startswith(signature):
            return ext
    return ".img"


class CoverCache:
    def __init__(self, directory: Path = COVER_DIR) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)
        self._inflight: dict[str, asyncio.Future] = {}

    def _key(self, profile_id: str, cover_id: str, size: int) -> str:
        raw = f"{profile_id}\0{cover_id}\0{size}".encode("utf-8")
        return hashlib.sha1(raw).hexdigest()

    def _lookup(self, key: str) -> Path | None:
        for candidate in self.dir.glob(key + ".*"):
            if candidate.stat().st_size > 0:
                return candidate
        return None

    async def fetch(self, backend, profile_id: str, cover_id: str,
                    size: int = 0) -> Path | None:
        """Return a local file holding the cover, downloading it if needed."""
        if not cover_id or backend is None:
            return None
        key = self._key(profile_id, cover_id, size)

        cached = self._lookup(key)
        if cached:
            return cached

        inflight = self._inflight.get(key)
        if inflight is not None:
            return await asyncio.shield(inflight)

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            path = await self._retrieve(backend, key, cover_id, size)
            if not future.done():
                future.set_result(path)
            return path
        except Exception as exc:
            log.debug("cover fetch failed for %s: %s", cover_id, exc)
            if not future.done():
                future.set_result(None)
            return None
        finally:
            self._inflight.pop(key, None)

    async def _retrieve(self, backend, key: str, cover_id: str,
                        size: int) -> Path | None:
        """Get the art however this backend is able to hand it over.

        Most services answer with an HTTP URL, which is fetched in a thread
        because ``requests`` blocks. MPD instead sends the bytes down its own
        control connection, so that path is asked first and stays on the event
        loop.
        """
        data = await backend.cover_bytes(cover_id, size)
        if data:
            return self._store(key, data)
        return await asyncio.to_thread(
            self._download, backend, key, cover_id, size)

    def _store(self, key: str, data: bytes) -> Path:
        path = self.dir / (key + _extension(data))
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path

    def _download(self, backend, key: str, cover_id: str, size: int) -> Path | None:
        request = backend.cover_request(cover_id, size)
        if request is None:
            return None
        url, params, headers = request

        session = getattr(backend, "http_session", None) or requests
        resp = session.get(
            url, params=params or None, headers=headers or None,
            timeout=(5, 20), stream=True,
            verify=getattr(backend, "verify_tls", True),
        )
        resp.raise_for_status()

        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_content(64 * 1024):
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_BYTES:
                raise ValueError("cover art too large")
        data = b"".join(chunks)
        if not data:
            return None
        return self._store(key, data)

    def clear(self) -> None:
        for entry in self.dir.glob("*"):
            try:
                entry.unlink()
            except OSError:
                pass
