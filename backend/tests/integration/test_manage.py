"""Manage Library API. Everything happens in temporary folders."""

import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import update

from app.core.db import Database
from app.library_manager.as_is import AsIsTagger
from app.library_manager.tagger import (
    Candidate,
    Identification,
    ImportMode,
    ImportOptions,
    ItemInfo,
    Recommendation,
    TaggerLibrary,
)
from app.models import ImportTask
from app.scanner.scanner import run_scan
from app.scanner.tags import read_audio_file
from tests.audio import COVER_JPG, album_tracks, make_track
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration


@pytest.fixture
def inbox(tmp_path: Path) -> Path:
    root = tmp_path / "inbox"
    album_tracks(root, "New Band", "First Album", 2, date="2024")
    (root / "New Band" / "First Album" / "cover.jpg").write_bytes(COVER_JPG.read_bytes())
    return root


@pytest.fixture
async def admin_client(
    app: FastAPI, admin: SubsonicUser, library: Path, inbox: Path
) -> AsyncIterator[AsyncClient]:
    async with signed_in(app, admin) as client:
        response = await client.put("/api/manage/settings", json={"root": str(inbox)})
        assert response.status_code == 200, response.text
        yield client
        # Imports trigger scans: let them finish before the next test resets the tables.
        await app.state.imports.wait_idle()
        await wait_scans(app)
        await client.put("/api/manage/settings", json={"root": None})
    app.state.imports.tagger = AsIsTagger()


async def wait_scans(app: FastAPI) -> None:
    for _ in range(200):
        if not app.state.scans.running:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("scan did not finish")


async def run_import(app: FastAPI, client: AsyncClient, *paths: Path) -> list[dict[str, Any]]:
    response = await client.post("/api/manage/imports", json={"paths": [str(p) for p in paths]})
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    await app.state.imports.wait_idle()
    job = next(j for j in (await client.get("/api/manage/imports")).json() if j["id"] == job_id)
    return job["tasks"]


async def decide(app: FastAPI, client: AsyncClient, task_id: int, **body: Any) -> dict[str, Any]:
    response = await client.post(f"/api/manage/tasks/{task_id}/decision", json=body)
    assert response.status_code == 200, response.text
    await app.state.imports.wait_idle()
    tasks = [t for j in (await client.get("/api/manage/imports")).json() for t in j["tasks"]]
    return next(t for t in tasks if t["id"] == task_id)


# --- settings and browsing ------------------------------------------------------------


async def test_settings(admin_client: AsyncClient, inbox: Path, tmp_path: Path) -> None:
    settings = (await admin_client.get("/api/manage/settings")).json()
    assert (settings["root"], settings["rootReachable"]) == (str(inbox), True)
    assert (settings["mode"], settings["autoApplyStrong"], settings["matching"]) == (
        "copy",
        True,
        False,
    )
    assert settings["transcodeLossless"] is False

    bad = await admin_client.put("/api/manage/settings", json={"root": str(tmp_path / "nope")})
    assert bad.status_code == 400

    cleared = (await admin_client.put("/api/manage/settings", json={"root": None})).json()
    assert cleared["root"] is None
    no_root = await admin_client.get("/api/manage/browse")
    assert no_root.status_code == 400
    assert "import root" in no_root.json()["detail"]


async def test_regular_users_are_refused(app: FastAPI, user: SubsonicUser) -> None:
    async with signed_in(app, user) as client:
        for method, path in [
            ("GET", "/api/manage/settings"),
            ("GET", "/api/manage/browse"),
            ("POST", "/api/manage/delete"),
        ]:
            assert (await client.request(method, path, json={})).status_code == 403, path


async def test_browse(admin_client: AsyncClient, inbox: Path, tmp_path: Path) -> None:
    listing = (await admin_client.get("/api/manage/browse")).json()  # the root itself
    assert (listing["root"], listing["parent"]) == (str(inbox), None)
    assert [(e["name"], e["isDir"]) for e in listing["entries"]] == [("New Band", True)]

    band = inbox / "New Band"
    albums = (await admin_client.get("/api/manage/browse", params={"path": str(band)})).json()
    assert albums["entries"][0] == {
        "name": "First Album",
        "path": str(band / "First Album"),
        "isDir": True,
        "audioFiles": 2,
        "size": 0,
    }

    for outside in (tmp_path, inbox / ".." / "music"):
        response = await admin_client.get("/api/manage/browse", params={"path": str(outside)})
        assert response.status_code == 403, outside


