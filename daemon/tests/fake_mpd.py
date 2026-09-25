"""A stub MPD server, good enough to answer what the backend actually asks.

It speaks the protocol over a loopback socket and pretends to play by watching
the clock, which keeps ``test_mpd.py`` self-contained.
"""

from __future__ import annotations

import asyncio
import time

#: (uri, tags) -- the tags are spelled exactly as MPD spells them.
LIBRARY: list[tuple[str, dict[str, str]]] = [
    ("Alba Nova/First Light/1 - Dawn.flac", {
        "Artist": "Alba Nova", "AlbumArtist": "Alba Nova",
        "Album": "First Light", "Title": "Dawn", "Track": "1",
        "Date": "1998-04-02", "Genre": "Ambient", "duration": "0.8"}),
    ("Alba Nova/First Light/3 - Dusk.flac", {
        "Artist": "Alba Nova", "AlbumArtist": "Alba Nova",
        "Album": "First Light", "Title": "Dusk", "Track": "3/3",
        "Date": "1998", "Genre": "Ambient", "duration": "0.8"}),
    ("Alba Nova/First Light/2 - Meridian.flac", {
        "Artist": "Alba Nova", "AlbumArtist": "Alba Nova",
        "Album": "First Light", "Title": "Meridian", "Track": "2",
        "Date": "1998", "Genre": "Ambient", "duration": "0.8"}),
    ("Alba Nova/Second Wind/1 - Gust.flac", {
        "Artist": "Alba Nova", "AlbumArtist": "Alba Nova",
        "Album": "Second Wind", "Title": "Gust", "Track": "1",
        "Date": "2011", "Genre": "Ambient", "duration": "0.8"}),
    ("Cobalt Choir/Deep Blue/1 - Azure.flac", {
        "Artist": "Cobalt Choir", "AlbumArtist": "Cobalt Choir",
        "Album": "Deep Blue", "Title": "Azure", "Track": "1",
        "Date": "2019", "Genre": "Electronic", "duration": "0.8"}),
    # An album name carrying both characters a filter has to escape.
    ("Odd/Rock'n'Roll \\ Forever/1 - Slash.flac", {
        "Artist": "The Odds", "AlbumArtist": "The Odds",
        "Album": "Rock'n'Roll \\ Forever", "Title": "Slash", "Track": "1",
        "Date": "1977", "Genre": "Rock", "duration": "0.8"}),
]

PLAYLISTS = {"Blue Mood": ["Cobalt Choir/Deep Blue/1 - Azure.flac"]}

#: Longer than the chunk size below, so the backend has to ask for the rest.
ART = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 5
ART_OWNER = "Alba Nova/First Light/1 - Dawn.flac"
EMBEDDED = b"\xff\xd8\xff" + b"jpeg" * 20
EMBEDDED_OWNER = "Cobalt Choir/Deep Blue/1 - Azure.flac"
CHUNK = 300


class Ack(Exception):
    """An error the server reports without dropping the connection."""

    def __init__(self, message: str, code: int = 5) -> None:
        super().__init__(message)
        self.code = code


def split_args(line: str) -> list[str]:
    """Undo the quoting the client applied, the way MPD does."""
    out: list[str] = []
    token: list[str] = []
    quoted = False
    escape = False
    started = False
    for char in line:
        if escape:
            token.append(char)
            escape = False
        elif char == "\\":
            escape = True
        elif char == '"':
            quoted = not quoted
            started = True
        elif char.isspace() and not quoted:
            if token or started:
                out.append("".join(token))
            token, started = [], False
        else:
            token.append(char)
    if token or started:
        out.append("".join(token))
    return out


def parse_filter(text: str, fold: bool = False):
    """Understand the subset of MPD's filter grammar the backend emits.

    Anything else is an error here, so a new spelling shows up as a failure.
    ``fold`` is the only difference between MPD's ``find`` and its ``search``.
    """
    text = text.strip()
    if not (text.startswith("(") and text.endswith(")")):
        raise Ack(f"Unknown filter type: {text}", code=2)
    inner = text[1:-1].strip()

    if " AND " in inner and inner.startswith("("):
        parts, depth, start = [], 0, 0
        for i, char in enumerate(inner):
            depth += (char == "(") - (char == ")")
            if depth == 0 and inner[i:i + 5] == ") AND":
                parts.append(inner[start:i + 1])
                start = i + 6
        parts.append(inner[start:])
        clauses = [parse_filter(p.strip(), fold) for p in parts]
        return lambda song: all(c(song) for c in clauses)

    if inner.startswith("base "):
        return lambda song: True

    for operator, test in (
            (" == ", lambda tag, want: tag == want),
            (" contains ", lambda tag, want: want in tag)):
        if operator in inner:
            name, _, raw = inner.partition(operator)
            norm = str.casefold if fold else (lambda value: value)
            want = norm(unquote_term(raw.strip()))
            tag = name.strip()
            return lambda song, tag=tag, want=want, test=test, norm=norm: test(
                norm(lookup(song, tag)), want)
    raise Ack(f"Unknown filter type: {text}", code=2)


