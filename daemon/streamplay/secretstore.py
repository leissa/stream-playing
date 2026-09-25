"""Profile secrets in the freedesktop Secret Service (KWallet, GNOME Keyring, KeePassXC)."""

from __future__ import annotations

from contextlib import closing, contextmanager
from typing import Iterator

APPLICATION = "streamplay"


class SecretStoreError(RuntimeError):
    pass


@contextmanager
def _collection() -> Iterator:
    try:
        import secretstorage
    except ImportError:
        raise SecretStoreError("python-secretstorage is not installed") from None
    try:
        with closing(secretstorage.dbus_init()) as conn:
            collection = secretstorage.get_default_collection(conn)
            if collection.is_locked() and collection.unlock():
                raise SecretStoreError("unlocking the keyring was dismissed")
            yield collection
    except secretstorage.exceptions.SecretStorageException as exc:
        raise SecretStoreError(f"Secret Service: {exc}") from exc


def _attributes(profile_id: str, field: str | None = None) -> dict[str, str]:
    attrs = {"application": APPLICATION, "profile": profile_id}
    if field:
        attrs["field"] = field
    return attrs


def load_all() -> dict[tuple[str, str], str]:
    """Every stored secret, keyed by ``(profile id, field)``."""
    with _collection() as collection:
        out = {}
        for item in collection.search_items({"application": APPLICATION}):
            attrs = item.get_attributes()
            out[attrs.get("profile", ""), attrs.get("field", "")] = \
                item.get_secret().decode("utf-8")
        return out


def store(profile_id: str, field: str, value: str, label: str) -> None:
    with _collection() as collection:
        collection.create_item(label, _attributes(profile_id, field),
                               value.encode("utf-8"), replace=True)


def forget(profile_id: str) -> None:
    with _collection() as collection:
        for item in collection.search_items(_attributes(profile_id)):
            item.delete()
