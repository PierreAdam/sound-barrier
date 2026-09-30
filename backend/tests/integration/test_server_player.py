"""The server player's API (the pipeline and its commands: tests/unit/test_server_player.py)."""

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.core.db import Database
from app.models import AppUser, Song
from app.scanner.scanner import run_scan
from app.services.server_player import ServerPlayers, ffmpeg_path, library_files
from tests.audio import album_tracks
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(ffmpeg_path() is None, reason="ffmpeg is not installed"),
]


async def test_start_configure_and_stop(app: FastAPI, user: SubsonicUser) -> None:
    async with signed_in(app, user) as web:
        assert (await web.get("/api/server-player")).json() is None  # not started

        started = await web.post("/api/server-player")
        assert started.status_code == 200, started.text
        player = started.json()
        assert player["target"]  # listed in the user's Remote menu
        assert player["streamUrl"].endswith(f"/api/stream/{player['key']}")
        assert player["alwaysOn"] is False
        # Started again: the same one (the devices stay connected).
        assert (await web.post("/api/server-player")).json()["key"] == player["key"]

        updated = await web.put("/api/server-player", json={"alwaysOn": True})
        assert updated.json()["alwaysOn"] is True

        # For the Cast receiver (another origin): what plays, by the key only.
        key = player["key"]
        now = await web.get(f"/api/stream/{key}/now", params={"listener": "tv"})
        assert now.status_code == 200
        assert now.headers["access-control-allow-origin"] == "*"
        assert set(now.json()) == {"streamTime", "listenerStart", "timeline"}
        assert (
            await web.get(f"/api/stream/{key}/now", params={"listener": "no/pe"})
        ).status_code == 422
        # Only what this player plays: nothing queued, nothing given.
        not_queued = str(uuid.uuid4())
        assert (
            await web.get(f"/api/stream/{key}/cover", params={"id": not_queued})
        ).status_code == 404
        lyrics = await web.get(f"/api/stream/{key}/lyrics", params={"song": not_queued})
        assert lyrics.status_code == 404
        assert player["receiverAppId"] is None

        assert (await web.get("/api/stream/not-a-key")).status_code == 404
        assert (await web.delete("/api/server-player")).status_code == 204
        assert (await web.get("/api/server-player")).json() is None
        assert (await web.get(f"/api/stream/{player['key']}")).status_code == 404
        assert (await web.put("/api/server-player", json={"alwaysOn": True})).status_code == 404


async def test_it_only_plays_the_users_songs(
    app: FastAPI, user: SubsonicUser, library: Path, db: Database
) -> None:
    album_tracks(library, "Band", "Album", 2)
    await run_scan(db)
    async with db.session() as session:
        ids = [str(i) for i in await session.scalars(select(Song.id).order_by(Song.path))]
        user_id = await session.scalar(select(AppUser.id).where(AppUser.username == user.username))
    assert user_id is not None
    files = await library_files(db, user_id)([*ids, str(uuid.uuid4()), "not-an-id"])
    assert set(files) == set(ids)
    assert all(path.is_file() for path in files.values())
    players: ServerPlayers = app.state.server_players
    assert players.of(user_id) is None


async def test_the_cast_receiver_app_id_is_a_setting(
    app: FastAPI, admin: SubsonicUser, user: SubsonicUser
) -> None:
    async with signed_in(app, admin) as web:
        bad = await web.put("/api/external/settings", json={"castReceiverAppId": "not-an-id"})
        assert bad.status_code == 400
        saved = await web.put("/api/external/settings", json={"castReceiverAppId": " 1a2b3c4d "})
        assert saved.json()["castReceiverAppId"] == "1A2B3C4D"
    async with signed_in(app, user) as web:
        player = (await web.post("/api/server-player")).json()
        assert player["receiverAppId"] == "1A2B3C4D"  # what their Cast button uses
        assert player["dashcast"] is True  # allowed by default
        await web.delete("/api/server-player")
    async with signed_in(app, admin) as web:
        cleared = await web.put("/api/external/settings", json={"castReceiverAppId": ""})
        assert cleared.json()["castReceiverAppId"] is None
        off = await web.put("/api/external/settings", json={"dashcast": False})
        assert off.json()["dashcast"] is False
        await web.put("/api/external/settings", json={"dashcast": True})
