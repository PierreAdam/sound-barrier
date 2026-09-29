"""Importing audiobooks and podcasts through the review (docs/specs/spoken-import-review.md):
one task per book / show, a proposal and online candidates, then one folder per book with
renamed, retagged files."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.scanner.tags import read_audio_file
from tests.audio import COVER_JPG, make_track
from tests.integration.conftest import SubsonicUser, signed_in
from tests.integration.test_manage import wait_scans
from tests.integration.test_spoken import spoken  # noqa: F401  (fixture)

pytestmark = pytest.mark.integration

AUDIBLE = {
    "products": [
        {  # another edition: much longer than the files
            "asin": "FULLCAST",
            "title": "Harry Potter and the Prisoner of Azkaban (Full-Cast Edition)",
            "authors": [{"name": "J.K. Rowling"}],
            "narrators": [{"name": "A Full Cast"}],
            "runtime_length_min": 700,
            "release_date": "2026-01-13",
        },
        {
            "asin": "FRY",
            "title": "Harry Potter and the Prisoner of Azkaban",
            "authors": [{"name": "J.K. Rowling"}],
            "narrators": [{"name": "Stephen Fry"}],
            "series": [{"title": "Harry Potter", "sequence": "3"}],
            "runtime_length_min": 1,
            "release_date": "2000-01-01",
            "publisher_summary": "<p>The <b>third</b> year.</p>",
            "product_images": {"500": "https://images.test/fry.jpg"},
        },
    ]
}
EDITION = "11111111-1111-4111-8111-111111111111"  # 3 tracks, like the files
EDITION_GROUP = "22222222-2222-4222-8222-222222222222"
MUSICBRAINZ_SEARCH = {
    "releases": [
        {  # a CD edition: many more tracks than files
            "id": "33333333-3333-4333-8333-333333333333",
            "title": "Harry Potter and the Prisoner of Azkaban",
            "artist-credit": [
                {"name": "J.K. Rowling", "joinphrase": " read by "},
                {"name": "Stephen Fry"},
            ],
            "media": [{"track-count": 20}, {"track-count": 20}],
            "date": "2000",
        },
        {
            "id": EDITION,
            "title": "Harry Potter and the Prisoner of Azkaban",
            "artist-credit": [
                {"name": "J.K. Rowling", "joinphrase": " read by "},
                {"name": "Stephen Fry"},
            ],
            "media": [{"track-count": 3}],
            "date": "2015-11-20",
            "release-group": {"id": EDITION_GROUP},
        },
    ]
}
MUSICBRAINZ_EDITION = {
    "id": EDITION,
    "media": [
        {
            "tracks": [
                {"title": "Chapter 1: “Owl Post”", "length": 1000},
                {"title": "Chapter 2: “Aunt Marge\u2019s Big Mistake”", "length": 1000},
                {"title": "Chapter 3: “The Grim”", "length": 1000},
            ]
        }
    ],
    "cover-art-archive": {"front": True},
}
OPEN_LIBRARY = {
    "docs": [
        {
            "key": "/works/OL82536W",
            "title": "Harry Potter and the Prisoner of Azkaban",
            "author_name": ["J. K. Rowling"],
            "first_publish_year": 1999,
            "cover_i": 10580435,
        }
    ]
}
ITUNES = {
    "results": [
        {
            "collectionId": 42,
            "collectionName": "The Show",
            "artistName": "Host",
            "primaryGenreName": "History",
            "artworkUrl600": "https://images.test/show.jpg",
        }
    ]
}


class FakeCatalogs:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host == "api.audible.com":
            return httpx.Response(200, json=AUDIBLE)
        if host == "musicbrainz.org":
            if request.url.path == f"/ws/2/release/{EDITION}":
                return httpx.Response(200, json=MUSICBRAINZ_EDITION)
            return httpx.Response(200, json=MUSICBRAINZ_SEARCH)
        if host == "openlibrary.org":
            return httpx.Response(200, json=OPEN_LIBRARY)
        if host == "itunes.apple.com":
            return httpx.Response(200, content=json.dumps(ITUNES))
        if host == "images.test":
            return httpx.Response(
                200, content=COVER_JPG.read_bytes(), headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(404)


@pytest.fixture
async def catalogs(app: FastAPI) -> AsyncIterator[FakeCatalogs]:
    fake = FakeCatalogs()
    real = app.state.http
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    yield fake
    await app.state.http.aclose()
    app.state.http = real


async def _import(app: FastAPI, web: AsyncClient, kind: str, *paths: Path) -> list[dict[str, Any]]:
    response = await web.post(
        "/api/manage/imports", json={"paths": [str(p) for p in paths], "kind": kind}
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    await app.state.imports.wait_idle()
    jobs = (await web.get("/api/manage/imports")).json()
    return next(j for j in jobs if j["id"] == job_id)["tasks"]


def _body(proposal: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """The review form sent back (camelCase), from a proposal (snake_case)."""
    body = {
        "title": proposal["title"],
        "author": proposal["author"],
        "narrator": proposal["narrator"],
        "seriesNumber": proposal["series_number"],
        "series": proposal["series"],
        "year": proposal["year"],
        "genre": proposal["genre"],
        "description": proposal["description"],
        "cover": proposal["cover"],
        "entries": proposal["entries"],
    }
    return {**body, **changes}


async def test_audiobook_review_and_import(
    app: FastAPI,
    admin: SubsonicUser,
    spoken: dict[str, Path],  # noqa: F811
    catalogs: FakeCatalogs,
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    book = inbox / "J K Rowling - Harry Potter" / "3 HARRY POTTER AND THE PRISONER OF AZKABAN"
    # A CD rip's track numbers (duplicates, too big): the file names give the order.
    for number, name, track in (
        (1, "OWL POST", "1"),
        (2, "AUNT MARGE", "29"),
        (10, "THE GRIM", "1"),
    ):
        make_track(
            book / f"CH{number:02d} {name}",
            album="HP03: Harry Potter And The Prisoner Of Azkaban",
            artist="Stephen Fry",
            composer="J.K. Rowling",
            compilation="1",
            tracknumber=track,
        )
    (book / "notes.nfo").write_text("left behind")
    # A book in two "CD" folders: one book.
    for cd in (1, 2):
        make_track(inbox / "Split Book" / f"CD{cd}" / "01", title=f"Part {cd}", album="Split")

    async with signed_in(app, admin) as web:
        await web.put("/api/manage/settings", json={"root": str(inbox)})
        tasks = await _import(app, web, "audiobook", inbox)
        by_dir = {Path(t["sourceDir"]).name: t for t in tasks}
        assert set(by_dir) == {book.name, "Split Book"}
        assert all(t["status"] == "pending" for t in tasks)
        split = by_dir["Split Book"]["spoken"]["proposal"]
        assert [e["title"] for e in split["entries"]] == ["Part 1", "Part 2"]

        task = by_dir[book.name]
        proposal = task["spoken"]["proposal"]
        assert (proposal["title"], proposal["author"], proposal["narrator"]) == (
            "Harry Potter And The Prisoner Of Azkaban",
            "J.K. Rowling",
            "Stephen Fry",
        )
        assert [e["title"] for e in proposal["entries"]] == ["Owl Post", "Aunt Marge", "The Grim"]
        # Audible: the edition closest to the files' duration first (1 min against 700 for
        # the full-cast one: the files last a few seconds). MusicBrainz: the edition with
        # as many tracks as files first. Then Open Library.
        sources = [(c["source"], c["id"]) for c in task["candidates"]]
        assert sources == [
            ("Audible", "audible:FRY"),
            ("Audible", "audible:FULLCAST"),
            ("MusicBrainz", f"musicbrainz:{EDITION}"),
            ("MusicBrainz", "musicbrainz:33333333-3333-4333-8333-333333333333"),
            ("Open Library", "openlibrary:/works/OL82536W"),
        ]
        edition = task["candidates"][2]
        assert (edition["authors"], edition["narrators"], edition["track_count"]) == (
            ["J.K. Rowling"],
            ["Stephen Fry"],
            3,
        )
        # Its track titles, cleaned like file names: the chapter titles on demand.
        assert [t["title"] for t in edition["tracks"]] == [
            "Owl Post",
            "Aunt Marge\u2019s Big Mistake",
            "The Grim",
        ]
        assert edition["cover_url"] == f"https://coverartarchive.org/release/{EDITION}/front-500"
        assert task["candidates"][3]["tracks"] == []  # not fetched: another edition
        fry = task["candidates"][0]
        assert (fry["series"], fry["series_number"], fry["description"]) == (
            "Harry Potter",
            "3",
            "The third year.",
        )

        response = await web.post(
            f"/api/manage/tasks/{task['id']}/spoken/import",
            json=_body(
                proposal,
                title="Harry Potter and the Prisoner of Azkaban",
                series="Harry Potter",
                seriesNumber="3",
                year=1999,
                cover="url:https://images.test/fry.jpg",
                # "Use chapter titles" on the MusicBrainz edition.
                entries=[
                    {**entry, "title": track["title"]}
                    for entry, track in zip(proposal["entries"], edition["tracks"], strict=True)
                ],
                musicbrainzReleaseId=EDITION,
                musicbrainzReleaseGroupId=EDITION_GROUP,
            ),
        )
        assert response.status_code == 200, response.text
        await app.state.imports.wait_idle()
        await wait_scans(app)
        jobs = (await web.get("/api/manage/imports")).json()
        done = next(t for j in jobs for t in j["tasks"] if t["id"] == task["id"])
        assert done["status"] == "imported", done["error"]

        folder = spoken["audiobooks"] / "J.K. Rowling" / "Harry Potter and the Prisoner of Azkaban"
        assert sorted(p.name for p in folder.iterdir()) == [
            "01 - Owl Post.mp3",
            "02 - Aunt Marge\u2019s Big Mistake.mp3",
            "03 - The Grim.mp3",
            "cover.jpg",
        ]
        audio = read_audio_file(folder / "03 - The Grim.mp3")
        assert audio is not None
        tags = audio.tags
        assert (tags.album, tags.album_artists, tags.composers, tags.title) == (
            "Harry Potter and the Prisoner of Azkaban",
            ["J.K. Rowling"],
            ["Stephen Fry"],
            "The Grim",
        )
        assert (tags.track_number, tags.track_total, tags.year, tags.compilation) == (
            3,
            3,
            1999,
            False,
        )
        assert (tags.mbz_album_id, tags.mbz_release_group_id) == (EDITION, EDITION_GROUP)
        assert (book / "CH01 OWL POST.mp3").is_file()  # copied: the source stays

        page = (await web.get("/api/spoken/audiobooks")).json()
        shows = {s["title"]: s for s in page["shows"]}
        imported = shows["Harry Potter and the Prisoner of Azkaban"]
        assert imported["author"] == "J.K. Rowling"

        # The same book again: not mixed into the existing folder, back to the review.
        [again] = [
            t for t in await _import(app, web, "audiobook", book) if Path(t["sourceDir"]) == book
        ]
        response = await web.post(
            f"/api/manage/tasks/{again['id']}/spoken/import",
            json=_body(
                again["spoken"]["proposal"], title="Harry Potter and the Prisoner of Azkaban"
            ),
        )
        await app.state.imports.wait_idle()
        jobs = (await web.get("/api/manage/imports")).json()
        refused = next(t for j in jobs for t in j["tasks"] if t["id"] == again["id"])
        assert refused["status"] == "pending"
        assert "already in the library" in refused["error"]
        await web.put("/api/manage/settings", json={"root": None})


async def test_merge_lookup_and_podcast_episodes(
    app: FastAPI,
    admin: SubsonicUser,
    spoken: dict[str, Path],  # noqa: F811
    catalogs: FakeCatalogs,
    tmp_path: Path,
) -> None:
    inbox = tmp_path / "inbox"
    for part in ("A", "B"):
        make_track(inbox / "Book" / f"Side {part}" / "1", title=f"Side {part}", album="Book")
    show = inbox / "The Show new"
    make_track(show / "ep3", title="Episode 3", album="The Show", artist="Host", date="2026-09-01")
    (show / "folder.jpg").write_bytes(COVER_JPG.read_bytes())

    async with signed_in(app, admin) as web:
        await web.put("/api/manage/settings", json={"root": str(inbox)})
        # Two folders that are one book: merged in the review.
        side_a, side_b = sorted(
            await _import(app, web, "audiobook", inbox / "Book"), key=lambda t: t["sourceDir"]
        )
        response = await web.post(
            f"/api/manage/tasks/{side_b['id']}/spoken/merge", json={"into": side_a["id"]}
        )
        assert response.status_code == 200, response.text
        merged = response.json()
        assert [e["title"] for e in merged["spoken"]["proposal"]["entries"]] == ["Side A", "Side B"]
        assert len(merged["items"]) == 2
        jobs = (await web.get("/api/manage/imports")).json()
        gone = next(t for j in jobs for t in j["tasks"] if t["id"] == side_b["id"])
        assert (gone["status"], gone["decision"]) == (
            "skipped",
            {"action": "merged", "into": side_a["id"]},
        )

        # A podcast: looked up on iTunes, its cover previewed, its episode added to the
        # show already in the library.
        [episode_task] = await _import(app, web, "podcast", show)
        assert [c["id"] for c in episode_task["candidates"]] == ["itunes:42"]
        response = await web.post(
            f"/api/manage/tasks/{episode_task['id']}/spoken/lookup",
            json={"title": "Another name"},
        )
        assert response.json()["spoken"]["lookup"]["query"] == {
            "title": "Another name",
            "author": None,
        }
        assert "term=Another+name" in str(catalogs.requests[-1].url)
        proposal = episode_task["spoken"]["proposal"]
        cover = proposal["cover"]
        assert cover == f"folder:{show / 'folder.jpg'}"
        preview = await web.get(
            f"/api/manage/tasks/{episode_task['id']}/spoken/cover", params={"cover": cover}
        )
        assert (preview.status_code, preview.headers["content-type"]) == (200, "image/jpeg")
        outside = await web.get(
            f"/api/manage/tasks/{episode_task['id']}/spoken/cover",
            params={"cover": f"folder:{COVER_JPG}"},
        )
        assert outside.status_code == 404  # only the import's own pictures

        response = await web.post(
            f"/api/manage/tasks/{episode_task['id']}/spoken/import",
            json=_body(proposal, title="The Show"),
        )
        assert response.status_code == 200, response.text
        await app.state.imports.wait_idle()
        await wait_scans(app)
        episodes = sorted(p.name for p in (spoken["podcasts"] / "The Show").iterdir())
        assert episodes == [
            "2026-09-01 - Episode 3.mp3",
            "cover.jpg",
            "episode 1.mp3",
            "episode 2.mp3",
        ]
        page = (await web.get("/api/spoken/podcasts")).json()
        [the_show] = [s for s in page["shows"] if s["title"] == "The Show"]
        assert the_show["episodes"] == 3
        await web.put("/api/manage/settings", json={"root": None})
