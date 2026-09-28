"""Album covers chosen by admins, with Deezer replaced by a fake transport."""

import io
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app.core.db import Database
from app.models import Album
from app.scanner.scanner import run_scan
from app.scanner.tags import extract_picture
from tests.audio import COVER_JPG, album_tracks
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration

BIG = "https://cdn-images.dzcdn.net/images/cover/abc/1000x1000.jpg"
SMALL = "https://cdn-images.dzcdn.net/images/cover/abc/250x250.jpg"
GROUP = "5b11f4ce-a62d-471e-81fc-a69a8278c7da"
FANART_COVER = "https://assets.fanart.tv/fanart/music/x/albumcover/cover.jpg"


def _png() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 20, 20)).save(output, format="PNG")
    return output.getvalue()


def fake_deezer(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.deezer.com":
        album: dict[str, Any] = {
            "title": "The Dethalbum",
            "artist": {"name": "Dethklok"},
            "cover_xl": BIG,
            "cover_medium": SMALL,
            "link": "https://www.deezer.com/album/1",
        }
        placeholder = {
            **album,
            "cover_xl": "https://cdn-images.dzcdn.net/images/cover//1000x1000.jpg",
        }
        return httpx.Response(200, json={"data": [album, placeholder]})
    if request.url.host == "webservice.fanart.tv":
        if request.url.params.get("api_key") != "fanart-key":
            return httpx.Response(401)
        covers = {"albums": {GROUP: {"albumcover": [{"url": FANART_COVER, "likes": "3"}]}}}
        return httpx.Response(200, json={"name": "Dethklok", **covers})
    if str(request.url) in (
        BIG,
        SMALL,
        FANART_COVER,
        FANART_COVER.replace("/fanart/", "/preview/"),
    ):
        return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})
    return httpx.Response(404)


@pytest.fixture
async def deezer(app: FastAPI) -> AsyncIterator[None]:
    real = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(fake_deezer))
    yield
    await app.state.http.aclose()
    app.state.http = real


@pytest.fixture
async def album(db: Database, library: Path) -> tuple[str, Path]:
    album_tracks(library, "Dethklok", "The Dethalbum", 2)
    folder = library / "Dethklok" / "The Dethalbum"
    (folder / "cover.jpg").write_bytes(COVER_JPG.read_bytes())
    await run_scan(db)
    async with db.session() as session:
        album_id = await session.scalar(select(Album.id).where(Album.name == "The Dethalbum"))
    return str(album_id), folder


async def test_search_and_set_a_cover(
    app: FastAPI,
    admin: SubsonicUser,
    client: AsyncClient,
    deezer: None,
    album: tuple[str, Path],
) -> None:
    album_id, folder = album
    async with signed_in(app, admin) as web:
        found = (await web.get(f"/api/albums/{album_id}/cover-search")).json()
        assert found["query"] == "Dethklok The Dethalbum"  # artist + album by default
        assert [r["imageUrl"] for r in found["results"]] == [BIG]  # no placeholder
        result = found["results"][0]
        assert (result["sourceLabel"], result["width"]) == ("Deezer", 1000)

        thumbnail = await web.get(result["thumbnailUrl"])
        assert thumbnail.headers["content-type"] == "image/png"
        # Only images of the cover sources: the server fetches nothing else.
        for url in ("https://example.com/x.jpg", "http://cdn-images.dzcdn.net/x.jpg"):
            assert (await web.get("/api/covers/thumbnail", params={"url": url})).status_code == 400

        # Browsers revalidate covers: the old one first.
        cover = await client.get("/rest/getCoverArt", params=admin.params(id=album_id))
        assert cover.content == COVER_JPG.read_bytes()
        etag = cover.headers["etag"]
        unchanged = await client.get(
            "/rest/getCoverArt", params=admin.params(id=album_id), headers={"If-None-Match": etag}
        )
        assert unchanged.status_code == 304

        applied = await web.post(
            f"/api/albums/{album_id}/cover", json={"imageUrl": BIG, "embed": True}
        )
        assert applied.status_code == 200, applied.text
        assert applied.json()["folders"] == ["Dethklok/The Dethalbum"]

    # cover.jpg (converted to JPEG), the previous one kept aside.
    with Image.open(folder / "cover.jpg") as image:
        assert (image.format, image.size) == ("JPEG", (40, 40))
    assert (folder / "cover.previous.jpg").read_bytes() == COVER_JPG.read_bytes()
    # Also inside the audio files.
    assert applied.json()["embedded"] == 2
    for song in sorted(folder.glob("*.mp3")):
        picture = extract_picture(song)
        assert picture is not None
        with Image.open(io.BytesIO(picture[0])) as embedded:
            assert max(embedded.size) <= 600
    # The same cover id, a new image: served at once, not the cached one.
    changed = await client.get(
        "/rest/getCoverArt", params=admin.params(id=album_id), headers={"If-None-Match": etag}
    )
    assert changed.status_code == 200
    assert changed.content == (folder / "cover.jpg").read_bytes()


async def test_covers_are_for_admins(
    app: FastAPI, user: SubsonicUser, deezer: None, album: tuple[str, Path]
) -> None:
    album_id, _ = album
    async with signed_in(app, user) as web:
        assert (await web.get(f"/api/albums/{album_id}/cover-search")).status_code == 403
        response = await web.post(f"/api/albums/{album_id}/cover", json={"imageUrl": BIG})
        assert response.status_code == 403


async def test_refuses_other_hosts(
    app: FastAPI, admin: SubsonicUser, deezer: None, album: tuple[str, Path]
) -> None:
    album_id, folder = album
    async with signed_in(app, admin) as web:
        response = await web.post(
            f"/api/albums/{album_id}/cover", json={"imageUrl": "https://example.com/cover.jpg"}
        )
    assert response.status_code == 400
    assert (folder / "cover.jpg").read_bytes() == COVER_JPG.read_bytes()


async def test_fanart_covers(
    app: FastAPI, admin: SubsonicUser, deezer: None, db: Database, library: Path
) -> None:
    album_tracks(library, "Dethklok", "Grouped", 1, musicbrainz_releasegroupid=GROUP)
    await run_scan(db)
    async with db.session() as session:
        album_id = await session.scalar(select(Album.id).where(Album.name == "Grouped"))
    async with signed_in(app, admin) as web:
        # Without a fanart.tv key: Deezer only.
        found = (await web.get(f"/api/albums/{album_id}/cover-search")).json()
        assert {r["source"] for r in found["results"]} == {"deezer"}
        await web.put("/api/external/settings", json={"fanartKey": "fanart-key"})
        found = (await web.get(f"/api/albums/{album_id}/cover-search")).json()
        fanart = [r for r in found["results"] if r["source"] == "fanarttv"]
        assert [r["imageUrl"] for r in fanart] == [FANART_COVER]
        assert (await web.get(fanart[0]["thumbnailUrl"])).status_code == 200
        await web.put("/api/external/settings", json={"fanartKey": ""})
