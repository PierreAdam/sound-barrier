from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from app.services import music_folders
from tests.audio import album_tracks, make_track
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def get(client: AsyncClient, user: SubsonicUser, method: str, **params: str) -> Any:
    response = await client.get(f"/rest/{method}", params=user.params(**params))
    return response.json()["subsonic-response"]


async def test_get_artists(
    client: AsyncClient, db: Database, library: Path, user: SubsonicUser
) -> None:
    album_tracks(library, "The Beatles", "Abbey Road", 1)
    album_tracks(library, "Dethklok", "The Dethalbum", 2)
    album_tracks(library, "Dethklok", "Dethalbum II", 1)
    album_tracks(library, "2Pac", "Me Against the World", 1)
    album_tracks(library, "Émilie Simon", "Émilie Simon", 1)
    # A composer is stored as an artist but is not an album artist: not listed.
    make_track(
        library / "Other" / "Song",
        title="Song",
        artist="Band",
        albumartist="Band",
        album="Record",
        composer="Some Composer",
    )
    await run_scan(db)

    data = await get(client, user, "getArtists")
    artists = data["artists"]
    assert artists["ignoredArticles"] == "The El La Los Las Le Les"
    index = {i["name"]: [a["name"] for a in i["artist"]] for i in artists["index"]}
    assert index == {
        "#": ["2Pac"],
        "B": ["Band", "The Beatles"],  # "The" is ignored when sorting
        "D": ["Dethklok"],
        "E": ["Émilie Simon"],
    }
    assert [i["name"] for i in artists["index"]] == ["#", "B", "D", "E"]
    dethklok = next(a for i in artists["index"] for a in i["artist"] if a["name"] == "Dethklok")
    assert dethklok["albumCount"] == 2
    assert dethklok["sortName"] == "Dethklok"
    assert isinstance(dethklok["id"], str)


async def test_get_artists_by_music_folder(
    client: AsyncClient, db: Database, library: Path, user: SubsonicUser, tmp_path: Path
) -> None:
    album_tracks(library, "In First", "Album", 1)
    second = tmp_path / "second"
    album_tracks(second, "In Second", "Album", 1)
    async with db.session() as session:
        folder = await music_folders.create(session, "Second", second)
        await session.commit()
    await run_scan(db)

    def names(data: Any) -> list[str]:
        return [a["name"] for i in data["artists"]["index"] for a in i["artist"]]

    assert names(await get(client, user, "getArtists")) == ["In First", "In Second"]
    data = await get(client, user, "getArtists", musicFolderId=str(folder.id))
    assert names(data) == ["In Second"]
    data = await get(client, user, "getArtists", musicFolderId="9999")
    assert data["error"]["code"] == 70


async def test_get_artists_hides_missing(
    client: AsyncClient, db: Database, library: Path, user: SubsonicUser
) -> None:
    (track,) = album_tracks(library, "Gone", "Album", 1)
    album_tracks(library, "Stays", "Album", 1)
    await run_scan(db)
    track.unlink()
    await run_scan(db)
    index = (await get(client, user, "getArtists"))["artists"]["index"]
    assert [a["name"] for i in index for a in i["artist"]] == ["Stays"]
