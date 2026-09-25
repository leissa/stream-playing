"""Connection profiles and daemon settings.

The whole configuration lives in a single JSON file so it can be edited by hand
and copied between machines. It contains backend passwords, so the file is
created and re-chmod'ed to 0600 on every save.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CONFIG_DIR = Path(
    os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")
) / "streamplay"
CONFIG_FILE = CONFIG_DIR / "config.json"

CACHE_DIR = Path(
    os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
) / "streamplay"

DEFAULT_PORT = 8760

#: Fields that are secret and therefore never leave the daemon in clear text.
SECRET_FIELDS = ("password",)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.strip().lower()).strip("-")
    return slug or uuid.uuid4().hex[:8]


class Profile(dict):
    """One backend configuration.

    Common keys: ``id``, ``name``, ``type`` (``subsonic``/``kodi``/``mpd``).
    Subsonic: ``url``, ``username``, ``password``, ``legacyAuth``, ``verifyTls``.
    Kodi: ``host``, ``port``, ``username``, ``password``, ``wsPort``, ``useTls``.
    MPD: ``host``, ``port``, ``password``, ``musicDirectory``, ``socket``.
    ``socket`` is a path to MPD's unix socket, used instead of host/port; it is
    not in the settings dialog, but MPD tells a socket client where its music
    lives, so setting it by hand saves configuring ``musicDirectory`` too.
    """

    @property
    def id(self) -> str:
        return str(self.get("id", ""))

    @property
    def name(self) -> str:
        return str(self.get("name") or self.id)

    @property
    def type(self) -> str:
        return str(self.get("type", "subsonic"))

    def redacted(self) -> dict[str, Any]:
        """A copy safe to send to the applet.

        Secrets become the sentinel ``True``/``False`` under ``has<Field>`` so
        the UI can show "password set" without ever receiving it.
        """
        out = {k: v for k, v in self.items() if k not in SECRET_FIELDS}
        for f in SECRET_FIELDS:
            out["has" + f[0].upper() + f[1:]] = bool(self.get(f))
        return out


class Config:
    def __init__(self, path: Path = CONFIG_FILE) -> None:
        self.path = path
        self.profiles: dict[str, Profile] = {}
        self.active_id: str | None = None
        self.settings: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------ io

    def load(self) -> None:
        if not self.path.exists():
            self.settings = self._default_settings()
            return
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            log.error("cannot read %s: %s -- starting with empty config", self.path, exc)
            self.settings = self._default_settings()
            return

        self.profiles = {}
        for pid, data in (raw.get("profiles") or {}).items():
            prof = Profile(data)
            prof["id"] = pid
            self.profiles[pid] = prof

        self.active_id = raw.get("active") or None
        if self.active_id not in self.profiles:
            self.active_id = None

        self.settings = self._default_settings()
        self.settings.update(raw.get("settings") or {})

    @staticmethod
    def _default_settings() -> dict[str, Any]:
        return {
            "port": DEFAULT_PORT,
            "volume": 0.7,
            "repeat": "none",
            "shuffle": False,
            "autoConnect": True,
            # Subsonic streaming: 0 = let the server decide (usually raw).
            "maxBitrate": 0,
            "streamFormat": "raw",
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "active": self.active_id,
            "profiles": {pid: dict(p) for pid, p in self.profiles.items()},
            "settings": self.settings,
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)
        os.chmod(self.path, 0o600)

    # ------------------------------------------------------------- profiles

    def upsert(self, data: dict[str, Any]) -> Profile:
        """Create or update a profile and return the stored copy.

        A profile submitted without a password keeps the one already on disk,
        so the applet can save edits without ever holding the secret.
        """
        pid = str(data.get("id") or "").strip()
        if not pid:
            pid = slugify(str(data.get("name") or data.get("type") or "profile"))
            base, n = pid, 2
            while pid in self.profiles:
                pid, n = f"{base}-{n}", n + 1

        existing = self.profiles.get(pid, Profile())
        merged = Profile(existing)
        for key, value in data.items():
            if key in SECRET_FIELDS and value in (None, ""):
                continue  # keep the stored secret
            if key.startswith("has"):
                continue  # redaction artefact echoed back by the UI
            merged[key] = value
        merged["id"] = pid

        self.profiles[pid] = merged
        if self.active_id is None:
            self.active_id = pid
        self.save()
        return merged

    def delete(self, pid: str) -> bool:
        if pid not in self.profiles:
            return False
        del self.profiles[pid]
        if self.active_id == pid:
            self.active_id = next(iter(self.profiles), None)
        self.save()
        return True

    def set_active(self, pid: str | None) -> None:
        if pid is not None and pid not in self.profiles:
            raise KeyError(pid)
        self.active_id = pid
        self.save()

    @property
    def active(self) -> Profile | None:
        if self.active_id is None:
            return None
        return self.profiles.get(self.active_id)

    def set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self.save()

    def redacted_profiles(self) -> list[dict[str, Any]]:
        return [p.redacted() for p in self.profiles.values()]
