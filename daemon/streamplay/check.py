"""Report missing runtime dependencies, one per line: ``python -m streamplay.check``."""

from __future__ import annotations

import importlib.util
import shutil
import sys

MODULES = {
    "requests": "python-requests",
    "websockets": "python-websockets",
    "secretstorage": "python-secretstorage",
    "dbus": "python-dbus",
    "gi": "python-gobject",
}


def missing() -> list[str]:
    out = [package for module, package in MODULES.items()
           if importlib.util.find_spec(module) is None]
    if shutil.which("mpv") is None:
        out.append("mpv")
    return out


def main() -> int:
    names = missing()
    for name in names:
        print(name)
    return 1 if names else 0


if __name__ == "__main__":
    sys.exit(main())
