"""Stars, ratings, random songs, genres, now playing (Subsonic)."""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from tests.audio import album_tracks
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def call(client: AsyncClient, user: SubsonicUser, method: str, **params: Any) -> Any:
    response = await client.get(f"/rest/{method}", params=user.params(**params))
    return response.json()["subsonic-response"]


async def ok(client: AsyncClient, user: SubsonicUser, method: str, **params: Any) -> Any:
    data = await call(client, user, method, **params)
    assert data["status"] == "ok", data
    return data


@pytest.fixture
async def content(
    db: Database, library: Path, client: AsyncClient, user: SubsonicUser
) -> dict[str, Any]:
    album_tracks(library, "Dethklok", "The Dethalbum", 2, genre="Metal")
    album_tracks(library, "Émilie Simon", "Végétal", 1, genre="Pop")
    await run_scan(db)
    albums = (await ok(client, user, "getAlbumList2", type="alphabeticalByName"))["albumList2"][
        "album"
    ]
    detail = {a["name"]: (await ok(client, user, "getAlbum", id=a["id"]))["album"] for a in albums}
    return detail


async def test_stars(
    client: AsyncClient, user: SubsonicUser, admin: SubsonicUser, content: dict[str, Any]
) -> None:
    deth = content["The Dethalbum"]
    song = deth["song"][0]
    await ok(client, user, "star", id=song["id"], albumId=deth["id"], artistId=deth["artistId"])

    starred = (await ok(client, user, "getStarred2"))["starred2"]
    assert [s["id"] for s in starred["song"]] == [song["id"]]
    assert [a["id"] for a in starred["album"]] == [deth["id"]]
    assert [a["name"] for a in starred["artist"]] == ["Dethklok"]
    assert (await ok(client, user, "getSong", id=song["id"]))["song"]["starred"]
    # Folder flavour: the album as its folder.
    folders = (await ok(client, user, "getStarred"))["starred"]
    assert [a["title"] for a in folders["album"]] == ["The Dethalbum"] and folders["album"][0][
        "isDir"
    ]
    assert [a["name"] for a in folders["artist"]] == ["Dethklok"]
    # Stars are per user.
    assert (await ok(client, admin, "getStarred2"))["starred2"]["song"] == []

    await ok(client, user, "unstar", id=song["id"])
    assert (await ok(client, user, "getStarred2"))["starred2"]["song"] == []
    # A folder id (folder clients) stars the album it holds.
    await ok(client, user, "unstar", albumId=deth["id"])
    await ok(client, user, "star", id=folders["album"][0]["id"])
    assert [a["id"] for a in (await ok(client, user, "getStarred2"))["starred2"]["album"]] == [
        deth["id"]
    ]

    unknown = await call(client, user, "star", id="00000000-0000-0000-0000-000000000000")
    assert unknown["error"]["code"] == 70


async def test_ratings(client: AsyncClient, user: SubsonicUser, content: dict[str, Any]) -> None:
    song = content["The Dethalbum"]["song"][1]
    await ok(client, user, "setRating", id=song["id"], rating="4")
    assert (await ok(client, user, "getSong", id=song["id"]))["song"]["userRating"] == 4
    album = content["Végétal"]
    await ok(client, user, "setRating", id=album["id"], rating="5")
    highest = (await ok(client, user, "getAlbumList2", type="highest"))["albumList2"]["album"]
    assert [a["name"] for a in highest] == ["Végétal"]
    await ok(client, user, "setRating", id=song["id"], rating="0")  # removes it
    assert "userRating" not in (await ok(client, user, "getSong", id=song["id"]))["song"]
    assert (await call(client, user, "setRating", id=song["id"], rating="6"))["status"] == "failed"


async def test_genres_and_random_songs(
    client: AsyncClient, user: SubsonicUser, content: dict[str, Any]
) -> None:
    genres = (await ok(client, user, "getGenres"))["genres"]["genre"]
    assert [(g["value"], g["songCount"], g["albumCount"]) for g in genres] == [
        ("Metal", 2, 1),
        ("Pop", 1, 1),
    ]
    metal = (await ok(client, user, "getSongsByGenre", genre="metal", count="10"))["songsByGenre"][
        "song"
    ]
    assert [s["title"] for s in metal] == ["Track 1", "Track 2"]

    random = (await ok(client, user, "getRandomSongs", size="10"))["randomSongs"]["song"]
    assert len(random) == 3
    pop = (await ok(client, user, "getRandomSongs", genre="Pop"))["randomSongs"]["song"]
    assert [s["album"] for s in pop] == ["Végétal"]

    # XML: the genre name is the element text.
    xml = (await client.get("/rest/getGenres", params={**user.params(), "f": "xml"})).text
    assert ">Metal</genre>" in xml


async def test_now_playing(
    client: AsyncClient, user: SubsonicUser, admin: SubsonicUser, content: dict[str, Any]
) -> None:
    song = content["Végétal"]["song"][0]
    await ok(client, user, "scrobble", id=song["id"], submission="false")
    entries = (await ok(client, admin, "getNowPlaying"))["nowPlaying"]["entry"]
    mine = [e for e in entries if e["username"] == user.username]
    assert [(e["title"], e["playerName"], e["minutesAgo"]) for e in mine] == [
        (song["title"], "tests", 0)
    ]
