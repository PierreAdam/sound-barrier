"""Podcasts and audiobooks: their own folders and switches, kept apart from music, served
to Subsonic apps as podcasts, imported as they are, resumed with bookmarks."""

import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.db import Database
from app.models import ServerSetting
from app.services import server_settings
from tests.audio import album_tracks, make_track
from tests.integration.conftest import SubsonicUser, signed_in
from tests.integration.test_manage import wait_scans

pytestmark = pytest.mark.integration


async def _call(
    client: AsyncClient, user: SubsonicUser, endpoint: str, **params: str
) -> dict[str, Any]:
    response = await client.get(f"/rest/{endpoint}", params=user.params(**params))
    return response.json()["subsonic-response"]


@pytest.fixture
async def spoken(
    app: FastAPI, db: Database, admin: SubsonicUser, library: Path, tmp_path: Path
) -> AsyncIterator[dict[str, Path]]:
    """A music album, a podcast show (2 episodes) and an audiobook (2 chapters), both on."""
    album_tracks(library, "A Band", "Some Songs", 1)
    podcasts, audiobooks = tmp_path / "podcasts", tmp_path / "audiobooks"
    now = time.time()
    for n, age in ((1, 3600), (2, 0)):  # the newest episode is the most recent file
        path = make_track(
            podcasts / "The Show" / f"episode {n}",
            title=f"Episode {n}",
            album="The Show",
            artist="Host",
        )
        os.utime(path, (now - age, now - age))
    for n in (2, 1):  # written in reverse: the order comes from the track numbers
        make_track(
            audiobooks / "An Author" / "A Book" / f"0{n}",
            title=f"Chapter {n}",
            album="A Book",
            artist="An Author",
            albumartist="An Author",
            tracknumber=f"{n}/2",
        )
    async with signed_in(app, admin) as web:
        for kind, path in (("podcasts", podcasts), ("audiobooks", audiobooks)):
            response = await web.put(
                f"/api/library/spoken/{kind}", json={"enabled": True, "path": str(path)}
            )
            assert response.status_code == 200, response.text
    await wait_scans(app)
    yield {"podcasts": podcasts, "audiobooks": audiobooks, "music": library}
    async with db.session() as session:
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.SPOKEN_KEY)
        )
        await session.commit()


async def test_music_stays_music(
    client: AsyncClient, user: SubsonicUser, spoken: dict[str, Path]
) -> None:
    albums = (await _call(client, user, "getAlbumList2", type="alphabeticalByName"))["albumList2"][
        "album"
    ]
    assert [a["name"] for a in albums] == ["Some Songs"]
    folders = (await _call(client, user, "getMusicFolders"))["musicFolders"]["musicFolder"]
    assert [f["name"] for f in folders] == ["Music"]
    found = (await _call(client, user, "search3", query="chapter"))["searchResult3"]
    assert found.get("song", []) == []
    index = (await _call(client, user, "getArtists"))["artists"]["index"]
    assert [a["name"] for i in index for a in i["artist"]] == ["A Band"]


async def test_podcast_api(
    client: AsyncClient, user: SubsonicUser, spoken: dict[str, Path]
) -> None:
    channels = (await _call(client, user, "getPodcasts"))["podcasts"]["channel"]
    by_title = {c["title"]: c for c in channels}
    assert set(by_title) == {"The Show", "A Book"}
    show, book = by_title["The Show"], by_title["A Book"]
    assert book["description"] == "Audiobook · An Author"
    assert [e["title"] for e in book["episode"]] == ["Chapter 1", "Chapter 2"]  # in order
    assert [e["title"] for e in show["episode"]] == ["Episode 2", "Episode 1"]  # newest first
    episode = show["episode"][0]
    assert (episode["streamId"], episode["channelId"], episode["status"]) == (
        episode["id"],
        show["id"],
        "completed",
    )
    assert (episode["mediaType"], book["episode"][0]["mediaType"]) == ("podcast", "audiobook")

    only = (await _call(client, user, "getPodcasts", id=book["id"], includeEpisodes="false"))[
        "podcasts"
    ]["channel"]
    assert [(c["title"], c.get("episode", [])) for c in only] == [("A Book", [])]
    newest = (await _call(client, user, "getNewestPodcasts", count="1"))["newestPodcasts"]
    assert [e["title"] for e in newest["episode"]] == ["Episode 2"]
    one = (await _call(client, user, "getPodcastEpisode", id=episode["id"]))["podcastEpisode"]
    assert one["channelId"] == show["id"]
    # Local files only: no RSS subscriptions.
    refused = await _call(client, user, "createPodcastChannel", url="https://example.com/feed")
    assert refused["status"] == "failed"
    # Episodes play like songs.
    stream = await client.get("/rest/stream", params=user.params(id=episode["streamId"]))
    assert stream.status_code == 200


