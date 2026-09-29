"""An audiobook's details: read from its tags (description, narrator, series), shown on its
page, changed by an admin (tags written, folder renamed, songs kept)."""

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
from tests.audio import make_track
from tests.integration.conftest import SubsonicUser, signed_in
from tests.integration.test_manage import wait_scans

pytestmark = pytest.mark.integration


async def _call(client: AsyncClient, user: SubsonicUser, endpoint: str, **params: str) -> Any:
    return (await client.get(f"/rest/{endpoint}", params=user.params(**params))).json()[
        "subsonic-response"
    ]


@pytest.fixture
async def books(
    app: FastAPI, db: Database, admin: SubsonicUser, library: Path, tmp_path: Path
) -> AsyncIterator[Path]:
    """Two books by the same author, the first one of a series, tagged like the import."""
    root = tmp_path / "audiobooks"
    for n in (1, 2):
        make_track(
            root / "An Author" / "Book One" / f"0{n}",
            fmt="flac",
            title=f"Chapter {n}",
            album="Book One",
            artist="An Author",
            albumartist="An Author",
            composer="A Narrator",
            grouping="The Saga, Book 1",
            comment="Once upon a time.",
            tracknumber=f"{n}/2",
        )
    make_track(
        root / "An Author" / "Book Two" / "01",
        fmt="flac",
        title="Chapter 1",
        album="Book Two",
        artist="An Author",
        albumartist="An Author",
        grouping="The Saga #2",
    )
    async with signed_in(app, admin) as web:
        response = await web.put(
            "/api/library/spoken/audiobooks", json={"enabled": True, "path": str(root)}
        )
        assert response.status_code == 200, response.text
    await wait_scans(app)
    yield root
    async with db.session() as session:
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.SPOKEN_KEY)
        )
        await session.commit()


async def _shows(web: AsyncClient) -> dict[str, dict[str, Any]]:
    page = (await web.get("/api/spoken/audiobooks")).json()
    return {show["title"]: show for show in page["shows"]}


async def test_details_from_the_tags(app: FastAPI, user: SubsonicUser, books: Path) -> None:
    async with signed_in(app, user) as web:
        shows = await _shows(web)
        one, two = shows["Book One"], shows["Book Two"]
        assert (one["series"], one["seriesNumber"], one["narrator"]) == (
            "The Saga",
            "1",
            "A Narrator",
        )
        assert (two["series"], two["seriesNumber"], two["narrator"]) == ("The Saga", "2", None)
        page = (await web.get(f"/api/spoken/shows/{one['id']}")).json()
        assert page["description"] == "Once upon a time."
        # Details are for admins only.
        assert (await web.get(f"/api/spoken/shows/{one['id']}/details")).status_code == 403


async def test_change_details(
    app: FastAPI, client: AsyncClient, admin: SubsonicUser, user: SubsonicUser, books: Path
) -> None:
    async with signed_in(app, user) as web:
        one = (await _shows(web))["Book One"]
        chapters = (await web.get(f"/api/spoken/shows/{one['id']}")).json()["episodes"]
    await _call(client, user, "createBookmark", id=chapters[1]["id"], position="5000")

    async with signed_in(app, admin) as web:
        current = (await web.get(f"/api/spoken/shows/{one['id']}/details")).json()
        assert current["title"] == "Book One"
        taken = await web.put(
            f"/api/spoken/shows/{one['id']}/details", json={**current, "title": "Book Two"}
        )
        assert taken.status_code == 400  # another book's folder
        assert "already exists" in taken.json()["detail"]

        changed = await web.put(
            f"/api/spoken/shows/{one['id']}/details",
            json={
                **current,
                "title": "The First Book",
                "narrator": "Another Narrator",
                "seriesNumber": "1.5",
                "description": "A new description.",
                "year": 1999,
            },
        )
        assert changed.status_code == 200, changed.text
        new_id = changed.json()["id"]
        assert new_id != one["id"]  # the album follows its name

    # The folder was renamed to match; the files are the same songs.
    assert not (books / "An Author" / "Book One").exists()
    assert sorted(p.name for p in (books / "An Author" / "The First Book").iterdir()) == [
        "01.flac",
        "02.flac",
    ]
    async with signed_in(app, user) as web:
        page = (await web.get(f"/api/spoken/shows/{new_id}")).json()
        show = page["show"]
        assert (show["title"], show["narrator"], show["seriesNumber"], show["year"]) == (
            "The First Book",
            "Another Narrator",
            "1.5",
            1999,
        )
        assert page["description"] == "A new description."
        assert [e["id"] for e in page["episodes"]] == [c["id"] for c in chapters]
    marks = (await _call(client, user, "getBookmarks"))["bookmarks"]["bookmark"]
    assert [(m["entry"]["id"], m["position"]) for m in marks] == [(chapters[1]["id"], 5000)]


