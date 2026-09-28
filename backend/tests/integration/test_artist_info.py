"""Artist information: Last.fm (biography, similar artists, top songs) and Deezer
(picture), with both services replaced by a fake transport."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.db import Database
from app.models import Artist, ArtistInfo, ServerSetting
from app.scanner.scanner import run_scan
from app.services import server_settings
from tests.audio import COVER_JPG, album_tracks, make_track
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration

GOOD_KEY = "0123456789abcdef"
PICTURE_URL = "https://cdn.deezer.test/images/artist/abc/1000x1000.jpg"
FANART_KEY = "fanart-key"
DETHKLOK_MBID = "e7a6b5e0-4a8f-4e5b-9d7e-3d0b9c2a1f00"
FANART_THUMB = "https://assets.fanart.tv/fanart/music/dethklok/artistthumb/best.jpg"


class FakeServices:
    """Last.fm and Deezer, as far as Sound-Barrier uses them."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        params = request.url.params
        if request.url.host == "ws.audioscrobbler.com":
            if params["api_key"] != GOOD_KEY:
                return httpx.Response(403, json={"error": 10, "message": "Invalid API key"})
            if params.get("artist", "").lower() not in ("dethklok", "radiohead"):
                return httpx.Response(200, json={"error": 6, "message": "not found"})
            if params["method"] == "artist.getInfo":
                return httpx.Response(200, json=_lastfm_info())
            return httpx.Response(200, json=_lastfm_top_tracks())
        if request.url.host == "api.deezer.com":
            return httpx.Response(200, json=_deezer_search(params["q"]))
        if request.url.host == "webservice.fanart.tv":
            if params.get("api_key") != FANART_KEY:
                return httpx.Response(
                    401, json={"status": "error", "error message": "Invalid API key"}
                )
            if request.url.path.endswith(DETHKLOK_MBID):
                thumbs = [
                    {"url": FANART_THUMB.replace("best", "other"), "likes": "1"},
                    {"url": FANART_THUMB, "likes": "9"},
                ]
                return httpx.Response(200, json={"name": "Dethklok", "artistthumb": thumbs})
            return httpx.Response(200, json={"name": "Radiohead"})
        if str(request.url) == FANART_THUMB:
            return httpx.Response(
                200, content=COVER_JPG.read_bytes(), headers={"content-type": "image/jpeg"}
            )
        if str(request.url) == PICTURE_URL:
            return httpx.Response(
                200, content=COVER_JPG.read_bytes(), headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(404)

    def count(self, host: str) -> int:
        return sum(1 for r in self.requests if r.url.host == host)


def _lastfm_info() -> dict[str, Any]:
    return {
        "artist": {
            "name": "Dethklok",
            "url": "https://www.last.fm/music/Dethklok",
            "bio": {
                "summary": "The <b>heaviest</b> band. "
                '<a href="https://www.last.fm/music/Dethklok">Read more on Last.fm</a>',
                "content": "The heaviest band in the world &amp; beyond.",
            },
            "similar": {"artist": [{"name": "Deaf Election"}, {"name": "Unknown Band"}]},
            "tags": {"tag": [{"name": "metal"}]},
        }
    }


def _lastfm_top_tracks() -> dict[str, Any]:
    tracks = ["Not In The Library", "Go Into the Water (Live)", "Murmaider"]
    return {"toptracks": {"track": [{"name": t, "playcount": "100"} for t in tracks]}}


def _deezer_search(query: str) -> dict[str, Any]:
    if query.lower() != "dethklok":
        return {"data": [{"name": "Somebody Else", "picture_xl": PICTURE_URL}]}
    return {
        "data": [
            {
                "name": "Dethklok",
                "picture_xl": PICTURE_URL,
                "link": "https://www.deezer.com/artist/1",
            }
        ]
    }


@pytest.fixture
async def services(app: FastAPI, db: Database) -> AsyncIterator[FakeServices]:
    fake = FakeServices()
    real = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    yield fake
    await app.state.http.aclose()
    app.state.http = real
    async with db.session() as session:
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.EXTERNAL_SERVICES_KEY)
        )
        await session.execute(delete(ArtistInfo))
        await session.commit()


@pytest.fixture
async def dethklok(db: Database, library: Path) -> str:
    album_tracks(library, "Deaf Election", "Falling in Flames", 1)
    for n, title in enumerate(("Murmaider", "Go into the Water"), start=1):
        make_track(
            library / "Dethklok" / "The Dethalbum" / f"0{n} - {title}",
            title=title,
            artist="Dethklok",
            albumartist="Dethklok",
            album="The Dethalbum",
            tracknumber=f"{n}/2",
        )
    await run_scan(db)
    async with db.session() as session:
        return str(await session.scalar(select(Artist.id).where(Artist.name == "Dethklok")))