def unquote_term(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    out, escape = [], False
    for char in text:
        if escape:
            out.append(char)
            escape = False
        elif char == "\\":
            escape = True
        else:
            out.append(char)
    return "".join(out)


#: Tag names arrive in whatever case the client used.
CANONICAL = {name.lower(): name for name in
             ("Artist", "AlbumArtist", "Album", "Title", "Track", "Date",
              "Genre", "Disc")}


def lookup(song: tuple[str, dict[str, str]], tag: str) -> str:
    if tag.lower() == "file":
        return song[0]
    return song[1].get(CANONICAL.get(tag.lower(), tag), "")


class FakeMpd:
    def __init__(self, password: str = "", version: str = "0.24.0",
                 mixer: bool = True, greeting: str | None = None) -> None:
        self.password = password
        self.version = version
        self.mixer = mixer
        self.greeting = greeting
        self.songs = list(LIBRARY)
        self.server: asyncio.Server | None = None
        self.port = 0

        self.queue: list[str] = []
        self.status = "stop"
        self.volume = 42
        self.options = {"repeat": "0", "random": "0", "single": "0",
                        "consume": "0"}
        self.started = 0.0
        self.offset = 0.0
        self.error = ""
        #: URIs that fail to play, the way an unreachable stream would.
        self.broken: set[str] = set()
        #: Every command the server was asked to run, for the tests to assert on.
        self.seen: list[str] = []
        self._waiters: list[asyncio.Event] = []
        self._ticker: asyncio.Task | None = None


    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._serve, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self._ticker = asyncio.create_task(self._tick())

    async def stop(self) -> None:
        if self._ticker:
            self._ticker.cancel()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()

    async def _tick(self) -> None:
        """Notice when the pretend track has run out, as MPD would."""
        while True:
            await asyncio.sleep(0.05)
            if self.status != "play":
                continue
            if self.queue and self.queue[0] in self.broken:
                self.status, self.error = "stop", "Failed to open"
                self.wake()
            elif self.elapsed() >= self.duration():
                self.status = "stop"
                self.wake()

    def wake(self) -> None:
        for event in self._waiters:
            event.set()


    def duration(self) -> float:
        if not self.queue:
            return 0.0
        for uri, tags in self.songs:
            if uri == self.queue[0]:
                return float(tags.get("duration") or 0)
        return 0.0

    def elapsed(self) -> float:
        if self.status == "play":
            return self.offset + (time.monotonic() - self.started)
        return self.offset


    async def _serve(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        writer.write(((self.greeting if self.greeting is not None
                       else f"OK MPD {self.version}") + "\n").encode())
        await writer.drain()
        authorised = not self.password
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                args = split_args(raw.decode().rstrip("\n"))
                if not args:
                    continue
                self.seen.append(args[0])
                try:
                    if args[0] == "password":
                        if len(args) < 2 or args[1] != self.password:
                            raise Ack("incorrect password", code=3)
                        authorised = True
                        body: list[bytes] = []
                    elif not authorised:
                        raise Ack("you don't have permission", code=4)
                    else:
                        body = await self._run(args, reader)
                except Ack as ack:
                    writer.write(f"ACK [{ack.code}@0] {{{args[0]}}} "
                                 f"{ack}\n".encode())
                    await writer.drain()
                    continue
                for chunk in body:
                    writer.write(chunk)
                writer.write(b"OK\n")
                await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            writer.close()


    async def _run(self, args: list[str],
                   reader: asyncio.StreamReader) -> list[bytes]:
        name, rest = args[0], args[1:]
        handler = getattr(self, "_cmd_" + name, None)
        if handler is None:
            raise Ack(f"unknown command {name!r}", code=5)
        result = handler(rest)
        if asyncio.iscoroutine(result):
            result = await result
        return [line if isinstance(line, bytes) else (line + "\n").encode()
                for line in (result or [])]

    def _cmd_ping(self, args): return []

    def _cmd_clearerror(self, args):
        self.error = ""
        return []

    def _cmd_config(self, args):
        raise Ack("Command only permitted to local clients", code=4)

    def _cmd_status(self, args):
        lines = [f"{k}: {v}" for k, v in self.options.items()]
        lines.append(f"state: {self.status}")
        lines.append(f"playlistlength: {len(self.queue)}")
        if self.error:
            lines.append(f"error: {self.error}")
        if self.mixer:
            lines.append(f"volume: {self.volume}")
        if self.status in ("play", "pause") and self.queue:
            lines.append(f"elapsed: {self.elapsed():.3f}")
            lines.append(f"duration: {self.duration():.3f}")
            lines.append("song: 0")
        return lines

    # -- browsing ---------------------------------------------------------

    def _song_lines(self, songs) -> list[str]:
        out: list[str] = []
        for uri, tags in songs:
            out.append(f"file: {uri}")
            for key, value in tags.items():
                out.append(f"{key}: {value}")
        return out

    def _matching(self, args: list[str], fold: bool = False):
        """The songs a command's filter selects, and whatever follows it.

        The filter is optional, and always the modern parenthesised form.
        """
        if args and args[0].startswith("("):
            predicate, rest = parse_filter(args[0], fold), args[1:]
        else:
            predicate, rest = (lambda song: True), args
        songs = [s for s in self.songs if predicate(s)]
        if "window" in rest:
            start, _, end = rest[rest.index("window") + 1].partition(":")
            songs = songs[int(start):int(end) if end else None]
        return songs

    def _cmd_find(self, args):
        return self._song_lines(self._matching(args))

    def _cmd_search(self, args):
        """``search`` is the case-insensitive twin of ``find``."""
        return self._song_lines(self._matching(args, fold=True))

    def _cmd_list(self, args):
        if not args:
            raise Ack("too few arguments", code=2)
        tag, rest = args[0], args[1:]
        groups: list[str] = []
        while "group" in rest:
            index = rest.index("group")
            groups.append(rest[index + 1])
            rest = rest[:index] + rest[index + 2:]
        songs = self._matching(rest)

        seen: set[tuple] = set()
        rows: list[tuple[tuple[str, ...], str]] = []
        for song in songs:
            value = lookup(song, tag)
            if not value:
                continue
            key = tuple(lookup(song, g) for g in groups)
            if (key, value) in seen:
                continue
            seen.add((key, value))
            rows.append((key, value))

        out: list[str] = []
        current: tuple | None = None
        for key, value in rows:
            if key != current:
                for group, group_value in zip(groups, key):
                    out.append(f"{CANONICAL.get(group.lower(), group)}: "
                               f"{group_value}")
                current = key
            out.append(f"{CANONICAL.get(tag.lower(), tag)}: {value}")
        return out

    def _cmd_listplaylists(self, args):
        out = []
        for name in PLAYLISTS:
            out.append(f"playlist: {name}")
            out.append("Last-Modified: 2026-01-01T00:00:00Z")
        return out

    def _cmd_listplaylistinfo(self, args):
        uris = PLAYLISTS.get(args[0] if args else "")
        if uris is None:
            raise Ack("No such playlist", code=50)
        return self._song_lines([s for s in self.songs if s[0] in uris])

    # -- art --------------------------------------------------------------

    def _binary(self, blob: bytes, offset: int) -> list:
        if offset >= len(blob):
            raise Ack("Bad file offset", code=2)
        piece = blob[offset:offset + CHUNK]
        return [f"size: {len(blob)}",
                f"binary: {len(piece)}".encode() + b"\n" + piece + b"\n"]

    def _cmd_albumart(self, args):
        uri, offset = args[0], int(args[1]) if len(args) > 1 else 0
        if uri != ART_OWNER:
            raise Ack("No file exists", code=50)
        return self._binary(ART, offset)

    def _cmd_readpicture(self, args):
        uri, offset = args[0], int(args[1]) if len(args) > 1 else 0
        if uri != EMBEDDED_OWNER:
            return []          # MPD answers a bare OK when there is no picture
        return self._binary(EMBEDDED, offset)

    # -- playback ---------------------------------------------------------

    def _cmd_clear(self, args):
        self.queue.clear()
        self.status, self.offset = "stop", 0.0
        self.wake()
        return []

    def _cmd_add(self, args):
        self.queue.append(args[0])
        return []

    def _cmd_play(self, args):
        if not self.queue:
            raise Ack("Playlist is empty", code=2)
        self.status, self.offset = "play", 0.0
        self.started = time.monotonic()
        self.wake()
        return []

    def _cmd_pause(self, args):
        want = args[0] if args else ("0" if self.status == "pause" else "1")
        if want == "1" and self.status == "play":
            self.offset = self.elapsed()
            self.status = "pause"
        elif want == "0" and self.status == "pause":
            self.started = time.monotonic()
            self.status = "play"
        self.wake()
        return []

    def _cmd_stop(self, args):
        self.status, self.offset = "stop", 0.0
        self.wake()
        return []

    def _cmd_seekcur(self, args):
        self.offset = float(args[0])
        self.started = time.monotonic()
        self.wake()
        return []

    def _cmd_setvol(self, args):
        if not self.mixer:
            raise Ack("problems setting volume", code=52)
        self.volume = int(args[0])
        self.wake()
        return []

    def _option(self, name, args):
        self.options[name] = args[0]
        self.wake()
        return []

    def _cmd_repeat(self, args): return self._option("repeat", args)
    def _cmd_random(self, args): return self._option("random", args)
    def _cmd_single(self, args): return self._option("single", args)
    def _cmd_consume(self, args): return self._option("consume", args)

    async def _cmd_idle(self, args):
        event = asyncio.Event()
        self._waiters.append(event)
        try:
            await event.wait()
        finally:
            self._waiters.remove(event)
        return ["changed: player"]
