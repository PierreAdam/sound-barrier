from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import Database
from app.models import Song
from app.scanner.scanner import run_scan
from tests.audio import album_tracks
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration


async def _song_ids(db: Database) -> list[str]:
    async with db.session() as session:
        rows = await session.scalars(select(Song.id).order_by(Song.path))
        return [str(song_id) for song_id in rows]


async def test_web_queue_follows_the_user(
    app: FastAPI, user: SubsonicUser, admin: SubsonicUser, library: Path, db: Database
) -> None:
    paths = album_tracks(library, "Band", "Album", 3)
    await run_scan(db)
    ids = await _song_ids(db)

    async with signed_in(app, user) as pc_a:
        empty = (await pc_a.get("/api/queue")).json()
        assert (empty["revision"], empty["songs"], empty["currentIndex"]) == (0, [], -1)
        saved = await pc_a.put(
            "/api/queue",
            json={
                "songIds": [ids[2], ids[0], ids[1]],
                "originalOrder": [1, 2, 0],
                "currentIndex": 1,
                "positionMs": 42000,
            },
        )
        assert saved.json() == {"revision": 1}

    async with signed_in(app, user) as pc_b:  # another browser: the same queue
        queue = (await pc_b.get("/api/queue")).json()
        assert [s["title"] for s in queue["songs"]] == ["Track 3", "Track 1", "Track 2"]
        assert queue["songs"][0]["id"] == ids[2]  # Subsonic "Child" format
        assert (queue["originalOrder"], queue["currentIndex"], queue["positionMs"]) == (
            [1, 2, 0],
            1,
            42000,
        )
        assert (await pc_b.get("/api/queue/revision")).json() == {"revision": 1}

        # A song deleted since: dropped, the queue still makes sense.
        paths[2].unlink()
        await run_scan(db)
        queue = (await pc_b.get("/api/queue")).json()
        assert [s["title"] for s in queue["songs"]] == ["Track 1", "Track 2"]
        assert (queue["originalOrder"], queue["currentIndex"]) == ([0, 1], 0)

    async with signed_in(app, admin) as other_user:
        assert (await other_user.get("/api/queue")).json()["songs"] == []


@pytest.mark.parametrize(
    "bad",
    [
        {"songIds": [], "currentIndex": 3},
        {"songIds": ["00000000-0000-0000-0000-000000000001"], "originalOrder": [0, 0]},
    ],
)
async def test_invalid_queue_refused(
    app: FastAPI, user: SubsonicUser, bad: dict[str, object]
) -> None:
    async with signed_in(app, user) as client:
        assert (await client.put("/api/queue", json=bad)).status_code == 400


async def test_web_queue_needs_a_session(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/queue")).status_code == 401