# --- imports ----------------------------------------------------------------------------


async def test_import_as_is(
    app: FastAPI,
    admin_client: AsyncClient,
    client: AsyncClient,
    admin: SubsonicUser,
    inbox: Path,
    library: Path,
) -> None:
    (task,) = await run_import(app, admin_client, inbox / "New Band")
    assert task["status"] == "pending"  # no matching: waits for a decision
    assert task["recommendation"] == "none"
    assert [i["title"] for i in task["items"]] == ["Track 1", "Track 2"]

    done = await decide(app, admin_client, task["id"], action="as_is")
    assert done["status"] == "imported", done
    assert done["result"]["paths"] == [
        "New Band/First Album/01 - Track 1.mp3",
        "New Band/First Album/02 - Track 2.mp3",
    ]
    assert (library / "New Band" / "First Album" / "cover.jpg").exists()
    assert (inbox / "New Band" / "First Album" / "01 - Track 1.mp3").exists()  # copied, kept

    # Already scanned (targeted scan) when the task shows "imported": no waiting.
    data = (await client.get("/rest/getArtists", params=admin.params())).json()
    names = [a["name"] for i in data["subsonic-response"]["artists"]["index"] for a in i["artist"]]
    assert "New Band" in names

    # Importing the same album again: stays pending with an explanation.
    (again,) = await run_import(app, admin_client, inbox / "New Band" / "First Album")
    again = await decide(app, admin_client, again["id"], action="as_is")
    assert again["status"] == "pending"
    assert "already in the library" in again["error"]

    skipped = await decide(app, admin_client, again["id"], action="skip")
    assert skipped["status"] == "skipped"
    retried = await decide(app, admin_client, again["id"], action="retry")
    assert retried["status"] == "pending"


async def test_search_needs_matching(app: FastAPI, admin_client: AsyncClient, inbox: Path) -> None:
    (task,) = await run_import(app, admin_client, inbox)
    response = await admin_client.post(
        f"/api/manage/tasks/{task['id']}/search", json={"artist": "x"}
    )
    assert response.status_code == 400
    assert "beets" in response.json()["detail"]


async def test_import_outside_folders_refused(admin_client: AsyncClient, library: Path) -> None:
    response = await admin_client.post("/api/manage/imports", json={"paths": [str(library)]})
    assert response.status_code == 403


class FakeMatcher(AsIsTagger):
    """A tagger with matching, to exercise candidates / auto-apply without beets."""

    name = "fake"
    supports_matching = True

    def __init__(self, recommendation: Recommendation) -> None:
        self.recommendation = recommendation
        self.applied: list[Candidate | None] = []

    def identify(self, items: list[ItemInfo]) -> Identification:
        candidate = Candidate(
            id="mb-1", source="musicbrainz", artist="New Band", album="First Album", distance=0.02
        )
        return Identification([candidate], self.recommendation)

    def search(self, items: list[ItemInfo], **query: Any) -> Identification:
        other = Candidate(
            id="mb-2", source="musicbrainz", artist="Other", album=str(query), distance=0.3
        )
        return Identification([other], Recommendation.MEDIUM)

    def apply(
        self,
        items: list[ItemInfo],
        candidate: Candidate | None,
        library_root: Path,
        options: ImportOptions,
    ) -> list[Path]:
        self.applied.append(candidate)
        return super().apply(items, None, library_root, options)


async def test_strong_matches_are_applied_automatically(
    app: FastAPI, admin_client: AsyncClient, inbox: Path
) -> None:
    tagger = FakeMatcher(Recommendation.STRONG)
    app.state.imports.tagger = tagger
    (task,) = await run_import(app, admin_client, inbox)
    assert task["status"] == "imported"
    assert task["decision"] == {"action": "apply", "candidateId": "mb-1", "auto": True}
    assert [c.id for c in tagger.applied if c] == ["mb-1"]


async def test_review_search_and_apply_candidate(
    app: FastAPI, admin_client: AsyncClient, inbox: Path
) -> None:
    tagger = FakeMatcher(Recommendation.LOW)
    app.state.imports.tagger = tagger
    (task,) = await run_import(app, admin_client, inbox)
    assert (task["status"], task["candidates"][0]["id"]) == ("pending", "mb-1")

    response = await admin_client.post(
        f"/api/manage/tasks/{task['id']}/search", json={"artist": "Other"}
    )
    assert response.status_code == 200
    await app.state.imports.wait_idle()
    tasks = [t for j in (await admin_client.get("/api/manage/imports")).json() for t in j["tasks"]]
    searched = next(t for t in tasks if t["id"] == task["id"])
    assert [c["id"] for c in searched["candidates"]] == ["mb-2"]

    bad = await admin_client.post(
        f"/api/manage/tasks/{task['id']}/decision", json={"action": "apply", "candidateId": "nope"}
    )
    assert bad.status_code == 400
    done = await decide(app, admin_client, task["id"], action="apply", candidateId="mb-2")
    assert done["status"] == "imported"
    assert [c.id for c in tagger.applied if c] == ["mb-2"]


