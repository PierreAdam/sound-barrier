"""Server players: a player that plays on the server itself, as one endless MP3 stream at
`/api/stream/<key>` that a Chromecast, VLC or any internet radio client plays. The web UI
controls it like any other player, through remote control (services/remote.py): it is a
target of the user's hub, of kind "server", mirrored and driven by the web UI's remote
mode. The device only listens.

The pipeline, per player:

    file -> ffmpeg (decoder, one per track) -> PCM -> pump -> ffmpeg (encoder) -> MP3 -> listeners

- A decoder turns the current track into raw PCM in one fixed format (whatever the file's
  format and sample rate): skipping or seeking kills it and starts another, the listeners
  never notice. Audiobooks and podcasts faster than 1x go through ffmpeg's `atempo`.
- The pump (this module) sends PCM to the encoder at real-time pace, in 20 ms frames, so
  the devices' buffers stay small and commands are heard quickly. Paused, it sends
  silence: the stream never stops, the devices stay connected.
- The encoder runs as long as the player: one continuous MP3 stream, copied to every
  listener. A listener joining gets the last seconds first (BURST_SECONDS), so its device
  starts at once.

Without listeners the pump waits (the position stays where it is), unless the player is
`always_on` (a radio playing for nobody).

The queue follows the web UI player's rules (services/server_queue.py). No volume (the
device playing the stream has its own) and no crossfade.

Kept in memory (one server process, like remote control).
"""

import asyncio
import contextlib
import logging
import secrets
import shutil
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.db import Database
from app.models import AppUser, MusicFolder, Song
from app.services import browsing
from app.services.remote import Member, RemoteHub, as_object
from app.services.server_queue import (
    CHAPTER_SLACK_SECONDS,
    Entry,
    Queue,
    chapter_index,
    next_index,
    previous_index,
    tracks_from,
)

log = logging.getLogger(__name__)

SAMPLE_RATE = 44100
CHANNELS = 2
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * 2  # signed 16-bit
FRAME_SECONDS = 0.02
FRAME_BYTES = int(BYTES_PER_SECOND * FRAME_SECONDS)  # a multiple of 4: whole samples
SILENCE = bytes(FRAME_BYTES)
BIT_RATE = 192  # kbps
BURST_SECONDS = 2.0  # of MP3 a new listener gets at once
OUTPUT_CHUNK = 4096
LISTENER_BACKLOG = 512  # output chunks (~85 s at 192 kbps): slower listeners are dropped
LATE_RESET_SECONDS = 1.0  # further behind than this (stalled): the pace starts over
RESTART_THRESHOLD_SECONDS = 3.0  # "previous" restarts the track after this
HEARTBEAT_SECONDS = 10.0  # the state is reported this often while playing (remotes' clocks)
TIMELINE_LENGTH = 16  # changes kept for the Cast receiver (what its device plays, late)
MAX_NAMED_LISTENERS = 32  # their start is kept (the Cast receiver's: see `now`)
SPEEDS = (1.0, 1.25, 1.5, 1.75, 2.0)  # of audiobooks and podcasts, as in the web UI
NAME = "Server player"
DEVICE = "Sound-Barrier"

# Given the song ids of tracks a remote sent: the files of those the user may play.
Resolve = Callable[[list[str]], Awaitable[dict[str, Path]]]


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def library_files(db: Database, user_id: uuid.UUID) -> Resolve:
    """The `Resolve` of a user: the files of the songs they may play."""

    async def resolve(song_ids: list[str]) -> dict[str, Path]:
        ids = [parsed for i in song_ids if (parsed := browsing.parse_id(i)) is not None]
        async with db.session() as session:
            user = await session.get(AppUser, user_id)
            if user is None or not ids:
                return {}
            playable = await browsing.get_songs(session, user, ids)
            rows = await session.execute(
                select(Song.id, Song.path, MusicFolder.path)
                .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
                .where(Song.id.in_(list(playable)))
            )
            return {str(song_id): Path(root) / path for song_id, path, root in rows}

    return resolve


