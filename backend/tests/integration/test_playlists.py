"""Playlists through the Subsonic API."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from tests.audio import album_tracks
from tests.integration.conftest import SubsonicUser, _create_user

pytestmark = pytest.mark.integration


async def call(client: AsyncClient, user: SubsonicUser, method: str, **params: Any) -> Any:
    response = await client.get(f"/rest/{method}", params=user.params(**params))
    return response.json()["subsonic-response"]


async def ok(client: AsyncClient, user: SubsonicUser, method: str, **params: Any) -> Any:
    data = await call(client, user, method, **params)
    assert data["status"] == "ok", data
    return data


@pytest.fixture
async def songs(db: Database, library: Path, client: AsyncClient, user: SubsonicUser) -> list[str]:
    album_tracks(library, "Band", "Album", 4)
    await run_scan(db)
    album = (await ok(client, user, "getAlbumList2", type="newest"))["albumList2"]["album"][0]
    return [s["id"] for s in (await ok(client, user, "getAlbum", id=album["id"]))["album"]["song"]]


async def test_playlist_lifecycle(
    client: AsyncClient, user: SubsonicUser, admin: SubsonicUser, songs: list[str]
) -> None:
    created = (
        await ok(client, user, "createPlaylist", name="Road trip", songId=[songs[2], songs[0]])
    )["playlist"]
    assert (created["name"], created["songCount"], created["owner"], created["public"]) == (
        "Road trip",
        2,
        user.username,
        False,
    )
    assert [s["id"] for s in created["entry"]] == [songs[2], songs[0]]
    playlist_id = created["id"]

    await ok(
        client,
        user,
        "updatePlaylist",
        playlistId=playlist_id,
        name="Road trip 2026",
        public="true",
        songIdToAdd=[songs[3], songs[1]],
        songIndexToRemove="0",
    )
    playlist = (await ok(client, user, "getPlaylist", id=playlist_id))["playlist"]
    assert playlist["name"] == "Road trip 2026" and playlist["public"]
    assert [s["id"] for s in playlist["entry"]] == [songs[0], songs[3], songs[1]]

    # Public: other users see it.
    assert [
        p["name"] for p in (await ok(client, admin, "getPlaylists"))["playlists"]["playlist"]
    ] == ["Road trip 2026"]
    # createPlaylist with an id replaces the songs.
    await ok(client, user, "createPlaylist", playlistId=playlist_id, songId=[songs[1]])
    assert (await ok(client, user, "getPlaylist", id=playlist_id))["playlist"]["songCount"] == 1

    await ok(client, user, "deletePlaylist", id=playlist_id)
    assert (await call(client, user, "getPlaylist", id=playlist_id))["error"]["code"] == 70


async def test_private_playlists(
    app: FastAPI, client: AsyncClient, user: SubsonicUser, songs: list[str]
) -> None:
    other = await _create_user(app, is_admin=False)  # a second regular user
    mine = (await ok(client, user, "createPlaylist", name="Private", songId=songs[0]))["playlist"]
    assert (await ok(client, other, "getPlaylists"))["playlists"]["playlist"] == []
    assert (await call(client, other, "getPlaylist", id=mine["id"]))["error"]["code"] == 70

    await ok(client, user, "updatePlaylist", playlistId=mine["id"], public="true")
    refused = await call(client, other, "deletePlaylist", id=mine["id"])
    assert refused["error"]["code"] == 50
