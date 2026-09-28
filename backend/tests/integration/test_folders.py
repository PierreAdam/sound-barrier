from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from tests.audio import album_tracks, make_track
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def get(client: AsyncClient, user: SubsonicUser, method: str, **params: str) -> Any:
    data = (await client.get(f"/rest/{method}", params=user.params(**params))).json()
    response = data["subsonic-response"]
    assert response["status"] == "ok", response
    return response


@pytest.fixture
async def folder_library(db: Database, library: Path) -> None:
    album_tracks(library, "Dethklok", "The Dethalbum", 2)
    album_tracks(library, "Dethklok", "Dethalbum II", 1)
    album_tracks(library, "Deaf Election", "Falling in Flames", 1)
    make_track(library / "Loose Song", title="Loose", artist="Nobody", album="Single")
    await run_scan(db)


async def test_browse_by_folders(
    client: AsyncClient, user: SubsonicUser, folder_library: None
) -> None:
    indexes = (await get(client, user, "getIndexes"))["indexes"]
    assert indexes["lastModified"] > 0
    artists = {a["name"]: a["id"] for i in indexes["index"] for a in i["artist"]}
    assert list(artists) == ["Deaf Election", "Dethklok"]
    assert [s["title"] for s in indexes["child"]] == ["Loose"]  # a song right in the root

    dethklok = (await get(client, user, "getMusicDirectory", id=artists["Dethklok"]))["directory"]
    assert dethklok["name"] == "Dethklok"
    albums = {c["title"]: c for c in dethklok["child"]}
    assert set(albums) == {"The Dethalbum", "Dethalbum II"}
    assert all(c["isDir"] for c in albums.values())

    album = (await get(client, user, "getMusicDirectory", id=albums["The Dethalbum"]["id"]))[
        "directory"
    ]
    assert album["parent"] == artists["Dethklok"]
    assert [(s["title"], s["isDir"], s["parent"]) for s in album["child"]] == [
        ("Track 1", False, album["id"]),
        ("Track 2", False, album["id"]),
    ]
    # Unchanged since: only the date.
    unchanged = await get(client, user, "getIndexes", ifModifiedSince=str(indexes["lastModified"]))
    assert "index" not in unchanged["indexes"] or unchanged["indexes"]["index"] == []


async def test_album_lists_and_search_as_folders(
    client: AsyncClient, user: SubsonicUser, folder_library: None
) -> None:
    listed = (await get(client, user, "getAlbumList", type="alphabeticalByName", size="10"))[
        "albumList"
    ]["album"]
    # By sort name ("The" ignored); the loose song's album too.
    assert [a["title"] for a in listed] == [
        "The Dethalbum",
        "Dethalbum II",
        "Falling in Flames",
        "Single",
    ]
    first = listed[0]
    assert first["isDir"] and first["artist"] == "Dethklok"
    # The folder of an album opens it.
    opened = (await get(client, user, "getMusicDirectory", id=first["id"]))["directory"]
    assert [s["title"] for s in opened["child"]] == ["Track 1", "Track 2"]
    # So does an album id (some clients mix them).
    by_album_id = (await get(client, user, "getMusicDirectory", id=first["albumId"]))["directory"]
    assert by_album_id["id"] == first["id"]

    found = (await get(client, user, "search2", query="deth"))["searchResult2"]
    assert [a["name"] for a in found["artist"]] == ["Dethklok"]
    assert {a["title"] for a in found["album"]} == {"The Dethalbum", "Dethalbum II"}
    assert all(a["isDir"] for a in found["album"])
    assert len(found["song"]) == 3


async def test_unknown_directory(
    client: AsyncClient, user: SubsonicUser, folder_library: None
) -> None:
    data = (
        await client.get(
            "/rest/getMusicDirectory", params=user.params(id="00000000-0000-0000-0000-000000000000")
        )
    ).json()["subsonic-response"]
    assert (data["status"], data["error"]["code"]) == ("failed", 70)
