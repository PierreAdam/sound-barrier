"""Song lyrics: .lrc files, tags, LRCLIB (replaced by a fake transport)."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.db import Database
from app.models import ServerSetting, Song
from app.scanner.scanner import run_scan
from app.services import server_settings
from tests.audio import make_track
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration

SYNCED = "[00:01.00]Hello\n[00:02.50]World"


class FakeLrclib:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        title = request.url.params.get("track_name")
        if request.url.path == "/api/get" and title == "Tagged":
            return httpx.Response(200, json={"syncedLyrics": SYNCED, "plainLyrics": "Hello"})
        if request.url.path == "/api/search" and title == "Searched":
            results: list[dict[str, Any]] = [
                {"duration": 500, "syncedLyrics": "[00:01.00]Too long"},
                {"duration": 1, "plainLyrics": "Plain words"},
            ]
            return httpx.Response(200, json=results)
        return httpx.Response(404, json={"message": "not found"})


@pytest.fixture
async def lrclib(app: FastAPI, db: Database) -> AsyncIterator[FakeLrclib]:
    fake = FakeLrclib()
    real = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    yield fake
    await app.state.http.aclose()
    app.state.http = real
    async with db.session() as session:
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.EXTERNAL_SERVICES_KEY)
        )
        await session.commit()


@pytest.fixture
async def songs(db: Database, library: Path) -> dict[str, str]:
    album = library / "Band" / "Album"
    common = {"artist": "Band", "albumartist": "Band", "album": "Album"}
    make_track(album / "01", fmt="flac", title="Tagged", lyrics="Plain from tags", **common)
    make_track(album / "02", title="With File", **common)
    (album / "02.lrc").write_text("[00:03.00]From the file", "utf-8")
    make_track(album / "03", title="Searched", **common)
    make_track(album / "04", title="Nothing", **common)
    await run_scan(db)
    async with db.session() as session:
        rows = (await session.execute(select(Song.title, Song.id))).all()
    return {title: str(song_id) for title, song_id in rows}


async def test_lyrics_sources(
    app: FastAPI, user: SubsonicUser, admin: SubsonicUser, lrclib: FakeLrclib, songs: dict[str, str]
) -> None:
    async with signed_in(app, user) as web:

        async def get(title: str) -> dict[str, Any]:
            return (await web.get(f"/api/songs/{songs[title]}/lyrics")).json()

        # Synced online lyrics win over plain ones from the tags.
        tagged = await get("Tagged")
        assert (tagged["source"], tagged["synced"]) == ("lrclib", True)
        assert tagged["lines"] == [
            {"startMs": 1000, "text": "Hello", "words": None},
            {"startMs": 2500, "text": "World", "words": None},
        ]
        # A synced .lrc: nothing asked online.
        before = len(lrclib.requests)
        with_file = await get("With File")
        assert (with_file["source"], with_file["lines"]) == (
            "lrc",
            [{"startMs": 3000, "text": "From the file", "words": None}],
        )
        assert len(lrclib.requests) == before
        # Found by the search, only with about the song's duration.
        searched = await get("Searched")
        assert (searched["source"], searched["synced"], searched["lines"][0]["text"]) == (
            "lrclib",
            False,
            "Plain words",
        )
        # Nothing anywhere, and remembered.
        assert (await get("Nothing"))["found"] is False
        before = len(lrclib.requests)
        assert (await get("Nothing"))["found"] is False
        assert len(lrclib.requests) == before

    async with signed_in(app, admin) as web:
        await web.put("/api/external/settings", json={"lrclib": False})
        tagged = (await web.get(f"/api/songs/{songs['Tagged']}/lyrics")).json()
    assert (tagged["source"], tagged["synced"], tagged["lines"][0]["text"]) == (
        "embedded",
        False,
        "Plain from tags",
    )


async def test_subsonic_lyrics(
    client: AsyncClient, user: SubsonicUser, lrclib: FakeLrclib, songs: dict[str, str]
) -> None:
    response = await client.get(
        "/rest/getLyricsBySongId", params=user.params(id=songs["With File"])
    )
    [structured] = response.json()["subsonic-response"]["lyricsList"]["structuredLyrics"]
    assert (structured["synced"], structured["displayTitle"]) == (True, "With File")
    assert structured["line"] == [{"start": 3000, "value": "From the file"}]

    response = await client.get(
        "/rest/getLyrics", params=user.params(artist="band", title="with file")
    )
    lyrics = response.json()["subsonic-response"]["lyrics"]
    assert (lyrics["artist"], lyrics["value"]) == ("Band", "From the file")

    extensions = (await client.get("/rest/getOpenSubsonicExtensions", params=user.params())).json()
    names = [e["name"] for e in extensions["subsonic-response"]["openSubsonicExtensions"]]
    assert "songLyrics" in names


async def test_lrclib_down(
    app: FastAPI, user: SubsonicUser, lrclib: FakeLrclib, songs: dict[str, str]
) -> None:
    async def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(down))
    async with signed_in(app, user) as web:
        nothing = (await web.get(f"/api/songs/{songs['Nothing']}/lyrics")).json()
        assert (nothing["found"], nothing["unavailable"]) == (False, True)  # not "none"
        # The file's own lyrics still show.
        tagged = (await web.get(f"/api/songs/{songs['Tagged']}/lyrics")).json()
        assert (tagged["source"], tagged["unavailable"]) == ("embedded", False)
    # Up again: asked again (nothing was remembered).
    await app.state.http.aclose()
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(lrclib.handle))
    async with signed_in(app, user) as web:
        found = (await web.get(f"/api/songs/{songs['Tagged']}/lyrics")).json()
    assert found["source"] == "lrclib"