def _decoder_command(ffmpeg: str, path: Path, start: float, speed: float) -> list[str]:
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if start > 0:
        command += ["-ss", f"{start:.3f}"]
    command += ["-i", str(path), "-vn", "-map", "0:a:0"]
    if speed != 1:
        command += ["-af", f"atempo={speed}"]
    return [*command, "-f", "s16le", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE), "pipe:1"]


def _encoder_command(ffmpeg: str) -> list[str]:
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        # Raw PCM needs no analysis: without these, ffmpeg reads seconds of it first.
        "-probesize",
        "32",
        "-analyzeduration",
        "0",
        "-fflags",
        "nobuffer",
        "-f",
        "s16le",
        "-ac",
        str(CHANNELS),
        "-ar",
        str(SAMPLE_RATE),
        "-i",
        "pipe:0",
        "-c:a",
        "libmp3lame",
        "-b:a",
        f"{BIT_RATE}k",
        # A live stream: no header announcing a length, no tags, every packet at once.
        "-write_xing",
        "0",
        "-id3v2_version",
        "0",
        "-flush_packets",
        "1",
        "-f",
        "mp3",
        "pipe:1",
    ]


async def _kill(process: asyncio.subprocess.Process | None) -> None:
    if process is None or process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    # communicate(), not wait(): a pipe left full (nobody reading any more) is paused, and
    # wait() would wait forever for it to close. This reads what is left, then its end.
    with contextlib.suppress(Exception):
        await asyncio.wait_for(process.communicate(), timeout=5)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


