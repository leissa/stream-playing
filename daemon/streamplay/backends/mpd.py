"""MPD over its own text protocol.

Like Kodi, MPD turns up twice: :class:`MpdBackend` is a library you browse and
:class:`MpdSink` is somewhere audio comes out. The two are independent, so an
MPD library can play on this computer's speakers and a Navidrome album can be
handed to MPD -- the daemon owns the queue either way.

Two things about MPD shape the code below. It has **no ids**: a tag value *is*
the identifier, so an album is addressed by its artist and title and a track by
its path inside the music directory. And it does not serve audio over its
control port, so playing an MPD track anywhere other than on MPD itself needs
the files to be reachable as ordinary paths -- see :meth:`MpdBackend._local`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..models import Album, Artist, Track
from .base import Backend, BackendError, Sink, StreamTarget

log = logging.getLogger(__name__)

#: Joins an album's artist and title into one id. MPD has nothing better to
#: offer, and a control character is the one thing that cannot occur in a tag.
ID_SEP = "\x1f"

CONNECT_TIMEOUT = 8.0
COMMAND_TIMEOUT = 30.0

#: How close to the end of a track a stop has to happen to count as the track
#: ending rather than somebody pressing stop in another client. The position is
#: carried forward from the last reading, so this only has to cover clock drift
#: and not the gap between two polls.
EOF_SLACK = 1.0


def _quote(value: str) -> str:
    """Wrap one protocol argument in quotes, escaping what needs it."""
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _term(value: str) -> str:
    """A filter value, single-quoted the way MPD's filter grammar wants."""
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _filter(*clauses: str) -> str:
    """Combine ``(tag == 'x')`` clauses into one filter expression."""
    kept = [c for c in clauses if c]
    if not kept:
        return "(base '')"      # matches the whole library
    if len(kept) == 1:
        return kept[0]
    return "(" + " AND ".join(kept) + ")"


def _eq(tag: str, value: str) -> str:
    return f"({tag} == {_term(value)})"


def _contains(tag: str, value: str) -> str:
    return f"({tag} contains {_term(value)})"


def _int(value: str | None) -> int | None:
    """``"3"`` and ``"3/12"`` both mean three; anything else means nothing."""
    if not value:
        return None
    head = str(value).split("/")[0].strip()
    try:
        return int(head)
    except ValueError:
        return None


def _year(value: str | None) -> int | None:
    """MPD dates run from a bare year to a full ISO timestamp."""
    if not value:
        return None
    return _int(str(value)[:4])


class MpdCommandError(BackendError):
    """MPD answered with ACK. The connection is still usable."""


