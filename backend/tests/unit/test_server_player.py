"""The server player's pipeline, with the real ffmpeg (skipped without it), driven as the
web UI's remote mode drives it: commands, through the remote control hub."""

import asyncio
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.services.remote import RemoteHub
from app.services.server_player import BIT_RATE, ServerPlayer, ServerPlayers, ffmpeg_path
from tests.unit.test_remote import Inbox

FFMPEG = ffmpeg_path()
pytestmark = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg is not installed")


class Library:
    """Tone files, as tracks the web UI would send (song id -> file)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files: dict[str, Path] = {}

    def tone(self, name: str, seconds: float, rate: int = 44100, **extra: Any) -> dict[str, Any]:
        assert FFMPEG is not None
        path = self.root / name
        source = f"sine=frequency=440:sample_rate={rate}:duration={seconds}"
        subprocess.run(
            [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                source,
                str(path),
            ],
            check=True,
        )
        song_id = str(uuid.uuid4())
        self.files[song_id] = path
        return {"id": song_id, "title": path.stem, "durationSeconds": seconds, **extra}

    async def resolve(self, song_ids: list[str]) -> dict[str, Path]:
        return {i: self.files[i] for i in song_ids if i in self.files}


async def _player(library: Library, always_on: bool = False) -> ServerPlayer:
    assert FFMPEG is not None
    player = ServerPlayer(FFMPEG, library.resolve, always_on=always_on)
    await player.start()
    return player


async def _listen(player: ServerPlayer, seconds: float) -> int:
    """Bytes received by a listener during `seconds`."""
    received = 0

    async def consume() -> None:
        nonlocal received
        async for chunk in player.listen():
            received += len(chunk)

    task = asyncio.create_task(consume())
    await asyncio.sleep(seconds)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return received


async def test_plays_the_queue_in_real_time_across_formats(tmp_path: Path) -> None:
    library = Library(tmp_path)
    # Different formats and sample rates: one continuous stream all the same.
    tracks = [library.tone("one.mp3", 0.6), library.tone("two.m4a", 0.6, rate=22050)]
    player = await _player(library)
    try:
        await player.command({"name": "playQueue", "tracks": tracks, "index": 0})
        start = time.monotonic()
        received = await _listen(player, 2.0)
        elapsed = time.monotonic() - start
        state = player.state()
    finally:
        await player.close()
    assert state["index"] == 1  # went on to the second track
    assert state["playing"] is False  # then stopped at the end of the queue
    # Paced: about the bit rate (a bit less while the encoder starts), never a burst ahead.
    expected = BIT_RATE * 1000 / 8 * elapsed
    assert 0.5 * expected < received < 1.2 * expected


async def test_paused_it_keeps_streaming_silence(tmp_path: Path) -> None:
    library = Library(tmp_path)
    track = library.tone("one.mp3", 5)
    player = await _player(library)
    try:
        await player.command({"name": "playQueue", "tracks": [track], "startAt": 1.0})
        await player.command({"name": "pause"})
        received = await _listen(player, 1.0)
        assert received > 0  # the device stays connected
        assert player.position == pytest.approx(1.0)
        assert player.state()["positioned"] is True
        await player.command({"name": "play"})
        await _listen(player, 0.6)
        assert player.position > 1.2
        await player.command({"name": "seek", "position": 3.0})
        assert player.position == pytest.approx(3.0)
        await player.command({"name": "previous"})  # past 3 s: the track's start
        assert player.position == 0
    finally:
        await player.close()


async def test_songs_the_user_cannot_play_are_not_queued(tmp_path: Path) -> None:
    library = Library(tmp_path)
    mine = library.tone("mine.mp3", 5)
    player = await _player(library)
    try:
        stranger = {"id": str(uuid.uuid4()), "title": "Not in the library"}
        await player.command({"name": "playQueue", "tracks": [stranger, mine], "index": 0})
        assert [e.track["id"] for e in player.queue.order] == [mine["id"]]
        assert player.state()["current"]["id"] == mine["id"]
    finally:
        await player.close()


async def test_audiobooks_speed_and_chapters(tmp_path: Path) -> None:
    library = Library(tmp_path)
    chapters = [{"start": 0, "title": "One"}, {"start": 2, "title": "Two"}]
    book = library.tone("book.mp3", 6, longForm=True, chapters=chapters)
    player = await _player(library, always_on=True)
    try:
        await player.command({"name": "playQueue", "tracks": [book]})
        await player.command({"name": "speed", "value": 2})
        await asyncio.sleep(0.6)
        assert player.position > 0.9  # twice as fast
        assert player.state()["rate"] == 2
        await player.command({"name": "next"})  # the next chapter, in the same file
        assert player.position == pytest.approx(2.0)
        assert player.state()["chapter"] == 1
        await player.command({"name": "seek", "position": 0})
        await player.command({"name": "pauseAtEnd", "value": True})
        await asyncio.sleep(1.6)  # chapter one ends at 2 s, at 2x: after 1 s
        state = player.state()
        assert (state["playing"], state["pauseAtEnd"]) == (False, False)
        assert state["position"] == pytest.approx(2.0)  # paused at the next one's start
    finally:
        await player.close()


async def test_without_listeners_it_waits_unless_always_on(tmp_path: Path) -> None:
    library = Library(tmp_path)
    track = library.tone("one.mp3", 5)
    waiting = await _player(library)
    always = await _player(library, always_on=True)
    try:
        await waiting.command({"name": "playQueue", "tracks": [track]})
        await always.command({"name": "playQueue", "tracks": [track]})
        await asyncio.sleep(0.8)
        assert waiting.position == 0
        assert always.position > 0.4
    finally:
        await waiting.close()
        await always.close()


async def test_driven_through_the_remote_control_hub(tmp_path: Path) -> None:
    assert FFMPEG is not None
    library = Library(tmp_path)
    tracks = [library.tone("one.mp3", 5), library.tone("two.mp3", 5)]
    hub = RemoteHub()
    user = uuid.uuid4()
    players = ServerPlayers(hub)
    phone = Inbox()
    remote = hub.join(user, phone)
    await hub.handle(remote, {"type": "remote"})
    player = await players.ensure(user, FFMPEG, library.resolve)
    try:
        # Listed as a server target...
        (target,) = phone.last["targets"]
        assert (target["id"], target["kind"]) == (player.target_id, "server")
        # ...mirrored and driven like a tab.
        await hub.handle(remote, {"type": "watch", "target": target["id"]})
        command = {"name": "playQueue", "tracks": tracks, "index": 1}
        await hub.handle(remote, {"type": "command", "target": target["id"], "command": command})
        await asyncio.sleep(0.3)  # reported by its own task
        queue = phone.of("queue")[-1]["queue"]
        assert [t["id"] for t in queue["tracks"]] == [t["id"] for t in tracks]
        state = phone.of("state")[-1]["state"]
        assert (state["current"]["id"], state["playing"], state["queueRevision"]) == (
            tracks[1]["id"],
            True,
            queue["revision"],
        )
        assert state["currentKey"] == queue["keys"][1]

        await players.remove(user)
        assert phone.last == {"type": "targets", "targets": []}
    finally:
        await players.close()


async def test_the_timeline_tells_a_late_listener_what_it_hears(tmp_path: Path) -> None:
    library = Library(tmp_path)
    tracks = [library.tone("one.mp3", 5), library.tone("two.mp3", 5)]
    player = await _player(library)
    try:
        await player.command({"name": "playQueue", "tracks": tracks})
        received = 0

        async def listen() -> None:
            nonlocal received
            async for chunk in player.listen("tv"):
                received += len(chunk)

        task = asyncio.create_task(listen())
        await asyncio.sleep(0.8)
        await player.command({"name": "next"})
        await asyncio.sleep(0.4)
        now = player.now("tv")
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        await player.close()
    assert received > 0
    # Where the TV's sound started on the stream's clock: nothing was played before it.
    assert now["listenerStart"] == 0
    assert player.now("someone else")["listenerStart"] is None
    # The changes, stamped on that clock: the first track from 0, the second from ~0.8 s.
    first, second = now["timeline"][-2:]
    assert (first["track"]["id"], second["track"]["id"]) == (tracks[0]["id"], tracks[1]["id"])
    assert first["at"] < second["at"] <= now["streamTime"]
    assert 0.5 < second["at"] < 1.2
    assert (second["position"], second["playing"], second["rate"]) == (0, True, 1)