# --- deletion ---------------------------------------------------------------------------


async def test_delete_album_and_song(
    app: FastAPI,
    admin_client: AsyncClient,
    client: AsyncClient,
    admin: SubsonicUser,
    db: Database,
    library: Path,
) -> None:
    album_tracks(library, "Keep", "Kept Album", 1)
    album_tracks(library, "Gone", "Deleted Album", 2)
    album_tracks(library, "Half", "Half Album", 2)
    (library / "Gone" / "Deleted Album" / "cover.jpg").write_bytes(COVER_JPG.read_bytes())
    await run_scan(db)

    async def rest(method: str, **params: str) -> Any:
        return (await client.get(f"/rest/{method}", params=admin.params(**params))).json()[
            "subsonic-response"
        ]

    artists = {
        a["name"]: a["id"]
        for i in (await rest("getArtists"))["artists"]["index"]
        for a in i["artist"]
    }
    gone_album = (await rest("getArtist", id=artists["Gone"]))["artist"]["album"][0]["id"]
    half_album = (await rest("getArtist", id=artists["Half"]))["artist"]["album"][0]["id"]
    half_song = (await rest("getAlbum", id=half_album))["album"]["song"][0]["id"]

    result = (
        await admin_client.post(
            "/api/manage/delete", json={"albumIds": [gone_album], "songIds": [half_song]}
        )
    ).json()
    assert (result["songs"], result["filesDeleted"], result["filesAlreadyGone"]) == (3, 3, 0)
    assert sorted(result["foldersRemoved"]) == ["Gone", "Gone/Deleted Album"]

    assert not (library / "Gone").exists()  # album folder (with its cover) and artist folder
    assert (library / "Half" / "Half Album" / "02 - Track 2.mp3").exists()
    assert not (library / "Half" / "Half Album" / "01 - Track 1.mp3").exists()
    assert (library / "Keep" / "Kept Album" / "01 - Track 1.mp3").exists()

    names = [a["name"] for i in (await rest("getArtists"))["artists"]["index"] for a in i["artist"]]
    assert names == ["Half", "Keep"]
    assert (await rest("getAlbum", id=gone_album))["error"]["code"] == 70
    assert (await rest("getAlbum", id=half_album))["album"]["songCount"] == 1

    empty = await admin_client.post("/api/manage/delete", json={})
    assert empty.status_code == 400


# --- lossless conversion and duplicates --------------------------------------------------


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
async def test_import_converts_flac_to_mp3(
    app: FastAPI, admin_client: AsyncClient, inbox: Path, library: Path, tmp_path: Path
) -> None:
    source = inbox / "Flac Band" / "Lossless"
    for n in (1, 2):
        make_track(
            source / f"0{n}",
            fmt="flac",
            title=f"Song {n}",
            artist="Flac Band",
            albumartist="Flac Band",
            album="Lossless",
            tracknumber=f"{n}/2",
            musicbrainz_albumid="11111111-2222-3333-4444-555555555555",
            picture=True,
        )
    (source / "folder.jpg").write_bytes(COVER_JPG.read_bytes())
    response = await admin_client.put(
        "/api/manage/settings", json={"root": str(inbox), "transcodeLossless": True}
    )
    assert response.json()["transcodeLossless"] is True

    (task,) = await run_import(app, admin_client, source)
    done = await decide(app, admin_client, task["id"], action="as_is")
    assert done["status"] == "imported", done
    assert done["result"]["converted"] == 2
    assert done["result"]["paths"] == [
        "Flac Band/Lossless/01 - Song 1.mp3",
        "Flac Band/Lossless/02 - Song 2.mp3",
    ]
    album = library / "Flac Band" / "Lossless"
    assert (album / "folder.jpg").exists()

    converted = read_audio_file(album / "01 - Song 1.mp3")
    assert converted is not None
    assert (converted.tags.title, converted.tags.album, converted.tags.track_number) == (
        "Song 1",
        "Lossless",
        1,
    )
    assert converted.tags.mbz_album_id == "11111111-2222-3333-4444-555555555555"
    assert converted.tags.has_picture
    assert converted.info.bit_rate >= 300  # 320 kbps CBR
    # Sources untouched, staging cleaned.
    assert sorted(p.name for p in source.iterdir()) == ["01.flac", "02.flac", "folder.jpg"]
    assert not any(tmp_path.glob("**/import-staging/task-*"))


