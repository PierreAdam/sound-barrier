"""Artist discographies ("Missing albums"): MusicBrainz, the Cover Art Archive and Deezer
replaced by a fake transport."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from app.core.db import Database
from app.external import musicbrainz
from app.models import Artist, ArtistInfo, ServerSetting
from app.scanner.scanner import run_scan
from app.services import server_settings
from tests.audio import COVER_JPG, album_tracks
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration

AMON = "d4f8c0a2-2c83-4a5e-9f3b-6b3b1f0c2a11"
DETHKLOK = "e7a6b5e0-4a8f-4e5b-9d7e-3d0b9c2a1f00"
TWILIGHT = "11111111-1111-4111-8111-111111111111"
JOMSVIKING = "22222222-2222-4222-8222-222222222222"
JOMSVIKING_RELEASE = "2a2a2a2a-2a2a-4a2a-8a2a-2a2a2a2a2a2a"
DECEIVER = "33333333-3333-4333-8333-333333333333"
VERSUS = "44444444-4444-4444-8444-444444444444"
LIVE = "55555555-5555-4555-8555-555555555555"
HYMNS = "66666666-6666-4666-8666-666666666666"
DEMO = "77777777-7777-4777-8777-777777777777"
NEXT = "88888888-8888-4888-8888-888888888888"
DETHALBUM = "99999999-9999-4999-8999-999999999999"
CAA_IMAGE = "https://coverartarchive.org/release/abc/1-500.jpg"
DEEZER_SMALL = "https://cdn-images.dzcdn.net/images/cover/versus/250x250.jpg"


def _group(mbid: str, title: str, date: str, primary: str, *secondary: str) -> dict[str, Any]:
    return {
        "id": mbid,
        "title": title,
        "first-release-date": date,
        "primary-type": primary,
        "secondary-types": list(secondary),
    }


AMON_GROUPS = [
    _group(LIVE, "Wrath of the Norsemen", "2006-06-12", "Album", "Live"),
    _group(VERSUS, "Versus the World", "2002-11-18", "Album"),
    _group(TWILIGHT, "Twilight of the Thunder God", "2008-09-17", "Album"),
    _group(JOMSVIKING, "Jomsviking", "2016-03-25", "Album"),
    _group(DECEIVER, "Deceiver of the Gods", "2013-06-21", "Album"),
    _group(HYMNS, "Hymns to the Rising Sun", "2010", "Album", "Compilation"),
    _group(DEMO, "The Arrival of the Fimbul Winter", "1994", "EP", "Demo"),
    _group(NEXT, "The Next One", "2999-01-01", "Album"),
]


def _artist(mbid: str, name: str, score: int = 100, **extra: Any) -> dict[str, Any]:
    return {"id": mbid, "name": name, "score": score, **extra}


class FakeServices:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url, params = request.url, request.url.params
        if url.host == "musicbrainz.org":
            return self._musicbrainz(url.path.removeprefix("/ws/2/"), params)
        if url.host == "coverartarchive.org" and url.path == f"/release-group/{VERSUS}":
            return httpx.Response(404)  # this one comes from Deezer
        if url.host == "coverartarchive.org" and url.path.startswith("/release-group/"):
            image = {"front": True, "image": CAA_IMAGE, "thumbnails": {"500": CAA_IMAGE}}
            return httpx.Response(200, json={"images": [image]})
        if url.host == "api.deezer.com":
            album = {
                "title": "Versus the World",
                "artist": {"name": "Amon Amarth"},
                "cover_xl": DEEZER_SMALL.replace("250x250", "1000x1000"),
                "cover_medium": DEEZER_SMALL,
            }
            other = {**album, "title": "Versus the World (Live)", "cover_medium": "x"}
            return httpx.Response(200, json={"data": [other, album]})
        if str(url) in (CAA_IMAGE, DEEZER_SMALL):
            return httpx.Response(
                200, content=COVER_JPG.read_bytes(), headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(404)

    def _musicbrainz(self, path: str, params: httpx.QueryParams) -> httpx.Response:
        if path == "release-group":
            assert params["release-group-status"] == "website-default"
            groups = {
                AMON: AMON_GROUPS,
                DETHKLOK: [_group(DETHALBUM, "The Dethalbum", "2007", "Album")],
            }
            found = groups.get(params["artist"])
            if found is None:
                return httpx.Response(404)
            return httpx.Response(
                200, json={"release-groups": found, "release-group-count": len(found)}
            )
        if path == f"release/{JOMSVIKING_RELEASE}":
            return httpx.Response(
                200, json={"id": JOMSVIKING_RELEASE, "release-group": {"id": JOMSVIKING}}
            )
        if path == "artist":
            query = params["query"]
            if "Dethklok" in query:
                return httpx.Response(
                    200,
                    json={
                        "artists": [
                            _artist(DETHKLOK, "Dethklok", disambiguation="Metalocalypse"),
                            _artist("00000000-0000-4000-8000-000000000001", "Dethklok Fans", 80),
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "artists": [
                        _artist(AMON, "Twin", country="SE"),
                        _artist("00000000-0000-4000-8000-000000000002", "Twin", country="US"),
                    ]
                },
            )
        if path == f"artist/{AMON}":
            return httpx.Response(200, json=_artist(AMON, "Amon Amarth"))
        return httpx.Response(404)

    def count(self, host: str, path: str = "") -> int:
        return sum(1 for r in self.requests if r.url.host == host and r.url.path.startswith(path))


@pytest.fixture
async def services(
    app: FastAPI, db: Database, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[FakeServices]:
    monkeypatch.setattr(musicbrainz.LIMITER, "interval", 0)
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
async def artists(db: Database, library: Path) -> dict[str, str]:
    ids = {"musicbrainz_artistid": AMON, "musicbrainz_albumartistid": AMON}
    album_tracks(
        library,
        "Amon Amarth",
        "Twilight of the Thunder God",
        1,
        musicbrainz_releasegroupid=TWILIGHT,
        **ids,
    )
    album_tracks(
        library, "Amon Amarth", "Jomsviking", 1, musicbrainz_albumid=JOMSVIKING_RELEASE, **ids
    )
    album_tracks(library, "Amon Amarth", "Deceiver of the Gods (Deluxe Edition)", 1, **ids)
    album_tracks(library, "Dethklok", "The Dethalbum", 1)
    album_tracks(library, "Twin", "First", 1)
    await run_scan(db)
    async with db.session() as session:
        rows = (await session.execute(select(Artist.name, Artist.id))).all()
    return {name: str(artist_id) for name, artist_id in rows}


async def test_discography_with_the_library(
    app: FastAPI, user: SubsonicUser, services: FakeServices, artists: dict[str, str]
) -> None:
    async with signed_in(app, user) as web:
        found = (await web.get(f"/api/artists/{artists['Amon Amarth']}/discography")).json()
    assert (found["artistMbid"], found["mbidSource"]) == (AMON, "tags")
    assert found["error"] is None
    # Categories in MusicBrainz order, with counts.
    assert [(c["key"], c["label"], c["total"], c["missing"]) for c in found["categories"]] == [
        ("album", "Album", 5, 2),
        ("album+compilation", "Album + Compilation", 1, 1),
        ("album+live", "Album + Live", 1, 1),
        ("ep+demo", "EP + Demo", 1, 1),
    ]
    groups = {g["mbid"]: g for g in found["releaseGroups"]}
    # Owned by release group id, by release id and by title (edition ignored).
    assert groups[TWILIGHT]["owned"]["name"] == "Twilight of the Thunder God"
    assert groups[JOMSVIKING]["owned"]["name"] == "Jomsviking"
    assert groups[DECEIVER]["owned"]["name"] == "Deceiver of the Gods (Deluxe Edition)"
    assert groups[VERSUS]["owned"] is None
    assert groups[LIVE]["owned"] is None
    assert (groups[NEXT]["upcoming"], groups[VERSUS]["upcoming"]) == (True, False)
    # Plain albums by date first.
    assert [g["title"] for g in found["releaseGroups"][:3]] == [
        "Versus the World",
        "Twilight of the Thunder God",
        "Deceiver of the Gods",
    ]

    # Cached: the next visit asks nobody.
    before = len(services.requests)
    async with signed_in(app, user) as web:
        await web.get(f"/api/artists/{artists['Amon Amarth']}/discography")
    assert len(services.requests) == before


async def test_artist_found_by_search_or_linked_by_an_admin(
    app: FastAPI,
    admin: SubsonicUser,
    user: SubsonicUser,
    services: FakeServices,
    artists: dict[str, str],
) -> None:
    async with signed_in(app, user) as web:
        # One exact result: linked automatically.
        found = (await web.get(f"/api/artists/{artists['Dethklok']}/discography")).json()
        assert (found["artistMbid"], found["mbidSource"]) == (DETHKLOK, "search")
        assert found["releaseGroups"][0]["owned"]["name"] == "The Dethalbum"
        # Two artists named "Twin": not linked.
        twin = artists["Twin"]
        found = (await web.get(f"/api/artists/{twin}/discography")).json()
        assert (found["artistMbid"], found["releaseGroups"]) == (None, [])
        # Only admins choose.
        assert (await web.get(f"/api/artists/{twin}/musicbrainz/candidates")).status_code == 403
        link = await web.put(f"/api/artists/{twin}/musicbrainz", json={"mbid": AMON})
        assert link.status_code == 403

    async with signed_in(app, admin) as web:
        candidates = (await web.get(f"/api/artists/{twin}/musicbrainz/candidates")).json()
        assert [(c["name"], c["country"]) for c in candidates] == [("Twin", "SE"), ("Twin", "US")]
        bad = await web.put(f"/api/artists/{twin}/musicbrainz", json={"mbid": "nope"})
        assert bad.status_code == 400
        unknown = await web.put(
            f"/api/artists/{twin}/musicbrainz",
            json={"mbid": "00000000-0000-4000-8000-00000000000f"},
        )
        assert unknown.status_code == 400
        # A musicbrainz.org URL works too.
        linked = await web.put(
            f"/api/artists/{twin}/musicbrainz",
            json={"mbid": f"https://musicbrainz.org/artist/{AMON}"},
        )
        assert linked.status_code == 200, linked.text
        assert (linked.json()["artistMbid"], linked.json()["mbidSource"]) == (AMON, "manual")
        assert len(linked.json()["releaseGroups"]) == len(AMON_GROUPS)
        # Unlinked: back to the search.
        cleared = (await web.put(f"/api/artists/{twin}/musicbrainz", json={"mbid": None})).json()
        assert cleared["artistMbid"] is None


async def test_covers_of_missing_albums(
    app: FastAPI, user: SubsonicUser, services: FakeServices, artists: dict[str, str]
) -> None:
    amon = artists["Amon Amarth"]
    async with signed_in(app, user) as web:
        await web.get(f"/api/artists/{amon}/discography")
        # Cover Art Archive first, then Deezer (same artist and title only).
        for group in (LIVE, VERSUS):
            response = await web.get(f"/api/artists/{amon}/discography/covers/{group}")
            assert response.status_code == 200, response.text
            assert response.content == COVER_JPG.read_bytes()
        assert services.count("cdn-images.dzcdn.net") == 1
        # Kept on disk.
        before = len(services.requests)
        again = await web.get(f"/api/artists/{amon}/discography/covers/{LIVE}")
        assert again.status_code == 200
        assert len(services.requests) == before
        # Only release groups of this artist.
        other = await web.get(f"/api/artists/{artists['Dethklok']}/discography/covers/{LIVE}")
        assert other.status_code == 404
        assert (
            await web.get(f"/api/artists/{amon}/discography/covers/not-an-id")
        ).status_code == 404


async def test_musicbrainz_can_be_turned_off(
    app: FastAPI,
    admin: SubsonicUser,
    services: FakeServices,
    artists: dict[str, str],
) -> None:
    async with signed_in(app, admin) as web:
        saved = await web.put("/api/external/settings", json={"musicbrainz": False})
        assert saved.json()["musicbrainz"] is False
        found = (await web.get(f"/api/artists/{artists['Amon Amarth']}/discography")).json()
    assert found["enabled"] is False
    assert services.count("musicbrainz.org") == 0


async def test_information_and_discography_at_the_same_time(
    app: FastAPI, user: SubsonicUser, services: FakeServices, artists: dict[str, str]
) -> None:
    # The artist page asks for both at once: both create the artist's cache row.
    amon = artists["Amon Amarth"]
    async with signed_in(app, user) as web:
        responses = await asyncio.gather(
            web.get(f"/api/artists/{amon}/info"), web.get(f"/api/artists/{amon}/discography")
        )
    assert [r.status_code for r in responses] == [200, 200]