async def test_change_chapters(app: FastAPI, admin: SubsonicUser, books: Path) -> None:
    """A file's title, and the chapters inside a file (written into it, read back)."""
    from app.library_manager.chapters import Chapter, write

    path = make_track(
        books / "An Author" / "One File" / "book",
        title="book",
        album="One File",
        artist="An Author",
        albumartist="An Author",
    )
    write(path, [Chapter(0, "001"), Chapter(400, "002"), Chapter(800, "003")], 1045)
    await app.state.scans.scan_paths((await _folder_id(app)), ["An Author/One File"])
    async with signed_in(app, admin) as web:
        book = (await _shows(web))["One File"]
        current = (await web.get(f"/api/spoken/shows/{book['id']}/details")).json()
        [file] = current["files"]
        assert (file["title"], file["canWriteChapters"]) == ("book", True)
        assert [c["title"] for c in file["chapters"]] == ["001", "002", "003"]

        file["title"] = "The Whole Book"
        file["chapters"] = [
            {"startMs": 0, "title": "Opening Credits"},
            {"startMs": 400, "title": "Chapter 1"},
            {"startMs": 800, "title": "Chapter 2"},
        ]
        changed = await web.put(f"/api/spoken/shows/{book['id']}/details", json=current)
        assert changed.status_code == 200, changed.text
        page = (await web.get(f"/api/spoken/shows/{changed.json()['id']}")).json()
    [episode] = page["episodes"]
    assert episode["title"] == "The Whole Book"
    assert [c["title"] for c in episode["chapters"]] == [
        "Opening Credits",
        "Chapter 1",
        "Chapter 2",
    ]


async def _folder_id(app: FastAPI) -> int:
    from sqlalchemy import select

    from app.models import MusicFolder

    async with app.state.db.session() as session:
        return await session.scalar(select(MusicFolder.id).where(MusicFolder.kind == "audiobooks"))


async def test_audible_lookup(app: FastAPI, admin: SubsonicUser, user: SubsonicUser) -> None:
    """Search and chapters, through the server (a fake Audible answers)."""
    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/1.0/catalog/products":
            return httpx.Response(
                200,
                json={
                    "products": [
                        {
                            "asin": "B08V8B2CGV",
                            "title": "Dungeon Crawler Carl",
                            "authors": [{"name": "Matt Dinniman"}],
                            "series": [{"title": "Dungeon Crawler Carl", "sequence": "1"}],
                            "runtime_length_min": 811,
                        }
                    ]
                },
            )
        if request.url.path == "/1.0/content/B08V8B2CGV/metadata":
            return httpx.Response(
                200,
                json={
                    "content_metadata": {
                        "chapter_info": {
                            "brandIntroDurationMs": 3970,
                            "brandOutroDurationMs": 4945,
                            "is_accurate": True,
                            "runtime_length_ms": 48693126,
                            "chapters": [
                                {
                                    "start_offset_ms": 17367,
                                    "length_ms": 1240804,
                                    "title": "Chapter 1",
                                },
                                {
                                    "start_offset_ms": 0,
                                    "length_ms": 17367,
                                    "title": "Opening Credits",
                                },
                            ],
                        }
                    }
                },
            )
        return httpx.Response(404)

    real = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    try:
        async with signed_in(app, user) as web:
            assert (
                await web.get("/api/spoken/audible/search", params={"title": "x"})
            ).status_code == 403
        async with signed_in(app, admin) as web:
            found = (
                await web.get(
                    "/api/spoken/audible/search", params={"title": "Dungeon Crawler Carl"}
                )
            ).json()
            assert [(b["asin"], b["seriesNumber"]) for b in found] == [("B08V8B2CGV", "1")]
            chapters = (await web.get("/api/spoken/audible/B08V8B2CGV/chapters")).json()
            assert (chapters["introMs"], chapters["runtimeMs"]) == (3970, 48693126)
            assert [c["title"] for c in chapters["chapters"]] == [
                "Opening Credits",
                "Chapter 1",
            ]  # by start
            assert (await web.get("/api/spoken/audible/not-an-asin/chapters")).status_code == 502
    finally:
        await app.state.http.aclose()
        app.state.http = real