async def test_import_refuses_existing_album_folder(
    app: FastAPI, admin_client: AsyncClient, inbox: Path, library: Path
) -> None:
    album_tracks(library, "New Band", "First Album", 1)  # already there, other files
    (library / "New Band" / "First Album" / "01 - Track 1.mp3").rename(
        library / "New Band" / "First Album" / "01 - Other name.mp3"
    )
    (task,) = await run_import(app, admin_client, inbox / "New Band" / "First Album")
    done = await decide(app, admin_client, task["id"], action="as_is")
    assert done["status"] == "pending"
    assert "already in the library" in done["error"]
    assert sorted(p.name for p in (library / "New Band" / "First Album").iterdir()) == [
        "01 - Other name.mp3"
    ]


async def test_duplicates_are_detected_ignoring_case(
    app: FastAPI, admin_client: AsyncClient, inbox: Path, library: Path
) -> None:
    """Library disks are often case-sensitive: "FIRST ALBUM" is the same album."""
    album_tracks(library, "NEW BAND", "FIRST ALBUM", 1)
    (task,) = await run_import(app, admin_client, inbox / "New Band" / "First Album")
    done = await decide(app, admin_client, task["id"], action="as_is")
    assert done["status"] == "pending"
    assert "FIRST ALBUM" in done["error"]
    assert [p.name for p in library.iterdir()] == ["NEW BAND"]  # no second artist folder


async def test_existing_artist_folder_is_reused_whatever_its_case(
    app: FastAPI, admin_client: AsyncClient, inbox: Path, library: Path
) -> None:
    album_tracks(library, "NEW BAND", "Older Album", 1)
    (task,) = await run_import(app, admin_client, inbox / "New Band" / "First Album")
    done = await decide(app, admin_client, task["id"], action="as_is")
    assert done["status"] == "imported"
    assert done["result"]["paths"][0] == "NEW BAND/First Album/01 - Track 1.mp3"
    assert [p.name for p in library.iterdir()] == ["NEW BAND"]


async def test_duplicates_are_detected_in_the_library_database(
    app: FastAPI, admin_client: AsyncClient, inbox: Path, library: Path, db: Database
) -> None:
    """An album of the library stored under another folder name (e.g. imported before
    Sound-Barrier) is still found, from the scanned tags."""
    make_track(
        library / "Old Layout" / "Some Folder" / "01 - Track 1",
        title="Track 1",
        artist="New Band",
        albumartist="New Band",
        album="First Album",
    )
    await run_scan(db)
    (task,) = await run_import(app, admin_client, inbox / "New Band" / "First Album")
    done = await decide(app, admin_client, task["id"], action="as_is")
    assert done["status"] == "pending"
    assert "already in the library: New Band - First Album" in done["error"]
    assert [p.name for p in library.iterdir()] == ["Old Layout"]


# --- library status and adopting --------------------------------------------------------


class FakeDatabaseTagger(FakeMatcher):
    """A matching tagger with its own database (like beets), in memory."""

    def __init__(self) -> None:
        super().__init__(Recommendation.MEDIUM)
        self.known: set[str] = set()
        self.options: list[ImportOptions] = []

    def library(self, library_root: Path) -> TaggerLibrary | None:
        missing = [p for p in self.known if not (library_root / p).exists()]
        return TaggerLibrary(
            len({p.rpartition("/")[0] for p in self.known}), set(self.known), missing
        )

    def forget_missing(self, library_root: Path) -> int:
        gone = [p for p in self.known if not (library_root / p).exists()]
        self.known -= set(gone)
        return len(gone)

    def apply(
        self,
        items: list[ItemInfo],
        candidate: Candidate | None,
        library_root: Path,
        options: ImportOptions,
    ) -> list[Path]:
        self.options.append(options)
        paths = super().apply(items, candidate, library_root, options)
        self.known |= {p.relative_to(library_root).as_posix() for p in paths}
        return paths


