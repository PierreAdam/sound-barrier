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


async def test_players_keep_their_own_queue(
    app: FastAPI, user: SubsonicUser, admin: SubsonicUser, library: Path, db: Database
) -> None:
    album_tracks(library, "Band", "Album", 2)
    await run_scan(db)
    ids = await _song_ids(db)

    async with signed_in(app, user) as client:
        assert (await client.get("/api/players")).json() == {
            "shared": {"songCount": 0, "updatedAt": None},
            "players": [],
            "maxPlayers": 20,
        }
        created = await client.post("/api/players", json={"name": "  Phone  "})
        assert created.status_code == 201
        phone = created.json()
        assert (phone["name"], phone["songCount"]) == ("Phone", 0)

        # The Shared queue and the phone's never mix.
        shared = {"songIds": [ids[0]], "currentIndex": 0, "positionMs": 1000}
        await client.put("/api/queue", json=shared)
        mine = {"songIds": [ids[1], ids[0]], "currentIndex": 1, "positionMs": 5000}
        saved = await client.put("/api/queue", params={"player": phone["id"]}, json=mine)
        assert saved.json() == {"revision": 1}
        queue = (await client.get("/api/queue", params={"player": phone["id"]})).json()
        assert ([s["id"] for s in queue["songs"]], queue["positionMs"]) == ([ids[1], ids[0]], 5000)
        assert [s["id"] for s in (await client.get("/api/queue")).json()["songs"]] == [ids[0]]
        revision = await client.get("/api/queue/revision", params={"player": phone["id"]})
        assert revision.json() == {"revision": 1}
        listed = (await client.get("/api/players")).json()
        assert [(p["name"], p["songCount"]) for p in listed["players"]] == [("Phone", 2)]
        assert listed["shared"]["songCount"] == 1

        renamed = await client.put(f"/api/players/{phone['id']}", json={"name": "My phone"})
        assert renamed.json()["name"] == "My phone"

    # Another user's player does not exist for them.
    async with signed_in(app, admin) as other:
        assert (await other.get("/api/players")).json()["players"] == []
        for response in (
            await other.get("/api/queue", params={"player": phone["id"]}),
            await other.put("/api/queue", params={"player": phone["id"]}, json=mine),
            await other.delete(f"/api/players/{phone['id']}"),
        ):
            assert response.status_code == 404

    async with signed_in(app, user) as client:
        assert (await client.delete(f"/api/players/{phone['id']}")).status_code == 204
        gone = await client.get("/api/queue", params={"player": phone["id"]})
        assert gone.status_code == 404  # the browser goes back to Shared
        assert [s["id"] for s in (await client.get("/api/queue")).json()["songs"]] == [ids[0]]


async def test_player_names(app: FastAPI, user: SubsonicUser) -> None:
    async with signed_in(app, user) as client:
        assert (await client.post("/api/players", json={"name": "PC"})).status_code == 201
        refused = {
            "pc": 409,  # whatever the case
            "shared": 400,  # the player every browser uses
            " ": 400,
            "x" * 41: 400,
        }
        for name, code in refused.items():
            assert (await client.post("/api/players", json={"name": name})).status_code == code
        tablet = (await client.post("/api/players", json={"name": "Tablet"})).json()
        taken = await client.put(f"/api/players/{tablet['id']}", json={"name": "PC"})
        assert taken.status_code == 409
        same = await client.put(f"/api/players/{tablet['id']}", json={"name": "tablet"})
        assert same.json()["name"] == "tablet"  # its own name, another case

        for number in range(18):
            await client.post("/api/players", json={"name": f"Player {number}"})
        assert len((await client.get("/api/players")).json()["players"]) == 20
        full = await client.post("/api/players", json={"name": "One more"})
        assert (full.status_code, full.json()["detail"]) == (400, "You can have at most 20 players")
