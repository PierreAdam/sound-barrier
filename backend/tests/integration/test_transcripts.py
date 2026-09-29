"""Transcripts: worker tokens, claims and leases, the transcripts sent back (database and
`.lrc`), served like synced lyrics; admins' removal and retry."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core.db import Database
from app.models import ServerSetting, Song, Transcript
from app.services import server_settings, transcripts
from tests.audio import album_tracks, make_track
from tests.integration.conftest import SubsonicUser, signed_in
from tests.integration.test_manage import wait_scans

pytestmark = pytest.mark.integration

LINES: list[dict[str, Any]] = [
    {
        "startMs": 2500,
        "endMs": 4000,
        "text": " Then   the night came. ",
        "words": [
            {"startMs": 2500, "text": " Then"},
            {"startMs": 2900, "text": " the"},
            {"startMs": 3100, "text": " night"},
            {"startMs": 3500, "text": " came."},
        ],
    },
    {"startMs": 0, "endMs": 2000, "text": "Chapter one."},
    {"startMs": 2100, "text": "   "},  # nothing said: dropped
]


@pytest.fixture
async def books(
    app: FastAPI, db: Database, admin: SubsonicUser, library: Path, tmp_path: Path
) -> AsyncIterator[dict[str, Any]]:
    """Music (never offered), an audiobook of 2 files and a podcast of 1 episode."""
    album_tracks(library, "A Band", "Some Songs", 1)
    podcasts, audiobooks = tmp_path / "podcasts", tmp_path / "audiobooks"
    make_track(podcasts / "The Show" / "episode", title="Episode", album="The Show", artist="Host")
    for n in (1, 2):
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
    async with db.session() as session:
        songs = {s.title: s for s in await session.scalars(select(Song))}
    yield {
        "songs": {title: str(song.id) for title, song in songs.items()},
        "book": str(songs["Chapter 1"].album_id),
        "show": str(songs["Episode"].album_id),
        "files": {
            "Chapter 1": audiobooks / "An Author" / "A Book" / "01.mp3",
            "Chapter 2": audiobooks / "An Author" / "A Book" / "02.mp3",
        },
    }
    async with db.session() as session:
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.SPOKEN_KEY)
        )
        await session.commit()


async def _token(app: FastAPI, admin: SubsonicUser, name: str) -> tuple[str, str]:
    async with signed_in(app, admin) as web:
        response = await web.post("/api/transcripts/tokens", json={"name": name})
        assert response.status_code == 200, response.text
        body = response.json()
    return body["token"]["id"], body["secret"]


def _bearer(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


async def test_tokens(
    app: FastAPI, client: AsyncClient, admin: SubsonicUser, user: SubsonicUser
) -> None:
    async with signed_in(app, user) as web:
        assert (await web.post("/api/transcripts/tokens", json={"name": "x"})).status_code == 403
    token_id, secret = await _token(app, admin, "Desktop")
    assert secret.startswith("sbw_")

    hello = await client.get("/api/transcriber/hello", headers=_bearer(secret))
    assert hello.status_code == 200
    assert hello.json()["worker"] == "Desktop"
    assert (await client.get("/api/transcriber/hello")).status_code == 401
    wrong = await client.get("/api/transcriber/hello", headers=_bearer("sbw_nope"))
    assert wrong.status_code == 401

    # A worker token is not a sign-in: neither the web UI nor the Subsonic API.
    assert (await client.get("/api/auth/me", headers=_bearer(secret))).status_code == 401
    ping = await client.get(
        "/rest/ping", params={"apiKey": secret, "v": "1.16.1", "c": "t", "f": "json"}
    )
    assert ping.json()["subsonic-response"]["status"] == "failed"

    async with signed_in(app, admin) as web:
        listed = (await web.get("/api/transcripts/tokens")).json()
        assert any(t["id"] == token_id and t["lastUsedAt"] for t in listed)
        assert (await web.delete(f"/api/transcripts/tokens/{token_id}")).status_code == 204
    assert (await client.get("/api/transcriber/hello", headers=_bearer(secret))).status_code == 401


async def test_transcribe_a_book(
    app: FastAPI,
    client: AsyncClient,
    admin: SubsonicUser,
    user: SubsonicUser,
    books: dict[str, Any],
) -> None:
    _, gpu = await _token(app, admin, "Desktop")
    _, other = await _token(app, admin, "Laptop")
    songs = books["songs"]

    listed = (await client.get("/api/transcriber/books", headers=_bearer(gpu))).json()
    assert {(b["title"], b["kind"], b["pending"]) for b in listed} == {
        ("A Book", "audiobooks", 2),
        ("The Show", "podcasts", 1),
    }  # never music

    # Two workers on one book: one file each, in order.
    first = await client.post(
        "/api/transcriber/claim",
        json={"albumId": books["book"], "instance": "GPU 0"},
        headers=_bearer(gpu),
    )
    assert first.status_code == 200, first.text
    assert first.json()["title"] == "Chapter 1"
    second = await client.post(
        "/api/transcriber/claim", json={"albumId": books["book"]}, headers=_bearer(other)
    )
    assert second.json()["title"] == "Chapter 2"
    nothing = await client.post(
        "/api/transcriber/claim", json={"albumId": books["book"]}, headers=_bearer(gpu)
    )
    assert nothing.status_code == 204

    chapter = songs["Chapter 1"]
    renewed = await client.post(
        f"/api/transcriber/files/{chapter}/progress", json={"progress": 0.5}, headers=_bearer(gpu)
    )
    assert renewed.status_code == 200
    stolen = await client.post(
        f"/api/transcriber/files/{chapter}/progress", json={}, headers=_bearer(other)
    )
    assert stolen.status_code == 409

    async with signed_in(app, admin) as web:
        overview = (await web.get("/api/transcripts")).json()
    running = {w["title"]: w for w in overview["working"]}
    assert running["Chapter 1"]["worker"] == "Desktop · GPU 0"
    assert running["Chapter 1"]["progress"] == 0.5

    audio = await client.get(f"/api/transcriber/files/{chapter}/audio", headers=_bearer(gpu))
    assert audio.status_code == 200
    assert audio.content == books["files"]["Chapter 1"].read_bytes()
    music = await client.get(
        f"/api/transcriber/files/{songs['Track 1']}/audio", headers=_bearer(gpu)
    )
    assert music.status_code == 404  # workers only get podcasts and audiobooks

    saved = await client.put(
        f"/api/transcriber/files/{chapter}/transcript",
        json={"model": "whisper large-v3", "language": "en", "lines": LINES},
        headers=_bearer(gpu),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"lines": 2, "done": True, "lrcWritten": True}
    lrc = books["files"]["Chapter 1"].with_suffix(".lrc").read_text("utf-8")
    assert lrc.splitlines()[0] == transcripts.LRC_MARKER
    assert "[00:00.00]Chapter one.\n[00:02.50]Then the night came." in lrc

    # Served like synced lyrics: the web UI (with the words), the Subsonic apps.
    async with signed_in(app, user) as web:
        lyrics = (await web.get(f"/api/songs/{chapter}/lyrics")).json()
    assert (lyrics["source"], lyrics["synced"]) == ("transcript", True)
    assert [line["text"] for line in lyrics["lines"]] == ["Chapter one.", "Then the night came."]
    assert [w["text"] for w in lyrics["lines"][1]["words"]] == ["Then ", "the ", "night ", "came."]
    subsonic = await client.get("/rest/getLyricsBySongId", params=user.params(id=chapter))
    structured = subsonic.json()["subsonic-response"]["lyricsList"]["structuredLyrics"][0]
    assert [line["start"] for line in structured["line"]] == [0, 2500]

    book = (
        await client.get(f"/api/transcriber/books/{books['book']}", headers=_bearer(gpu))
    ).json()
    assert [(f["title"], f["status"]) for f in book["files"]] == [
        ("Chapter 1", "done"),
        ("Chapter 2", "working"),
    ]


async def test_someone_elses_lrc_is_kept(
    app: FastAPI,
    client: AsyncClient,
    admin: SubsonicUser,
    user: SubsonicUser,
    books: dict[str, Any],
) -> None:
    _, secret = await _token(app, admin, "Desktop")
    chapter = books["songs"]["Chapter 2"]
    theirs = books["files"]["Chapter 2"].with_suffix(".lrc")
    theirs.write_text("[00:01.00]My own lyrics", "utf-8")
    claimed = await client.post(
        "/api/transcriber/claim", json={"songId": chapter}, headers=_bearer(secret)
    )
    assert claimed.status_code == 200
    saved = await client.put(
        f"/api/transcriber/files/{chapter}/transcript",
        json={"lines": LINES},
        headers=_bearer(secret),
    )
    assert saved.json()["lrcWritten"] is False
    assert theirs.read_text("utf-8") == "[00:01.00]My own lyrics"
    async with signed_in(app, user) as web:
        lyrics = (await web.get(f"/api/songs/{chapter}/lyrics")).json()
    assert lyrics["source"] == "lrc"  # a .lrc of the user wins

    async with signed_in(app, admin) as web:
        removed = await web.delete(f"/api/transcripts/books/{books['book']}")
    assert removed.json() == {"count": 1}
    assert theirs.exists()  # not ours: kept


async def test_expired_lease_and_failures(
    app: FastAPI, client: AsyncClient, db: Database, admin: SubsonicUser, books: dict[str, Any]
) -> None:
    _, gone = await _token(app, admin, "Turned off")
    _, alive = await _token(app, admin, "Desktop")
    episode = books["songs"]["Episode"]
    claimed = await client.post(
        "/api/transcriber/claim", json={"kind": "podcasts"}, headers=_bearer(gone)
    )
    assert claimed.json()["songId"] == episode
    assert (
        await client.post(
            "/api/transcriber/claim", json={"kind": "podcasts"}, headers=_bearer(alive)
        )
    ).status_code == 204

    async with db.session() as session:  # the first worker stopped: its lease runs out
        await session.execute(
            update(Transcript).values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
    taken = await client.post(
        "/api/transcriber/claim", json={"kind": "podcasts"}, headers=_bearer(alive)
    )
    assert taken.json()["songId"] == episode
    late = await client.put(
        f"/api/transcriber/files/{episode}/transcript",
        json={"lines": LINES},
        headers=_bearer(gone),
    )
    assert late.status_code == 409

    failed = await client.post(
        f"/api/transcriber/files/{episode}/fail",
        json={"error": "CUDA out of memory"},
        headers=_bearer(alive),
    )
    assert failed.status_code == 204
    again = await client.post(
        "/api/transcriber/claim", json={"kind": "podcasts"}, headers=_bearer(alive)
    )
    assert again.status_code == 204  # failed files wait for a retry
    async with signed_in(app, admin) as web:
        show = (await web.get(f"/api/transcripts/books/{books['show']}")).json()
        assert show["files"][0]["error"] == "CUDA out of memory"
        assert (await web.post(f"/api/transcripts/books/{books['show']}/retry")).json() == {
            "count": 1
        }
    retried = await client.post(
        "/api/transcriber/claim", json={"kind": "podcasts"}, headers=_bearer(alive)
    )
    assert retried.json()["songId"] == episode

    released = await client.post(
        f"/api/transcriber/files/{episode}/release", headers=_bearer(alive)
    )
    assert released.status_code == 204
    async with db.session() as session:
        assert await session.get(Transcript, books["songs"]["Episode"]) is None


async def test_remove_and_revoke(
    app: FastAPI, client: AsyncClient, db: Database, admin: SubsonicUser, books: dict[str, Any]
) -> None:
    token_id, secret = await _token(app, admin, "Desktop")
    chapter = books["songs"]["Chapter 1"]
    await client.post("/api/transcriber/claim", json={"songId": chapter}, headers=_bearer(secret))
    await client.put(
        f"/api/transcriber/files/{chapter}/transcript",
        json={"lines": LINES},
        headers=_bearer(secret),
    )
    ours = books["files"]["Chapter 1"].with_suffix(".lrc")
    assert ours.exists()
    async with signed_in(app, admin) as web:
        assert (await web.delete(f"/api/transcripts/books/{books['book']}")).json() == {"count": 1}
    assert not ours.exists()

    # Revoking a token gives its files back.
    await client.post("/api/transcriber/claim", json={"songId": chapter}, headers=_bearer(secret))
    async with signed_in(app, admin) as web:
        assert (await web.delete(f"/api/transcripts/tokens/{token_id}")).status_code == 204
    async with db.session() as session:
        assert (await session.scalars(select(Transcript))).all() == []


async def test_long_transcript_in_parts(
    app: FastAPI,
    client: AsyncClient,
    admin: SubsonicUser,
    user: SubsonicUser,
    books: dict[str, Any],
) -> None:
    _, secret = await _token(app, admin, "Desktop")
    chapter = books["songs"]["Chapter 2"]
    await client.post("/api/transcriber/claim", json={"songId": chapter}, headers=_bearer(secret))
    url = f"/api/transcriber/files/{chapter}/transcript"
    parts = [
        {"part": 0, "last": False, "lines": [{"startMs": 0, "text": "Discarded"}]},
        {"part": 0, "last": False, "lines": [{"startMs": 0, "text": "One"}]},  # started over
        {"part": 1, "last": False, "lines": [{"startMs": 1000, "text": "Two"}]},
        {"part": 2, "last": True, "lines": [{"startMs": 2000, "text": "Three"}], "model": "m"},
    ]
    answers = [(await client.put(url, json=body, headers=_bearer(secret))).json() for body in parts]
    assert [(a["lines"], a["done"]) for a in answers] == [
        (1, False),
        (1, False),
        (2, False),
        (3, True),
    ]
    async with signed_in(app, user) as web:
        lyrics = (await web.get(f"/api/songs/{chapter}/lyrics")).json()
    assert [line["text"] for line in lyrics["lines"]] == ["One", "Two", "Three"]
