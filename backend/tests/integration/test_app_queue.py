"""The Subsonic apps' play queue (separate from the web UI's queue)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from tests.audio import album_tracks
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration

UNKNOWN = "00000000-0000-0000-0000-000000000000"


async def call(client: AsyncClient, user: SubsonicUser, method: str, **params: Any) -> Any:
    response = await client.get(f"/rest/{method}", params=user.params(**params))
    data = response.json()["subsonic-response"]
    assert data["status"] == "ok", data
    return data


@pytest.fixture
async def songs(db: Database, library: Path, client: AsyncClient, user: SubsonicUser) -> list[str]:
    album_tracks(library, "Band", "Album", 3)
    await run_scan(db)
    album = (await call(client, user, "getAlbumList2", type="newest"))["albumList2"]["album"][0]
    return [
        s["id"] for s in (await call(client, user, "getAlbum", id=album["id"]))["album"]["song"]
    ]


async def test_save_and_resume(
    app: FastAPI, client: AsyncClient, user: SubsonicUser, admin: SubsonicUser, songs: list[str]
) -> None:
    assert "playQueue" not in await call(client, user, "getPlayQueue")  # never saved

    # Unknown ids are dropped; a song may be queued twice.
    await call(
        client,
        user,
        "savePlayQueue",
        id=[songs[2], UNKNOWN, songs[0], songs[2]],
        current=songs[0],
        position="61000",
    )
    queue = (await call(client, user, "getPlayQueue"))["playQueue"]
    assert [s["id"] for s in queue["entry"]] == [songs[2], songs[0], songs[2]]
    assert (queue["current"], queue["position"], queue["changedBy"], queue["username"]) == (
        songs[0],
        61000,
        "tests",
        user.username,
    )

    # Index-based: the second copy of the same song is the current one.
    await call(
        client,
        user,
        "savePlayQueueByIndex",
        id=[songs[2], songs[0], songs[2]],
        currentIndex="2",
        position="5",
    )
    by_index = (await call(client, user, "getPlayQueueByIndex"))["playQueueByIndex"]
    assert (by_index["currentIndex"], by_index["position"]) == (2, 5)
    assert (await call(client, user, "getPlayQueue"))["playQueue"]["current"] == songs[2]

    # Per user, and apart from the web UI's queue.
    assert "playQueue" not in await call(client, admin, "getPlayQueue")
    async with signed_in(app, user) as web:
        assert (await web.get("/api/queue")).json()["songs"] == []

    await call(client, user, "savePlayQueue")  # no id: cleared
    assert "playQueue" not in await call(client, user, "getPlayQueue")


async def test_extension_is_advertised(client: AsyncClient, user: SubsonicUser) -> None:
    data = await call(client, user, "getOpenSubsonicExtensions")
    assert "indexBasedQueue" in [e["name"] for e in data["openSubsonicExtensions"]]