async def test_library_status_and_adopt(
    app: FastAPI, admin_client: AsyncClient, library: Path, db: Database
) -> None:
    tagger = FakeDatabaseTagger()
    app.state.imports.tagger = tagger
    album_tracks(library, "Old Band", "Known", 1)
    album_tracks(library, "Old Band", "Not Known", 2)
    tagger.known = {"Old Band/Known/01 - Track 1.mp3", "Old Band/Gone/01 - Track 1.mp3"}
    await run_scan(db)

    status = (await admin_client.get("/api/manage/library-status")).json()
    assert (status["albums"], status["songs"], status["hasTaggerDatabase"]) == (2, 3, True)
    assert (status["taggerSongs"], status["taggerMissing"]) == (1, 1)
    assert status["unknownFolders"] == [
        {
            "path": "Old Band/Not Known",
            "artist": "Old Band",
            "album": "Not Known",
            "songs": 2,
            "unknownSongs": 2,
        }
    ]

    # Adopting: matched like an import (waits for review here), then tagged in place.
    response = await admin_client.post("/api/manage/adopt", json={"paths": ["Old Band/Not Known"]})
    assert response.status_code == 202, response.text
    assert response.json()["kind"] == "adopt"
    await app.state.imports.wait_idle()
    (task,) = next(
        j for j in (await admin_client.get("/api/manage/imports")).json() if j["kind"] == "adopt"
    )["tasks"]
    assert task["status"] == "pending"
    done = await decide(app, admin_client, task["id"], action="apply", candidateId="mb-1")
    assert done["status"] == "imported", done  # no "already in the library" for adopted albums
    assert done["result"]["paths"] == [
        "Old Band/Not Known/01 - Track 1.mp3",
        "Old Band/Not Known/02 - Track 2.mp3",
    ]
    assert tagger.options[-1].mode is ImportMode.IN_PLACE
    assert sorted(p.name for p in (library / "Old Band").iterdir()) == [
        "Known",
        "Not Known",
    ]  # nothing copied

    status = (await admin_client.get("/api/manage/library-status")).json()
    assert (status["taggerSongs"], status["unknownFolderCount"]) == (3, 0)
    assert (await admin_client.post("/api/manage/forget-missing")).json() == {"removed": 1}
    assert (await admin_client.get("/api/manage/library-status")).json()["taggerMissing"] == 0


async def test_adopt_refuses_folders_outside_the_library(admin_client: AsyncClient) -> None:
    response = await admin_client.post("/api/manage/adopt", json={"paths": ["../elsewhere"]})
    assert response.status_code == 403


async def test_bulk_skip_and_retry(
    app: FastAPI, admin_client: AsyncClient, inbox: Path, db: Database
) -> None:
    album_tracks(inbox, "Band B", "Second", 1)
    album_tracks(inbox, "Band C", "Third", 1)
    tasks = await run_import(app, admin_client, inbox)
    assert len(tasks) == 3 and {t["status"] for t in tasks} == {"pending"}
    failed_id = tasks[0]["id"]  # interrupted by a restart
    async with db.session() as session:
        await session.execute(
            update(ImportTask).where(ImportTask.id == failed_id).values(status="failed")
        )
        await session.commit()
    before = (await admin_client.get("/api/manage/tasks/counts")).json()

    # Every waiting album of every job (other tests may have left some too).
    skipped = await admin_client.post(
        "/api/manage/tasks/bulk", json={"action": "skip", "status": "pending"}
    )
    assert skipped.json() == {"changed": before["pending"]}
    assert before["pending"] >= 2
    counts = (await admin_client.get("/api/manage/tasks/counts")).json()
    assert (counts["pending"], counts["failed"]) == (0, before["failed"])

    retried = await admin_client.post(
        "/api/manage/tasks/bulk", json={"action": "retry", "status": "failed"}
    )
    assert retried.json()["changed"] >= 1
    await app.state.imports.wait_idle()
    tasks = {
        t["id"]: t
        for j in (await admin_client.get("/api/manage/imports")).json()
        for t in j["tasks"]
    }
    assert tasks[failed_id]["status"] == "pending"  # identified again, waits for a decision

    # A failed album can also be dismissed.
    async with db.session() as session:
        await session.execute(
            update(ImportTask).where(ImportTask.id == failed_id).values(status="failed")
        )
        await session.commit()
    dismissed = await admin_client.post(
        "/api/manage/tasks/bulk", json={"action": "skip", "status": "failed"}
    )
    assert dismissed.json()["changed"] >= 1
    bad = await admin_client.post(
        "/api/manage/tasks/bulk", json={"action": "apply", "status": "pending"}
    )
    assert bad.status_code == 400