class MpdConnection:
    """One connection speaking the MPD text protocol.

    MPD replies are ``key: value`` lines closed by ``OK`` or ``ACK``, and the
    order of those lines carries meaning -- a song is one run of them -- so the
    reply is kept as a list of pairs rather than collapsed into a dict.

    Commands are serialised by a lock: MPD has no request ids, so two callers
    writing at once would read each other's answers.
    """

    def __init__(self, host: str, port: int, password: str = "",
                 unix_socket: str = "", label: str = "MPD") -> None:
        self.host = host
        self.port = port
        self.password = password
        self.unix_socket = unix_socket
        self.label = label
        self.version = ""
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    # ------------------------------------------------------------ lifecycle

    async def _open(self) -> None:
        try:
            if self.unix_socket:
                opening = asyncio.open_unix_connection(self.unix_socket)
            else:
                opening = asyncio.open_connection(self.host, self.port)
            reader, writer = await asyncio.wait_for(opening, CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            raise BackendError(f"{self.label}: timed out connecting") from None
        except OSError as exc:
            raise BackendError(f"{self.label}: {exc.strerror or exc}") from exc

        try:
            banner = await asyncio.wait_for(reader.readline(), CONNECT_TIMEOUT)
        except asyncio.TimeoutError:
            writer.close()
            raise BackendError(f"{self.label}: no greeting") from None

        text = banner.decode("utf-8", "replace").strip()
        if not text.startswith("OK MPD "):
            writer.close()
            raise BackendError(f"{self.label}: not an MPD server")
        self.version = text[len("OK MPD "):]
        self._reader, self._writer = reader, writer

        if self.password:
            try:
                await self._exchange("password", self.password)
            except MpdCommandError:
                await self.close()
                raise BackendError(f"{self.label}: the password was rejected") from None

    async def close(self) -> None:
        writer, self._writer, self._reader = self._writer, None, None
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.CancelledError):
            pass

    # -------------------------------------------------------------- talking

    async def command(self, *args: Any) -> list[tuple[str, str]]:
        """Run one command, reconnecting once if the socket has gone."""
        async with self._lock:
            if not self.connected:
                await self._open()
            try:
                return await self._exchange(*args)
            except MpdCommandError:
                raise
            except BackendError:
                # A dropped socket looks exactly like this. Try once more on a
                # fresh connection before telling the user anything is wrong.
                await self.close()
                await self._open()
                return await self._exchange(*args)

    async def binary(self, name: str, uri: str) -> bytes | None:
        """Read a chunked binary reply (``albumart`` / ``readpicture``).

        MPD only hands over ``binarylimit`` bytes at a time, so the command is
        repeated at increasing offsets until the announced size is complete.
        """
        async with self._lock:
            if not self.connected:
                await self._open()
            chunks: list[bytes] = []
            total = 0
            while True:
                pairs, blob = await self._exchange_binary(name, uri, len(b"".join(chunks)))
                if blob is None:
                    return None
                chunks.append(blob)
                for key, value in pairs:
                    if key == "size":
                        total = _int(value) or 0
                got = sum(len(c) for c in chunks)
                if not blob or total == 0 or got >= total:
                    break
            data = b"".join(chunks)
            return data or None

    async def _exchange(self, *args: Any) -> list[tuple[str, str]]:
        pairs, _ = await self._exchange_binary(*args)
        return pairs

    async def _exchange_binary(
            self, *args: Any) -> tuple[list[tuple[str, str]], bytes | None]:
        assert self._reader is not None and self._writer is not None
        line = " ".join([str(args[0])] + [_quote(a) for a in args[1:]])
        try:
            self._writer.write((line + "\n").encode("utf-8"))
            await self._writer.drain()
            return await asyncio.wait_for(self._read_reply(), COMMAND_TIMEOUT)
        except asyncio.TimeoutError:
            await self.close()
            raise BackendError(f"{self.label}: {args[0]} timed out") from None
        except (OSError, ConnectionError) as exc:
            await self.close()
            raise BackendError(f"{self.label}: {exc}") from exc

    async def _read_reply(self) -> tuple[list[tuple[str, str]], bytes | None]:
        assert self._reader is not None
        pairs: list[tuple[str, str]] = []
        blob: bytes | None = None
        while True:
            raw = await self._reader.readline()
            if not raw:
                raise ConnectionError("the server closed the connection")
            text = raw.decode("utf-8", "replace").rstrip("\n")

            if text == "OK":
                return pairs, blob
            if text.startswith("ACK "):
                raise MpdCommandError(f"{self.label}: {self._ack_message(text)}")
            if text.startswith("binary: "):
                size = _int(text[len("binary: "):]) or 0
                blob = await self._reader.readexactly(size)
                await self._reader.readexactly(1)   # the newline after the blob
                continue

            key, _, value = text.partition(": ")
            pairs.append((key, value))

    @staticmethod
    def _ack_message(text: str) -> str:
        """Pull the human half out of ``ACK [50@0] {find} No such directory``."""
        _, _, tail = text.partition("} ")
        return tail or text[len("ACK "):]


def _runs(pairs: Sequence[tuple[str, str]], start: str) -> Iterable[dict[str, str]]:
    """Split a flat reply into one dict per item.

    A new item begins at every ``start`` key -- ``file`` for songs, ``playlist``
    for stored playlists -- because that is the only structure MPD gives.
    """
    current: dict[str, str] | None = None
    for key, value in pairs:
        if key == start:
            if current is not None:
                yield current
            current = {key: value}
        elif current is not None and key not in current:
            current[key] = value
    if current is not None:
        yield current


def _grouped(pairs: Sequence[tuple[str, str]],
             wanted: str) -> Iterable[tuple[str, dict[str, str]]]:
    """Walk a ``list <tag> group <tag>…`` reply.

    MPD prints each group's value just before the run it applies to, so the
    most recently seen value of every other key is the group this item is in.
    """
    groups: dict[str, str] = {}
    for key, value in pairs:
        if key.lower() == wanted.lower():
            yield value, dict(groups)
        else:
            groups[key.lower()] = value


