import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from tests.audio import album_tracks
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def get(client: AsyncClient, user: SubsonicUser, method: str, **params: str) -> Any:
    response = await client.get(f"/rest/{method}", params=user.params(**params))
    return response.json()["subsonic-response"]


def _set_mtime(paths: list[Path], when: datetime) -> None:
    for path in paths:
        os.utime(path, (when.timestamp(), when.timestamp()))


async def _albums(client: AsyncClient, user: SubsonicUser, **params: str) -> list[Any]:
    data = await get(client, user, "getAlbumList2", **params)
    assert data["status"] == "ok", data
    return data["albumList2"].get("album", [])


@pytest.fixture
async def albums(db: Database, library: Path) -> dict[str, list[Path]]:
    tracks = {
        "Old": album_tracks(library, "Band", "Old", 2, date="1999"),
        "Middle": album_tracks(library, "Band", "Middle", 1, date="2005"),
        "New": album_tracks(library, "Other", "New", 1, date="2020"),
    }
    _set_mtime(tracks["Old"], datetime(2020, 1, 1, tzinfo=UTC))
    _set_mtime(tracks["Middle"], datetime(2022, 6, 1, tzinfo=UTC))
    _set_mtime(tracks["New"], datetime(2024, 3, 1, tzinfo=UTC))
    await run_scan(db)
    return tracks


async def test_newest_uses_the_file_dates(
    client: AsyncClient, user: SubsonicUser, albums: dict[str, list[Path]]
) -> None:
    newest = await _albums(client, user, type="newest")
    assert [a["name"] for a in newest] == ["New", "Middle", "Old"]
    assert newest[0]["created"].startswith("2024-03-01")  # when the files were written


async def test_plays_feed_frequent_and_recent(
    client: AsyncClient, user: SubsonicUser, admin: SubsonicUser, albums: dict[str, list[Path]]
) -> None:
    by_name = {a["name"]: a for a in await _albums(client, user, type="alphabeticalByName")}
    assert list(by_name) == ["Middle", "New", "Old"]
    songs = (await get(client, user, "getAlbum", id=by_name["Old"]["id"]))["album"]["song"]
    middle_song = (await get(client, user, "getAlbum", id=by_name["Middle"]["id"]))["album"][
        "song"
    ][0]

    # "Now playing" notifications do not count.
    assert (await get(client, user, "scrobble", id=songs[0]["id"], submission="false"))[
        "status"
    ] == "ok"
    assert await _albums(client, user, type="frequent") == []
    # Two songs of "Old", then one of "Middle" (played last).
    for song_id, time in ((songs[0]["id"], "1700000000000"), (songs[1]["id"], "1700000100000")):
        assert (await get(client, user, "scrobble", id=song_id, time=time))["status"] == "ok"
    assert (await get(client, user, "scrobble", id=middle_song["id"]))["status"] == "ok"

    frequent = await _albums(client, user, type="frequent")
    assert [(a["name"], a["playCount"]) for a in frequent] == [("Old", 2), ("Middle", 1)]
    recent = await _albums(client, user, type="recent")
    assert [a["name"] for a in recent] == ["Middle", "Old"]
    assert recent[1]["played"].startswith("2023-11-14")  # time=1700000100000

    song = (await get(client, user, "getSong", id=songs[0]["id"]))["song"]
    assert song["playCount"] == 1
    # Plays are per user.
    assert await _albums(client, admin, type="frequent") == []


async def test_other_list_types(
    client: AsyncClient, user: SubsonicUser, albums: dict[str, list[Path]]
) -> None:
    assert len(await _albums(client, user, type="random", size="2")) == 2
    by_year = await _albums(client, user, type="byYear", fromYear="2010", toYear="1990")
    assert [a["name"] for a in by_year] == ["Middle", "Old"]  # fromYear > toYear: newest first
    by_artist = await _albums(client, user, type="alphabeticalByArtist")
    assert [a["name"] for a in by_artist] == ["Middle", "Old", "New"]
    assert [
        a["name"] for a in await _albums(client, user, type="newest", size="1", offset="1")
    ] == ["Middle"]

    bad = await get(client, user, "getAlbumList2", type="nonsense")
    assert bad["status"] == "failed"
    missing = await get(client, user, "getAlbumList2", type="byYear")
    assert missing["status"] == "failed"
    assert (await get(client, user, "scrobble", id="00000000-0000-0000-0000-000000000000"))[
        "error"
    ]["code"] == 70


async def test_retagging_does_not_make_an_album_new(
    client: AsyncClient, user: SubsonicUser, db: Database, albums: dict[str, list[Path]]
) -> None:
    _set_mtime(albums["Old"], datetime.now(UTC))  # e.g. tags rewritten by beets today
    await run_scan(db)
    newest = await _albums(client, user, type="newest")
    assert [a["name"] for a in newest] == ["New", "Middle", "Old"]
    assert newest[2]["created"].startswith("2020-01-01")
