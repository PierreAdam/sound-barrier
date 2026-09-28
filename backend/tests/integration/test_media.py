import io
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image

from app.core.db import Database
from app.models import UserMusicFolder
from app.scanner.scanner import run_scan
from app.services import music_folders, users
from tests.audio import COVER_JPG, album_tracks, make_track
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def get(client: AsyncClient, user: SubsonicUser, method: str, **params: str) -> Any:
    response = await client.get(f"/rest/{method}", params=user.params(**params))
    return response.json()["subsonic-response"]


def write_cover(path: Path, size: int = 600) -> None:
    Image.new("RGB", (size, size), "red").save(path, format="JPEG")


@pytest.fixture
async def dethklok(db: Database, library: Path) -> Path:
    album_tracks(library, "Dethklok", "The Dethalbum", 3, date="2007", genre="Metal")
    album_tracks(library, "Dethklok", "Dethalbum II", 2, date="2009")
    write_cover(library / "Dethklok" / "The Dethalbum" / "cover.jpg")
    await run_scan(db)
    return library


async def artist_id(client: AsyncClient, user: SubsonicUser, name: str) -> str:
    data = await get(client, user, "getArtists")
    return next(a["id"] for i in data["artists"]["index"] for a in i["artist"] if a["name"] == name)


async def test_artist_album_song(client: AsyncClient, dethklok: Path, user: SubsonicUser) -> None:
    artist = (await get(client, user, "getArtist", id=await artist_id(client, user, "Dethklok")))[
        "artist"
    ]
    assert artist["name"] == "Dethklok"
    assert [a["name"] for a in artist["album"]] == ["The Dethalbum", "Dethalbum II"]  # by year
    first = artist["album"][0]
    assert (first["songCount"], first["year"], first["genre"]) == (3, 2007, "Metal")
    assert first["artists"] == [{"id": artist["id"], "name": "Dethklok"}]
    assert first["coverArt"]

    album = (await get(client, user, "getAlbum", id=first["id"]))["album"]
    assert [s["title"] for s in album["song"]] == ["Track 1", "Track 2", "Track 3"]
    song = album["song"][0]
    assert song["albumId"] == first["id"]
    assert song["coverArt"] == first["coverArt"]  # album cover shared by its songs
    assert (song["suffix"], song["contentType"], song["isDir"]) == ("mp3", "audio/mpeg", False)
    assert song["duration"] >= 1
    assert song["path"] == "Dethklok/The Dethalbum/01 - Track 1.mp3"

    assert (await get(client, user, "getSong", id=song["id"]))["song"]["title"] == "Track 1"


@pytest.mark.parametrize("method", ["getArtist", "getAlbum", "getSong"])
async def test_not_found(
    client: AsyncClient, dethklok: Path, user: SubsonicUser, method: str
) -> None:
    for bad_id in ("not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        assert (await get(client, user, method, id=bad_id))["error"]["code"] == 70
    assert (await get(client, user, method))["error"]["code"] == 10


async def first_song(client: AsyncClient, user: SubsonicUser) -> dict[str, Any]:
    artist = await get(client, user, "getArtist", id=await artist_id(client, user, "Dethklok"))
    album = await get(client, user, "getAlbum", id=artist["artist"]["album"][0]["id"])
    return album["album"]["song"][0]


async def test_stream_supports_ranges(
    client: AsyncClient, dethklok: Path, user: SubsonicUser
) -> None:
    song = await first_song(client, user)
    file = dethklok / song["path"]

    response = await client.get("/rest/stream", params=user.params(id=song["id"]))
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.content == file.read_bytes()

    response = await client.get(
        "/rest/stream", params=user.params(id=song["id"]), headers={"Range": "bytes=100-199"}
    )
    assert response.status_code == 206
    assert response.content == file.read_bytes()[100:200]


async def test_download(client: AsyncClient, dethklok: Path, user: SubsonicUser) -> None:
    song = await first_song(client, user)
    response = await client.get("/rest/download", params=user.params(id=song["id"]))
    assert response.status_code == 200
    # RFC 5987 form for names with spaces: filename*=utf-8''01%20-%20Track%201.mp3
    assert "01 - Track 1.mp3" in unquote(response.headers["content-disposition"])


async def test_stream_missing_song(client: AsyncClient, dethklok: Path, user: SubsonicUser) -> None:
    response = await client.get("/rest/stream", params=user.params(id="nope"))
    assert response.json()["subsonic-response"]["error"]["code"] == 70


async def test_cover_art(client: AsyncClient, dethklok: Path, user: SubsonicUser) -> None:
    song = await first_song(client, user)

    original = await client.get("/rest/getCoverArt", params=user.params(id=song["coverArt"]))
    assert original.status_code == 200
    assert original.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(original.content)).size == (600, 600)

    resized = await client.get(
        "/rest/getCoverArt", params=user.params(id=song["coverArt"], size="120")
    )
    assert Image.open(io.BytesIO(resized.content)).size == (120, 120)
    cached = await client.get(
        "/rest/getCoverArt", params=user.params(id=song["coverArt"], size="120")
    )
    assert cached.content == resized.content

    # Clients may also ask by album, song or artist id.
    for other_id in (song["albumId"], song["id"], song["artistId"]):
        response = await client.get("/rest/getCoverArt", params=user.params(id=other_id))
        assert response.headers["content-type"] == "image/jpeg", other_id


async def test_embedded_cover_art(
    client: AsyncClient, db: Database, library: Path, user: SubsonicUser
) -> None:
    make_track(
        library / "A" / "B" / "01", title="x", artist="A", albumartist="A", album="B", picture=True
    )
    await run_scan(db)
    song = await first_song_of(client, user, "A")
    response = await client.get("/rest/getCoverArt", params=user.params(id=song["coverArt"]))
    assert response.content == COVER_JPG.read_bytes()


async def first_song_of(client: AsyncClient, user: SubsonicUser, artist: str) -> dict[str, Any]:
    data = await get(client, user, "getArtist", id=await artist_id(client, user, artist))
    album = await get(client, user, "getAlbum", id=data["artist"]["album"][0]["id"])
    return album["album"]["song"][0]


async def test_folder_restrictions(
    client: AsyncClient,
    app: FastAPI,
    db: Database,
    dethklok: Path,
    user: SubsonicUser,
    tmp_path: Path,
) -> None:
    song = await first_song(client, user)
    other = tmp_path / "other"
    other.mkdir()
    async with db.session() as session:
        folder = await music_folders.create(session, "Other", other)
        restricted = await users.create_user(session, app.state.cipher, "restricted", "pw")
        session.add(UserMusicFolder(user_id=restricted.id, music_folder_id=folder.id))
        await session.commit()
    restricted_user = SubsonicUser("restricted", "pw")

    for method in ("getSong", "stream", "getAlbum"):
        target = song["albumId"] if method == "getAlbum" else song["id"]
        response = await client.get(f"/rest/{method}", params=restricted_user.params(id=target))
        assert response.json()["subsonic-response"]["error"]["code"] == 70, method