async def test_settings_keep_the_key_secret(
    app: FastAPI, admin: SubsonicUser, user: SubsonicUser, services: FakeServices
) -> None:
    async with signed_in(app, admin) as client:
        initial = (await client.get("/api/external/settings")).json()
        assert (initial["lastfmKeySet"], initial["pictureSource"]) == (False, "deezer")
        assert [s["id"] for s in initial["pictureSources"]] == ["none", "deezer", "fanarttv"]

        refused = await client.put("/api/external/settings", json={"lastfmKey": "wrong"})
        assert refused.status_code == 400
        saved = await client.put("/api/external/settings", json={"lastfmKey": GOOD_KEY})
        assert saved.json()["lastfmKeySet"] is True
        assert GOOD_KEY not in saved.text
        # Changing the picture source keeps the key.
        kept = await client.put("/api/external/settings", json={"pictureSource": "none"})
        assert (kept.json()["lastfmKeySet"], kept.json()["pictureSource"]) == (True, "none")
        removed = await client.put("/api/external/settings", json={"lastfmKey": ""})
        assert removed.json()["lastfmKeySet"] is False
    async with signed_in(app, user) as client:
        assert (await client.get("/api/external/settings")).status_code == 403


async def test_artist_info_and_picture(
    app: FastAPI,
    admin: SubsonicUser,
    user: SubsonicUser,
    client: AsyncClient,
    services: FakeServices,
    dethklok: str,
) -> None:
    async with signed_in(app, user) as web:
        # No Last.fm key yet: only the picture (Deezer needs no key).
        info = (await web.get(f"/api/artists/{dethklok}/info")).json()
        assert info["lastfmConfigured"] is False
        assert services.count("ws.audioscrobbler.com") == 0
        assert info["picture"]["source"] == "Deezer"
        assert info["picture"]["pageUrl"] == "https://www.deezer.com/artist/1"

    async with signed_in(app, admin) as web:
        await web.put("/api/external/settings", json={"lastfmKey": GOOD_KEY})
    async with signed_in(app, user) as web:
        info = (await web.get(f"/api/artists/{dethklok}/info")).json()
        assert info["summary"] == "The heaviest band."  # HTML and the Last.fm link removed
        assert info["biography"] == "The heaviest band in the world & beyond."
        assert info["lastfmUrl"] == "https://www.last.fm/music/Dethklok"
        similar = {s["name"]: s["id"] for s in info["similar"]}
        assert similar["Deaf Election"] is not None and similar["Unknown Band"] is None
        # Top tracks of the library only, in Last.fm's order ("(Live)" is ignored).
        assert [s["title"] for s in info["topSongs"]] == ["Go into the Water", "Murmaider"]
        assert info["error"] is None

        # Cached: the next visit asks nobody.
        before = len(services.requests)
        again = (await web.get(f"/api/artists/{dethklok}/info")).json()
        assert again["topSongs"] == info["topSongs"]
        assert len(services.requests) == before

    # The picture is served by getCoverArt, for the artist id or the versioned id.
    for cover_id in (dethklok, info["picture"]["coverArt"]):
        response = await client.get("/rest/getCoverArt", params=user.params(id=cover_id))
        assert response.content == COVER_JPG.read_bytes()

    # Subsonic clients get the same information.
    data = (await client.get("/rest/getArtistInfo2", params=user.params(id=dethklok))).json()
    artist_info = data["subsonic-response"]["artistInfo2"]
    assert artist_info["lastFmUrl"] == "https://www.last.fm/music/Dethklok"
    assert [a["name"] for a in artist_info["similarArtist"]] == ["Deaf Election"]
    data = (
        await client.get("/rest/getTopSongs", params=user.params(artist="dethklok", count="1"))
    ).json()
    assert [s["title"] for s in data["subsonic-response"]["topSongs"]["song"]] == [
        "Go into the Water"
    ]


async def test_no_picture_source(
    app: FastAPI, admin: SubsonicUser, user: SubsonicUser, services: FakeServices, dethklok: str
) -> None:
    async with signed_in(app, admin) as web:
        await web.put("/api/external/settings", json={"pictureSource": "none"})
        info = (await web.get(f"/api/artists/{dethklok}/info")).json()
    assert info["picture"] is None
    assert services.count("api.deezer.com") == 0
    assert json.dumps(info).count("Deezer") == 0


async def test_fanart_pictures(
    app: FastAPI, admin: SubsonicUser, services: FakeServices, db: Database, library: Path
) -> None:
    make_track(
        library / "Dethklok" / "Album" / "01 - Song",
        title="Song",
        artist="Dethklok",
        albumartist="Dethklok",
        album="Album",
        musicbrainz_artistid=DETHKLOK_MBID,
        musicbrainz_albumartistid=DETHKLOK_MBID,
    )
    await run_scan(db)
    async with db.session() as session:
        artist_id = str(await session.scalar(select(Artist.id).where(Artist.name == "Dethklok")))
    async with signed_in(app, admin) as web:
        needs_key = await web.put("/api/external/settings", json={"pictureSource": "fanarttv"})
        assert needs_key.status_code == 400  # no key yet
        assert (
            await web.put("/api/external/settings", json={"fanartKey": "wrong"})
        ).status_code == 400
        saved = await web.put(
            "/api/external/settings", json={"fanartKey": FANART_KEY, "pictureSource": "fanarttv"}
        )
        assert (saved.json()["fanartKeySet"], saved.json()["pictureSource"]) == (True, "fanarttv")
        assert FANART_KEY not in saved.text

        info = (await web.get(f"/api/artists/{artist_id}/info")).json()
    assert info["picture"]["source"] == "fanart.tv"
    assert info["picture"]["pageUrl"] == f"https://fanart.tv/artist/{DETHKLOK_MBID}"
    downloads = [str(r.url) for r in services.requests if r.url.host == "assets.fanart.tv"]
    assert downloads == [FANART_THUMB]  # the most liked one