class ServerPlayer:
    def __init__(self, ffmpeg: str, resolve: Resolve, *, always_on: bool = False) -> None:
        self.id = uuid.uuid4().hex
        self.key = secrets.token_urlsafe(24)  # the stream's address: whoever has it listens
        self.target_id: str | None = None  # in the remote control hub
        self.always_on = always_on
        self.queue = Queue()
        self._ffmpeg = ffmpeg
        self._resolve = resolve
        self._playing = False
        self._pause_at_end = False
        self._speed = 1.0
        self._positioned: int | None = None  # the entry started at a chosen position
        self._track_start = 0.0  # seconds: where the current decoder started
        self._decoded = 0  # PCM bytes sent from the current decoder
        self._decoder_speed = 1.0  # the speed the current decoder plays at
        self._decoder: asyncio.subprocess.Process | None = None
        self._encoder: asyncio.subprocess.Process | None = None
        self._listeners: set[asyncio.Queue[bytes | None]] = set()
        self._burst: deque[bytes] = deque()
        self._burst_bytes = 0
        self._wake = asyncio.Event()
        self._changed = asyncio.Event()  # something to report
        self._lock = asyncio.Lock()  # commands against the pump's track changes
        self._tasks: list[asyncio.Task[None]] = []
        self._report: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        # The stream's own clock: seconds of sound sent to the encoder (silence too). Its
        # listeners hear it late (their buffer): the timeline stamps each change of what
        # plays with it, so a screen showing what they hear can follow (the Cast receiver).
        self._stream_time = 0.0
        self._timeline: deque[dict[str, Any]] = deque(maxlen=TIMELINE_LENGTH)
        # Named listeners (the Cast receiver's `?listener=`): the stream time of the first
        # sound each was sent (the burst goes back that far).
        self._starts: dict[str, float] = {}

    # --- lifecycle ------------------------------------------------------------------

    async def start(
        self, report: Callable[[dict[str, Any]], Awaitable[None]] | None = None
    ) -> None:
        """Starts the stream; `report` gets its "state" and "queue" messages (the hub)."""
        self._report = report
        self._encoder = await asyncio.create_subprocess_exec(
            *_encoder_command(self._ffmpeg),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._tasks = [
            asyncio.create_task(self._pump(), name="server-player-pump"),
            asyncio.create_task(self._fan_out(), name="server-player-output"),
        ]
        if report is not None:
            self._tasks.append(asyncio.create_task(self._reporter(), name="server-player-report"))

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await _kill(self._decoder)
        await _kill(self._encoder)
        for queue in self._listeners:
            self._offer(queue, None)
        self._listeners.clear()

    def set_always_on(self, always_on: bool) -> None:
        self.always_on = always_on
        self._wake.set()

    # --- commands (the web UI's remote mode, through the hub) -------------------------

    async def on_hub_message(self, message: dict[str, Any]) -> None:
        """What the hub sends its targets: only commands matter here."""
        if message.get("type") == "command":
            command = as_object(message.get("command"))
            if command is not None:
                await self.command(command)

    async def command(self, command: dict[str, Any]) -> None:
        name = command.get("name")
        # Tracks first, outside the lock: the pump goes on meanwhile.
        entries: list[Entry] = []
        if name in ("playQueue", "add", "playNext"):
            entries = await self._entries(command.get("tracks"))
        async with self._lock:
            await self._apply(name, command, entries)
            self._mark()
        self._changed.set()

    async def _entries(self, value: object) -> list[Entry]:
        tracks = tracks_from(value)
        files = await self._resolve([t["id"] for t in tracks]) if tracks else {}
        return self.queue.entries([(t, files[t["id"]]) for t in tracks if t["id"] in files])

    async def _apply(self, name: object, command: dict[str, Any], entries: list[Entry]) -> None:
        queue = self.queue
        current = queue.current
        duration = current.duration if current else 0.0
        if name == "toggle":
            self._playing = not self._playing and current is not None
        elif name == "play":
            self._playing = current is not None
        elif name in ("pause", "stop"):
            self._playing = False
        elif name == "next":
            await self._next()
        elif name == "previous":
            await self._previous()
        elif name == "seek" and (position := _finite(command.get("position"))) is not None:
            await self._seek(position, duration)
        elif name == "skip" and (seconds := _finite(command.get("seconds"))) is not None:
            await self._seek(self.position + seconds, duration)
        elif name == "shuffle":
            queue.toggle_shuffle()
        elif name == "repeat":
            queue.cycle_repeat()
        elif name == "pauseAtEnd" and queue.spoken:
            value = command.get("value")
            self._pause_at_end = value if isinstance(value, bool) else not self._pause_at_end
        elif name == "speed" and _finite(command.get("value")) in SPEEDS:
            self._speed = float(command["value"])
            if current is not None and current.long_form:
                await self._open(self.position)  # at the new speed from here
        elif name == "playQueue" and entries:
            index = command.get("index")
            start = index if isinstance(index, int) and 0 <= index < len(entries) else 0
            queue.replace(entries, start)
            at = _finite(command.get("startAt"))
            self._positioned = queue.current.key if queue.current and at is not None else None
            await self._load(at or 0.0, play=True)
        elif name == "add" and entries:
            if queue.add(entries):
                await self._load(0.0, play=False)
        elif name == "playNext" and entries:
            if queue.play_next(entries):
                await self._load(0.0, play=False)
        elif name == "playAt":
            position = queue.position_of(command.get("key"))
            if position >= 0:
                queue.index = position
                await self._load(0.0, play=True)
        elif name == "remove" and isinstance(command.get("keys"), list):
            if queue.remove(command["keys"]):
                await self._load(0.0, play=self._playing)
        elif name == "move":
            queue.move(command.get("key"), command.get("before"))
        elif name == "clear":
            queue.clear()
            await self._load(0.0, play=False)
        elif name == "undo" and not queue.undo():
            await self._load(0.0, play=False)  # what played is no longer queued
        # volume, mute, crossfade...: the device's own volume, and no crossfade here.

    async def _next(self) -> None:
        current = self.queue.current
        if current is None:
            return
        following = next(
            (c for c in current.chapters if c["start"] > self.position + CHAPTER_SLACK_SECONDS),
            None,
        )
        if following is not None:
            await self._open(following["start"])
            return
        index = next_index(self.queue.index, len(self.queue.order), self.queue.repeat_mode, False)
        if index is not None:
            self.queue.index = index
            await self._load(0.0, play=True)

    async def _previous(self) -> None:
        current = self.queue.current
        if current is None:
            return
        position = self.position
        chapters = current.chapters
        playing = chapter_index(chapters, position)
        if chapters and playing >= 0:
            start = chapters[playing]["start"]
            if position - start > RESTART_THRESHOLD_SECONDS:
                await self._open(start)
                return
            if playing > 0:
                await self._open(chapters[playing - 1]["start"])
                return
        if position > RESTART_THRESHOLD_SECONDS:
            await self._open(0.0)
            return
        index = previous_index(self.queue.index, len(self.queue.order), self.queue.repeat_mode)
        if index is None:
            await self._open(0.0)
            return
        self.queue.index = index
        await self._load(0.0, play=True)

    async def _seek(self, position: float, duration: float) -> None:
        end = max(duration - 0.5, 0.0) if duration > 0 else position
        await self._open(min(max(position, 0.0), end))

    async def _load(self, start: float, *, play: bool) -> None:
        """The current entry (a new one) from `start`: playing or paused."""
        current = self.queue.current
        if current is None or not current.long_form:
            self._pause_at_end = False
        if current is None or current.key != self._positioned:
            self._positioned = None
        self._playing = play and current is not None
        await self._open(start)

    # --- state ----------------------------------------------------------------------

    @property
    def position(self) -> float:
        return self._track_start + self._decoded / BYTES_PER_SECOND * self._decoder_speed

    @property
    def rate(self) -> float:
        current = self.queue.current
        return self._speed if current is not None and current.long_form else 1.0

    def state(self, queue_revision: int = 0) -> dict[str, Any]:
        """As the web UI's remote state (frontend/src/remote/protocol.ts `RemoteState`)."""
        queue = self.queue
        current = queue.current
        position = self.position
        chapters = current.chapters if current else []
        chapter = chapter_index(chapters, position)
        length = len(queue.order)
        has_next = current is not None and (
            chapter + 1 < len(chapters)
            or next_index(queue.index, length, queue.repeat_mode, False) is not None
        )
        return {
            "index": queue.index,
            "current": current.track if current else None,
            "currentKey": current.key if current else None,
            "playing": self._playing,
            "position": round(position, 3),
            "duration": current.duration if current else 0,
            "rate": self.rate,
            "volume": 1,
            "muted": False,
            "shuffle": queue.shuffle,
            "repeat": queue.repeat,
            "crossfade": False,
            "crossfadeSeconds": 5,
            "hasNext": has_next,
            "hasPrevious": current is not None,
            "canUndo": queue.can_undo,
            "spoken": queue.spoken,
            "chapter": chapter,
            "positioned": current is not None and current.key == self._positioned,
            "pauseAtEnd": self._pause_at_end,
            "speed": self._speed,
            "queueRevision": queue_revision,
        }

    def _mark(self) -> None:
        """What plays from now on (stream time), for the timeline."""
        current = self.queue.current
        mark = {
            "at": round(self._stream_time, 3),
            "key": current.key if current else None,
            "track": current.track if current else None,
            "position": round(self.position, 3),
            "playing": self._playing and current is not None,
            "rate": self.rate,
        }
        last = self._timeline[-1] if self._timeline else None
        if last is not None and last["at"] == mark["at"]:
            self._timeline.pop()  # replaced: nothing was heard of it
        self._timeline.append(mark)

    def now(self, listener: str | None = None) -> dict[str, Any]:
        """For a screen showing what a listener hears (the Cast receiver): the stream's
        clock, where that listener's sound started on it (`listenerStart`: it hears
        listenerStart + the seconds it played), and the recent changes. It hears stream
        time T: the last change at or before T, advanced by (T - at) * rate while playing."""
        start = self._starts.get(listener) if listener else None
        return {
            "streamTime": round(self._stream_time, 3),
            "listenerStart": None if start is None else round(start, 3),
            "timeline": list(self._timeline),
        }

    def queued_ids(self) -> set[str]:
        """The songs and covers queued or in the timeline (what the receiver may ask for)."""
        ids: set[str] = set()
        tracks = [entry.track for entry in self.queue.order]
        tracks += [mark["track"] for mark in self._timeline if mark["track"]]
        for track in tracks:
            ids.add(track["id"])
            if track.get("coverArt"):
                ids.add(track["coverArt"])
        return ids

    def info(self) -> dict[str, Any]:
        """For the web UI's Remote menu: the stream, who listens."""
        return {
            "target": self.target_id,
            "key": self.key,
            "listeners": len(self._listeners),
            "alwaysOn": self.always_on,
        }

    async def _reporter(self) -> None:
        """Reports the state when it changes, and every few seconds while playing; the
        queue first when its entries changed."""
        assert self._report is not None
        revision = 0
        signature: list[int] | None = None
        while True:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._changed.wait(), HEARTBEAT_SECONDS if self._playing else None
                )
            self._changed.clear()
            keys = self.queue.keys()
            try:
                if keys != signature:
                    revision += 1
                    signature = keys
                    tracks = [entry.track for entry in self.queue.order]
                    queue = {"revision": revision, "keys": keys, "tracks": tracks}
                    await self._report({"type": "queue", "queue": queue})
                await self._report({"type": "state", "state": self.state(revision)})
            except Exception:
                log.exception("Server player: could not report its state")

    # --- listeners ------------------------------------------------------------------

    async def listen(self, name: str | None = None) -> AsyncIterator[bytes]:
        """The MP3 stream, from now on (after the last BURST_SECONDS). `name`: its start
        on the stream's clock is kept (`now`)."""
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=LISTENER_BACKLOG)
        # No await between the two: nothing is missed or sent twice.
        burst = b"".join(self._burst)
        if name:
            burst_seconds = len(burst) * 8 / (BIT_RATE * 1000)
            self._starts[name] = max(self._stream_time - burst_seconds, 0.0)
            while len(self._starts) > MAX_NAMED_LISTENERS:
                del self._starts[next(iter(self._starts))]
        self._listeners.add(queue)
        self._wake.set()
        try:
            if burst:
                yield burst
            while True:
                chunk = await queue.get()
                if chunk is None:
                    return
                yield chunk
        finally:
            self._listeners.discard(queue)

    def _offer(self, queue: asyncio.Queue[bytes | None], chunk: bytes | None) -> bool:
        try:
            queue.put_nowait(chunk)
        except asyncio.QueueFull:
            return False
        return True

    async def _fan_out(self) -> None:
        assert self._encoder is not None and self._encoder.stdout is not None
        output = self._encoder.stdout
        burst_limit = int(BURST_SECONDS * BIT_RATE * 1000 / 8)
        while chunk := await output.read(OUTPUT_CHUNK):
            self._burst.append(chunk)
            self._burst_bytes += len(chunk)
            while self._burst_bytes - len(self._burst[0]) >= burst_limit:
                self._burst_bytes -= len(self._burst.popleft())
            for queue in list(self._listeners):
                if not self._offer(queue, chunk):
                    log.info("Server player: a listener too slow was dropped")
                    self._listeners.discard(queue)
        log.warning("Server player: the encoder stopped")

    # --- the pump -------------------------------------------------------------------

    async def _open(self, start: float) -> None:
        """(Re)starts the decoder on the current entry at `start` seconds."""
        await _kill(self._decoder)
        self._decoder = None
        self._track_start = start
        self._decoded = 0
        self._decoder_speed = self.rate
        current = self.queue.current
        self._mark()
        self._changed.set()
        if current is None:
            return
        self._decoder = await asyncio.create_subprocess_exec(
            *_decoder_command(self._ffmpeg, current.path, start, self._decoder_speed),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

    async def _ended(self) -> None:
        """The current file ended (or could not be read)."""
        queue = self.queue
        if self._pause_at_end and queue.spoken:
            # Paused on the next file (at its start), if there is one.
            self._pause_at_end = False
            following = next_index(queue.index, len(queue.order), "off", True)
            if following is not None:
                queue.index = following
            await self._load(0.0, play=False)
            return
        following = next_index(queue.index, len(queue.order), queue.repeat_mode, True)
        if following is None:
            await self._load(0.0, play=False)  # stopped, ready on the last track
            return
        queue.index = following
        await self._load(0.0, play=True)

    async def _check_pause_at_end(self, before: float) -> None:
        """Audiobooks and podcasts: paused at the next chapter's start, once (when the
        position crosses it)."""
        current = self.queue.current
        if not self._pause_at_end or current is None or not current.long_form:
            return
        end = next((c["start"] for c in current.chapters if c["start"] > before), None)
        # A seek landing just before a chapter's start is in that chapter: not its end.
        if end is None or end - self._track_start <= CHAPTER_SLACK_SECONDS:
            return
        if self.position >= end:
            self._pause_at_end = False
            self._playing = False
            await self._open(end)

    async def _next_frame(self) -> bytes:
        """20 ms of what is playing: the current track, silence when paused."""
        async with self._lock:
            while self._playing and self._decoder is not None:
                assert self._decoder.stdout is not None
                try:
                    frame = await self._decoder.stdout.readexactly(FRAME_BYTES)
                except asyncio.IncompleteReadError as end:
                    frame = end.partial
                if len(frame) == FRAME_BYTES:
                    before = self.position
                    self._decoded += FRAME_BYTES
                    await self._check_pause_at_end(before)
                    return frame
                await self._ended()
                if frame:
                    return frame + bytes(FRAME_BYTES - len(frame))
            return SILENCE

    async def _pump(self) -> None:
        assert self._encoder is not None and self._encoder.stdin is not None
        encoder = self._encoder.stdin
        deadline = time.monotonic()
        while True:
            if not self.always_on and not self._listeners:
                # Nobody listens: wait, the position stays where it is. What was encoded
                # before is stale for the next listener.
                self._wake.clear()
                self._burst.clear()
                self._burst_bytes = 0
                await self._wake.wait()
                deadline = time.monotonic()
            encoder.write(await self._next_frame())
            await encoder.drain()
            self._stream_time += FRAME_SECONDS
            deadline += FRAME_SECONDS
            delay = deadline - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            elif delay < -LATE_RESET_SECONDS:
                deadline = time.monotonic()


class ServerPlayers:
    """The server players, each a target of its user's remote control hub: one per user
    for now."""

    def __init__(self, hub: RemoteHub) -> None:
        self._hub = hub
        self._by_user: dict[uuid.UUID, tuple[ServerPlayer, Member]] = {}

    def of(self, user_id: uuid.UUID) -> ServerPlayer | None:
        found = self._by_user.get(user_id)
        return found[0] if found else None

    def by_key(self, key: str) -> ServerPlayer | None:
        return next(
            (p for p, _ in self._by_user.values() if secrets.compare_digest(p.key, key)), None
        )

    async def ensure(self, user_id: uuid.UUID, ffmpeg: str, resolve: Resolve) -> ServerPlayer:
        found = self._by_user.get(user_id)
        if found is not None:
            return found[0]
        player = ServerPlayer(ffmpeg, resolve)
        member = self._hub.join(user_id, player.on_hub_message, kind="server")
        player.target_id = member.id

        async def report(message: dict[str, Any]) -> None:
            await self._hub.handle(member, message)

        await player.start(report)
        await self._hub.handle(
            member,
            {
                "type": "target",
                "player": f"server:{player.id}",
                "playerName": NAME,
                "device": DEVICE,
                "takeOver": True,
            },
        )
        self._by_user[user_id] = (player, member)
        return player

    async def remove(self, user_id: uuid.UUID) -> None:
        found = self._by_user.pop(user_id, None)
        if found is not None:
            player, member = found
            await self._hub.leave(member)
            await player.close()

    async def close(self) -> None:
        for user_id in list(self._by_user):
            await self.remove(user_id)
