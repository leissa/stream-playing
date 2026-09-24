"""Thin asyncio wrapper around an ``mpv --idle`` process driven over JSON IPC.

mpv does the hard parts of audio playback -- network buffering, seeking inside
a streamed file, the codec zoo, ReplayGain -- so the daemon only has to feed it
URLs and react to its property changes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")

#: Properties the player needs to be told about as they change.
OBSERVED = (
    "pause",
    "time-pos",
    "duration",
    "core-idle",
    "volume",
    "eof-reached",
    "seeking",
    "cache-buffering-state",
    "metadata",
)


class MpvError(RuntimeError):
    pass


class Mpv:
    """One long-lived mpv process.

    ``on_event(name, payload)`` and ``on_property(name, value)`` are awaited for
    every IPC event; they run on the same loop as everything else.
    """

    def __init__(
        self,
        on_event: Callable[[str, dict], Awaitable[None]],
        on_property: Callable[[str, Any], Awaitable[None]],
        extra_args: list[str] | None = None,
    ) -> None:
        self._on_event = on_event
        self._on_property = on_property
        self._extra_args = extra_args or []

        self._socket = RUNTIME_DIR / f"streamplay-mpv-{os.getpid()}.sock"
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        # Handlers may issue new mpv commands, so they must not run inside the
        # socket reader -- that would wait for a reply the reader itself has to
        # deliver. Events are handed to a consumer task instead, which keeps
        # them ordered without the re-entrancy.
        self._events: asyncio.Queue[tuple[str, str, object]] = asyncio.Queue()
        self._event_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 1
        self._observe_ids: dict[int, str] = {}
        self._starting: asyncio.Lock = asyncio.Lock()
        self._closed = False

    # ------------------------------------------------------------ lifecycle

    @property
    def alive(self) -> bool:
        return (
            self._proc is not None
            and self._proc.returncode is None
            and self._writer is not None
        )

    async def start(self) -> None:
        async with self._starting:
            if self.alive:
                return
            await self._teardown()

            if not shutil.which("mpv"):
                raise MpvError("mpv is not installed")

            self._socket.unlink(missing_ok=True)
            args = [
                "mpv",
                "--idle=yes",
                "--no-video",
                "--no-terminal",
                "--audio-display=no",
                "--gapless-audio=yes",
                "--keep-open=no",
                "--force-window=no",
                "--msg-level=all=warn",
                "--replaygain=track",
                "--audio-client-name=streamplay",
                # Give network streams a healthy buffer so a hiccup on the way
                # from the music server does not turn into an audible dropout.
                "--cache=yes",
                "--demuxer-max-bytes=64MiB",
                "--demuxer-readahead-secs=30",
                f"--input-ipc-server={self._socket}",
                *self._extra_args,
            ]
            log.info("starting mpv")
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

            deadline = time.monotonic() + 10.0
            last_exc: Exception | None = None
            while time.monotonic() < deadline:
                if self._proc.returncode is not None:
                    raise MpvError(f"mpv exited immediately ({self._proc.returncode})")
                try:
                    self._reader, self._writer = await asyncio.open_unix_connection(
                        str(self._socket)
                    )
                    break
                except (FileNotFoundError, ConnectionRefusedError, OSError) as exc:
                    last_exc = exc
                    await asyncio.sleep(0.05)
            else:
                raise MpvError(f"could not connect to mpv IPC socket: {last_exc}")

            self._closed = False
            self._reader_task = asyncio.create_task(
                self._read_loop(), name="mpv-reader"
            )
            self._event_task = asyncio.create_task(
                self._event_loop(), name="mpv-events"
            )
            for index, prop in enumerate(OBSERVED, start=1):
                self._observe_ids[index] = prop
                await self.command("observe_property", index, prop)

    async def _teardown(self) -> None:
        for task in (self._reader_task, self._event_task):
            if task:
                task.cancel()
        self._reader_task = self._event_task = None
        if self._writer:
            try:
                self._writer.close()
            except Exception:
                pass
        self._writer = self._reader = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MpvError("mpv connection closed"))
        self._pending.clear()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self._proc.kill()
        self._proc = None
        self._socket.unlink(missing_ok=True)

    async def close(self) -> None:
        self._closed = True
        await self._teardown()

    # ----------------------------------------------------------------- ipc

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                await self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("mpv reader failed")
        finally:
            if not self._closed:
                log.warning("mpv IPC connection lost")
                self._events.put_nowait(("event", "ipc-closed", {}))

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        if "request_id" in msg:
            fut = self._pending.pop(msg["request_id"], None)
            if fut and not fut.done():
                if msg.get("error", "success") != "success":
                    fut.set_exception(MpvError(msg.get("error", "unknown error")))
                else:
                    fut.set_result(msg.get("data"))
            return

        event = msg.get("event")
        if event == "property-change":
            self._events.put_nowait(
                ("property", msg.get("name", ""), msg.get("data")))
        elif event:
            self._events.put_nowait(("event", event, msg))

    async def _event_loop(self) -> None:
        while True:
            kind, name, payload = await self._events.get()
            try:
                if kind == "property":
                    await self._on_property(name, payload)
                else:
                    await self._on_event(name, payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("mpv %s handler failed for %s", kind, name)

    async def command(self, *args: Any, timeout: float = 10.0) -> Any:
        if not self.alive:
            raise MpvError("mpv is not running")
        assert self._writer is not None

        request_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = fut

        payload = json.dumps({"command": list(args), "request_id": request_id})
        try:
            self._writer.write(payload.encode("utf-8") + b"\n")
            await self._writer.drain()
        except Exception as exc:
            self._pending.pop(request_id, None)
            raise MpvError(str(exc)) from exc

        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise MpvError(f"mpv command timed out: {args[0]}") from exc

    # ------------------------------------------------------------ shortcuts

    async def set_property(self, name: str, value: Any) -> None:
        await self.command("set_property", name, value)

    async def get_property(self, name: str) -> Any:
        return await self.command("get_property", name)

    async def loadfile(self, url: str, mode: str = "replace") -> None:
        await self.command("loadfile", url, mode, timeout=30.0)

    async def playlist_clear(self) -> None:
        await self.command("playlist-clear")

    async def stop(self) -> None:
        await self.command("stop")