class MpdBackend(Backend):
    kind = "mpd"

    def __init__(self, profile: dict[str, Any]) -> None:
        super().__init__(profile)
        self.unix_socket = str(profile.get("socket") or "").strip()
        self.host = str(profile.get("host") or "127.0.0.1").strip()
        self.port = int(profile.get("port") or 6600)
        self.password = str(profile.get("password") or "")
        #: Where MPD's files live as far as *this* machine is concerned. Only
        #: needed to play MPD tracks somewhere other than on MPD itself.
        self.music_directory = str(profile.get("musicDirectory") or "").strip()

        self.client = MpdConnection(self.host, self.port, self.password,
                                    self.unix_socket, self.name)

    async def call(self, *args: Any) -> list[tuple[str, str]]:
        return await self.client.command(*args)

    # ------------------------------------------------------------ lifecycle

    async def connect(self) -> None:
        await self.call("ping")
        if not self.music_directory:
            await self._discover_music_directory()

    async def _discover_music_directory(self) -> None:
        """Ask MPD where its files are, which only local clients may do.

        Over a unix socket this saves the user from configuring the path twice;
        over TCP it is refused and the profile has to say, so the failure is
        expected and not worth reporting.
        """
        try:
            pairs = await self.call("config")
        except BackendError as exc:
            log.debug("%s: no music directory from config: %s", self.name, exc)
            return
        for key, value in pairs:
            if key == "music_directory" and value:
                self.music_directory = value
                log.info("%s: music directory is %s", self.name, value)

    async def close(self) -> None:
        await self.client.close()

    # -------------------------------------------------------------- mapping

    def _track(self, song: dict[str, str]) -> Track:
        uri = song.get("file", "")
        return Track(
            # The path is the only stable handle MPD has, so it doubles as the
            # id -- which means a track survives the round trip through the
            # applet without any per-backend rehydration.
            id=uri,
            title=song.get("Title") or Path(uri).stem or "Unknown",
            artist=song.get("Artist") or song.get("AlbumArtist") or "",
            album=song.get("Album") or "",
            duration=float(song.get("duration") or song.get("Time") or 0),
            backend=self.kind,
            source=self.source,
            artist_id=song.get("AlbumArtist") or song.get("Artist") or None,
            album_id=self._album_id(song.get("AlbumArtist") or song.get("Artist") or "",
                                   song.get("Album") or "") or None,
            track_no=_int(song.get("Track")),
            disc_no=_int(song.get("Disc")),
            year=_year(song.get("Date") or song.get("OriginalDate")),
            genre=song.get("Genre") or None,
            cover_id=uri or None,
            extra={"uri": uri},
        )

    @staticmethod
    def _album_id(artist: str, album: str) -> str:
        return f"{artist}{ID_SEP}{album}" if album else ""

    @staticmethod
    def _split_album_id(album_id: str) -> tuple[str, str]:
        artist, _, album = str(album_id).partition(ID_SEP)
        return artist, album

    def _album(self, name: str, groups: dict[str, str]) -> Album:
        artist = groups.get("albumartist") or groups.get("artist") or ""
        return Album(
            id=self._album_id(artist, name),
            name=name or "Unknown",
            artist=artist,
            source=self.source,
            artist_id=artist or None,
            year=_year(groups.get("date")),
            genre=groups.get("genre") or None,
        )

    # -------------------------------------------------------------- browsing

    async def _album_list(self, *clauses: str) -> list[Album]:
        """Every album matching the clauses, with its artist and year.

        One command does the whole job. Track counts are left at zero on
        purpose: ``count`` accepts a single ``group``, so there is no way to
        ask for them per artist *and* album, and a count keyed on the title
        alone would silently add up two different records with the same name.

        Grouping by date is what gets a year at all, and it is also why the
        results have to be folded together afterwards: one album whose tracks
        carry ``1998`` and ``1998-04-02`` is two groups to MPD, and would
        otherwise be listed twice.
        """
        pairs = await self.call(
            "list", "album", _filter(*clauses), "group", "albumartist",
            "group", "date")

        seen: dict[tuple[str, str], Album] = {}
        for name, groups in _grouped(pairs, "Album"):
            if not name:
                continue
            album = self._album(name, groups)
            key = (album.artist.casefold(), album.name.casefold())
            first = seen.get(key)
            if first is None:
                seen[key] = self.tag(album)
            elif album.year is not None:
                # Tracks disagreeing about the date usually means a reissue
                # tag on some of them, so the earliest is the release.
                first.year = (album.year if first.year is None
                              else min(first.year, album.year))
        return list(seen.values())

    async def artists(self) -> list[Artist]:
        # Asking for the albums rather than for ``list albumartist`` gets the
        # album count in the same breath, for no extra round trip.
        pairs = await self.call("list", "album", "group", "albumartist")
        counts: dict[str, int] = {}
        for _, groups in _grouped(pairs, "Album"):
            name = groups.get("albumartist") or ""
            counts[name] = counts.get(name, 0) + 1
        return [self.tag(Artist(id=name, name=name or "Unknown",
                                source=self.source, album_count=count))
                for name, count in counts.items() if name]

    async def artist_albums(self, artist_id: str) -> list[Album]:
        return await self._album_list(_eq("AlbumArtist", artist_id))

    async def albums(self, sort: str = "alphabetical", offset: int = 0,
                     limit: int = 100) -> list[Album]:
        # MPD cannot sort or page a ``list``, so the whole set comes back and
        # the caller's shared sort decides the order. The library lives in
        # MPD's memory, so this stays cheap.
        albums = await self._album_list()
        albums.sort(key=lambda a: (a.artist.lower(), a.year or 0, a.name.lower()))
        return albums[offset:offset + limit] if limit else albums[offset:]

    async def album_tracks(self, album_id: str) -> list[Track]:
        artist, album = self._split_album_id(album_id)
        clauses = [_eq("Album", album)]
        if artist:
            clauses.append(_eq("AlbumArtist", artist))
        pairs = await self.call("find", _filter(*clauses))
        tracks = [self.tag(self._track(s)) for s in _runs(pairs, "file")]
        tracks.sort(key=lambda t: (t.disc_no or 0, t.track_no or 0, t.title.lower()))
        return tracks

    async def search(self, query: str, limit: int = 40) -> dict[str, list]:
        """Find artists, albums and tracks whose names contain the query.

        Artists and albums are filtered here rather than by MPD. Its ``list``
        command matches case-sensitively, which is no use to somebody typing
        into a search box, and the full artist and album lists are one cheap
        command each -- MPD keeps the database in memory.
        """
        needle = query.casefold()
        artists, albums, songs = await asyncio.gather(
            self.artists(),
            self._album_list(),
            # ``search``, unlike ``list`` and ``find``, ignores case, so the
            # track arm can be left to MPD and windowed to a sane size.
            self.call("search", _contains("Title", query),
                      "window", f"0:{max(1, limit)}"),
            return_exceptions=True,
        )

        def ok(result: Any) -> list:
            """One arm failing should not empty the other two."""
            if isinstance(result, Exception):
                log.debug("%s search: %s", self.name, result)
                return []
            return result

        return {
            "artists": [a for a in ok(artists)
                        if needle in a.name.casefold()][:limit],
            "albums": [a for a in ok(albums)
                       if needle in a.name.casefold()
                       or needle in a.artist.casefold()][:limit],
            "tracks": [self.tag(self._track(s))
                       for s in _runs(ok(songs), "file")],
        }

    async def genres(self) -> list[str]:
        pairs = await self.call("list", "genre")
        return sorted({value for key, value in pairs
                       if key == "Genre" and value})

    async def genre_albums(self, genre: str, offset: int = 0,
                           limit: int = 100) -> list[Album]:
        albums = await self._album_list(_eq("Genre", genre))
        for album in albums:
            # Grouping by genre as well would split an album whose tracks are
            # tagged differently, so it is stamped on from the filter instead.
            album.genre = genre
        return albums[offset:offset + limit] if limit else albums[offset:]

    async def playlists(self) -> list[dict[str, Any]]:
        pairs = await self.call("listplaylists")
        return [{"id": entry["playlist"], "name": entry["playlist"]}
                for entry in _runs(pairs, "playlist") if entry.get("playlist")]

    async def playlist_tracks(self, playlist_id: str) -> list[Track]:
        pairs = await self.call("listplaylistinfo", playlist_id)
        return [self.tag(self._track(s)) for s in _runs(pairs, "file")]

    # ----------------------------------------------------------------- media

    def _local(self, uri: str) -> str | None:
        """The track as a URL any player can open, if there is one.

        MPD serves no audio over its control port, so this only works when the
        files are also reachable from this machine -- the usual case for an MPD
        running on the same box, and for a remote one whose library is mounted.
        """
        if uri.startswith(("http://", "https://")):
            return uri            # a radio stream sitting in MPD's database
        if not self.music_directory:
            return None
        path = Path(self.music_directory) / uri
        try:
            return path.as_uri() if path.is_file() else None
        except (OSError, ValueError):
            return None

    async def stream_target(self, track: Track) -> StreamTarget:
        uri = track.extra.get("uri") or track.id
        if not uri:
            raise BackendError(f"{self.name}: {track.title} has no path")
        url = self._local(uri)
        if url is None and not self.music_directory:
            log.debug("%s: %s can only play on MPD itself "
                      "(no music directory configured)", self.name, uri)
        return StreamTarget(url=url, native={"uri": uri}, source=self.source)

    async def cover_bytes(self, cover_id: str, size: int) -> bytes | None:
        """Cover art comes down the control connection, not over HTTP.

        ``albumart`` is the folder image and ``readpicture`` the one embedded
        in the file; different libraries have one or the other, so both are
        tried. MPD ignores ``size`` -- it hands over whatever it has.
        """
        if not cover_id:
            return None
        for command in ("albumart", "readpicture"):
            try:
                data = await self.client.binary(command, cover_id)
            except BackendError as exc:
                log.debug("%s %s: %s", self.name, command, exc)
                continue
            if data:
                return data
        return None