async def test_switches_hide_a_kind(
    app: FastAPI,
    client: AsyncClient,
    admin: SubsonicUser,
    user: SubsonicUser,
    spoken: dict[str, Path],
) -> None:
    async with signed_in(app, user) as web:
        sections = (await web.get("/api/library/sections")).json()
        assert sections == {"podcasts": True, "audiobooks": True}
    async with signed_in(app, admin) as web:
        await web.put("/api/library/spoken/podcasts", json={"enabled": False})
        folders = (await web.get("/api/library/spoken")).json()
        assert (folders["podcasts"]["enabled"], folders["podcasts"]["folder"]["name"]) == (
            False,
            "Podcasts",
        )
    async with signed_in(app, user) as web:
        sections = (await web.get("/api/library/sections")).json()
        assert sections == {"podcasts": False, "audiobooks": True}
        assert (await web.get("/api/spoken/podcasts")).status_code == 404
    channels = (await _call(client, user, "getPodcasts"))["podcasts"]["channel"]
    assert [c["title"] for c in channels] == ["A Book"]


async def test_bookmarks_and_pages(
    app: FastAPI,
    client: AsyncClient,
    user: SubsonicUser,
    admin: SubsonicUser,
    spoken: dict[str, Path],
) -> None:
    async with signed_in(app, user) as web:
        page = (await web.get("/api/spoken/audiobooks")).json()
        [book] = page["shows"]
        assert (book["title"], book["author"], book["episodes"]) == ("A Book", "An Author", 2)
        assert page["continueListening"] == []
        detail = (await web.get(f"/api/spoken/shows/{book['id']}")).json()
        chapter_2 = detail["episodes"][1]
        assert chapter_2["title"] == "Chapter 2"

    created = await _call(client, user, "createBookmark", id=chapter_2["id"], position="65000")
    assert created["status"] == "ok"
    await _call(client, user, "createBookmark", id=chapter_2["id"], position="70000")  # moved
    [mark] = (await _call(client, user, "getBookmarks"))["bookmarks"]["bookmark"]
    assert (mark["position"], mark["entry"]["id"]) == (70000, chapter_2["id"])
    others = (await _call(client, admin, "getBookmarks"))["bookmarks"]
    assert others.get("bookmark", []) == []  # per user

    async with signed_in(app, user) as web:
        page = (await web.get("/api/spoken/audiobooks")).json()
        [resume] = page["continueListening"]
        assert (resume["show"]["title"], resume["episode"]["bookmarkPosition"]) == (
            "A Book",
            70000,
        )
        assert page["shows"][0]["started"] == 1

    unknown = "00000000-0000-4000-8000-000000000000"
    missing = await _call(client, user, "createBookmark", id=unknown, position="1")
    assert missing["error"]["code"] == 70
    await _call(client, user, "deleteBookmark", id=chapter_2["id"])
    remaining = (await _call(client, user, "getBookmarks"))["bookmarks"]
    assert remaining.get("bookmark", []) == []


async def test_chapters_dismiss_and_delete(
    app: FastAPI,
    client: AsyncClient,
    user: SubsonicUser,
    admin: SubsonicUser,
    spoken: dict[str, Path],
) -> None:
    from mutagen.id3 import CHAP, ID3, TIT2

    # A book in one file, with chapters inside it.
    path = make_track(
        spoken["audiobooks"] / "An Author" / "One File" / "book",
        title="One File",
        album="One File",
        artist="An Author",
    )
    tags = ID3(path)
    for element, start, title in [("c1", 0, "Opening"), ("c2", 500, "Ending")]:
        tags.add(
            CHAP(
                element_id=element,
                start_time=start,
                end_time=start + 400,
                sub_frames=[TIT2(encoding=3, text=[title])],
            )
        )
    tags.save(path)
    async with signed_in(app, admin) as web:
        await web.post("/api/scan", json={"full": False})
    await wait_scans(app)

    async with signed_in(app, user) as web:
        shows = {s["title"]: s for s in (await web.get("/api/spoken/audiobooks")).json()["shows"]}
        one_file = (await web.get(f"/api/spoken/shows/{shows['One File']['id']}")).json()
        [file] = one_file["episodes"]
        assert file["chapters"] == [
            {"startMs": 0, "title": "Opening"},
            {"startMs": 500, "title": "Ending"},
        ]
        book = (await web.get(f"/api/spoken/shows/{shows['A Book']['id']}")).json()
        assert all("chapters" not in e for e in book["episodes"])  # files without chapters

        # Dismissed: every bookmark of the book goes, it leaves "Continue listening".
        for episode in book["episodes"]:
            await _call(client, user, "createBookmark", id=episode["id"], position="6000")
        page = (await web.get("/api/spoken/audiobooks")).json()
        assert [r["show"]["title"] for r in page["continueListening"]] == ["A Book"]
        response = await web.delete(f"/api/spoken/shows/{shows['A Book']['id']}/bookmarks")
        assert response.status_code == 204
        page = (await web.get("/api/spoken/audiobooks")).json()
        assert page["continueListening"] == []
        assert (await _call(client, user, "getBookmarks"))["bookmarks"].get("bookmark", []) == []

    # Deleting a whole audiobook: its files and its entry go.
    async with signed_in(app, admin) as web:
        response = await web.post(
            "/api/manage/delete", json={"albumIds": [shows["One File"]["id"]]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["filesDeleted"] == 1
        await wait_scans(app)
        titles = [s["title"] for s in (await web.get("/api/spoken/audiobooks")).json()["shows"]]
        assert titles == ["A Book"]
    assert not path.exists()