class MpdSink(Sink):
    """Plays one track at a time on an MPD instance.

    MPD has a perfectly good queue of its own, and it is deliberately not used:
    the daemon's queue is the single source of truth, so MPD is handed one song
    and told to stop at the end of it.
    """

    POLL_INTERVAL = 1.0

    def __init__(self, backend: MpdBackend) -> None:
        super().__init__()
        self.backend = backend
        self.source = backend.source
        self.id = f"mpd:{backend.source}"
        self.name = backend.name
        #: A second connection, because ``idle`` blocks until something happens
        #: and would hold up every command issued in the meantime.
        self.watcher = MpdConnection(
            backend.host, backend.port, backend.password,
            backend.unix_socket, backend.name)
        #: Set while a play/stop is halfway through. MPD passes through
        #: ``stop`` on the way to the next song, and that momentary stop must
        #: not be mistaken for the track having ended.
        self._changing = False
        self._has_mixer = True
        #: When :attr:`state.position` was last read, so it can be carried
        #: forward -- see :meth:`_near_end`.
        self._position_at = 0.0
        self._idle_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None

    async def start(self) -> None:
        # Whatever the user left MPD set to, our queue does the deciding.
        await self.backend.call("repeat", "0")
        await self.backend.call("random", "0")
        await self.backend.call("consume", "0")
        await self.backend.call("single", "1")
        await self._sync()
        self._idle_task = asyncio.create_task(
            self._idle_loop(), name=f"mpd-idle-{self.backend.source}")
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name=f"mpd-poll-{self.backend.source}")

    async def close(self) -> None:
        for task in (self._idle_task, self._poll_task):
            if task:
                task.cancel()
        self._idle_task = self._poll_task = None
        await self.watcher.close()

    # ------------------------------------------------------------ live feed

    async def _idle_loop(self) -> None:
        """Follow MPD's own change notifications.

        ``idle`` answers the moment the player, the mixer or the options
        change, which is what makes another client's play/pause show up here
        straight away instead of at the next poll.
        """
        backoff = 1.0
        while True:
            try:
                await self.watcher.command("idle", "player", "mixer", "options")
                backoff = 1.0
                await self._sync()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("%s idle: %s", self.name, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _poll_loop(self) -> None:
        """Keep the progress bar moving; ``idle`` says nothing about elapsed."""
        while True:
            try:
                await asyncio.sleep(self.POLL_INTERVAL)
                if self.state.status == "playing":
                    await self._sync()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("%s poll: %s", self.name, exc)

    async def _sync(self) -> None:
        try:
            status = dict(await self.backend.call("status"))
        except BackendError as exc:
            self.state.error = str(exc)
            self._changed()
            return
        if self._changing:
            return

        # Both loops can be in here at once. Reading the old state only after
        # the round trip -- and the connection serialises those -- means the
        # second one sees what the first concluded, so an ended track is
        # reported once rather than twice.
        was, near_end = self.state.status, self._near_end()
        state = status.get("state", "stop")
        self.state.status = {"play": "playing", "pause": "paused"}.get(
            state, "stopped")
        self._note_position(float(status.get("elapsed") or 0.0))
        self.state.duration = float(status.get("duration") or self.state.duration)
        self.state.error = status.get("error") or None

        # MPD reports no volume at all, or -1, when its output has no mixer --
        # a null or pipe output, or ALSA without a control. Then the level is
        # not ours to set and pretending otherwise would be a lie.
        volume = _int(status.get("volume"))
        self._has_mixer = volume is not None and volume >= 0
        if self._has_mixer:
            self.state.volume = max(0.0, min(1.0, (volume or 0) / 100.0))

        if self.state.status == "stopped" and was == "playing":
            self._note_position(0.0)
            if self.state.error:
                # MPD could not fetch or decode it. Reported separately from
                # eof so the player steps over the track and says why, rather
                # than counting it as one that played.
                await self._ended("error")
                return
            if near_end:
                await self._ended("eof")
                return
            # Otherwise somebody stopped MPD from another client. Respect it
            # rather than treating it as the track finishing and rolling on.
        self._changed()

    def _note_position(self, position: float) -> None:
        """Record where playback is, and when we learned it."""
        self.state.position = position
        self._position_at = time.monotonic()

    def _near_end(self) -> bool:
        """Was the track about to finish when it stopped?

        MPD reports a plain ``state: stop`` whether the song ran out or
        somebody pressed stop, and unlike Kodi it does not say which, so the
        position is the only evidence there is. The last reading may be up to
        a poll old and a short track can start and end inside that gap, so it
        is carried forward by however long ago it was taken.
        """
        if self.state.duration <= 0:
            return True
        position = self.state.position
        if self.state.status == "playing":
            position += max(0.0, time.monotonic() - self._position_at)
        # Never let the slack swallow the whole track: on something shorter
        # than a couple of seconds that would make every stop look like an end.
        slack = min(EOF_SLACK, self.state.duration / 2)
        return position >= self.state.duration - slack

    # ------------------------------------------------------------- playback

    def _uri_for(self, target: StreamTarget, track: Track) -> str:
        if target.native and target.source == self.backend.source:
            uri = str(target.native.get("uri") or "")
            if uri:
                return uri
        if target.url and target.url.startswith(("http://", "https://")):
            return target.url
        if target.url:
            raise BackendError(
                f"{self.name} can only play its own library and web streams")
        raise BackendError(f"{self.name} cannot play {track.title}")

    async def play(self, target: StreamTarget, track: Track) -> None:
        uri = self._uri_for(target, track)

        # Replacing the queue takes MPD through stop; hold off the watchers
        # until it is playing again.
        self._changing = True
        try:
            # MPD keeps the last playback error until it is told to forget it,
            # and a stale one would make the next track look broken too.
            await self.backend.call("clearerror")
            await self.backend.call("clear")
            await self.backend.call("single", "1")
            await self.backend.call("add", uri)
            await self.backend.call("play")
        finally:
            self._changing = False
        self.state.status = "playing"
        self._note_position(0.0)
        self.state.duration = track.duration
        self.state.error = None
        self._changed()
        await self._sync()

    async def resume(self) -> None:
        await self.backend.call("pause", "0")
        await self._sync()

    async def pause(self) -> None:
        if self.state.status == "stopped":
            return
        await self.backend.call("pause", "1")
        await self._sync()

    async def stop(self) -> None:
        self._changing = True
        try:
            await self.backend.call("stop")
        except BackendError as exc:
            log.debug("%s stop: %s", self.name, exc)
        finally:
            self._changing = False
        self.state.status = "stopped"
        self._note_position(0.0)
        self._changed()

    async def seek(self, position: float) -> None:
        try:
            await self.backend.call("seekcur", f"{max(0.0, position):.3f}")
        except BackendError as exc:
            log.debug("%s seek: %s", self.name, exc)
            return
        self._note_position(max(0.0, position))
        self._changed()

    async def set_volume(self, volume: float) -> None:
        volume = max(0.0, min(1.0, float(volume)))
        if not self._has_mixer:
            # No mixer on MPD's output: remember the wish, but do not pretend
            # it did anything.
            self.state.volume = volume
            self._changed()
            return
        try:
            await self.backend.call("setvol", str(int(round(volume * 100))))
        except BackendError as exc:
            log.debug("%s setvol: %s", self.name, exc)
            return
        self.state.volume = volume
        self._changed()

    def capabilities(self) -> dict[str, bool]:
        return {"seek": True, "volume": self._has_mixer}
