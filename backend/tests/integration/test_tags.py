"""Tag editor (admins)."""

from pathlib import Path
from typing import Any

import mutagen
import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import Database
from app.models import Album
from app.scanner.scanner import run_scan
from tests.audio import make_track
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration


@pytest.fixture
async def album(db: Database, library: Path) -> tuple[str, list[Path]]:
    paths = [
        make_track(
            library / "Metalocalypse_ Dethklok" / "Dethalbum Iv" / f"0{n} - Track {n}",
            title=f"Track {n}",
            artist="Metalocalypse: Dethklok",
            albumartist="Metalocalypse: Dethklok",
            album="Dethalbum Iv",
            tracknumber=f"{n}/2",
            date="2023",
        )
        for n in (1, 2)
    ]
    await run_scan(db)
    async with db.session() as session:
        album_id = await session.scalar(select(Album.id).where(Album.name == "Dethalbum Iv"))
    return str(album_id), paths


async def test_edit_tags(
    app: FastAPI, admin: SubsonicUser, client: AsyncClient, album: tuple[str, list[Path]]
) -> None:
    album_id, paths = album
    async with signed_in(app, admin) as web:
        tags = (await web.get(f"/api/albums/{album_id}/tags")).json()
        assert (tags["album"], tags["albumArtist"], tags["year"]) == (
            "Dethalbum Iv",
            "Metalocalypse: Dethklok",
            2023,
        )
        assert [t["title"] for t in tags["tracks"]] == ["Track 1", "Track 2"]

        # Nothing changed: nothing written.
        assert (await web.put(f"/api/albums/{album_id}/tags", json=tags)).json()["files"] == 0

        tags["album"] = "Dethalbum IV"
        tags["albumArtist"] = "Dethklok"
        tags["tracks"][1]["title"] = "Crush The Industry"
        saved = (await web.put(f"/api/albums/{album_id}/tags", json=tags)).json()
    assert saved["files"] == 2

    first: Any = mutagen.File(paths[0], easy=True)
    second: Any = mutagen.File(paths[1], easy=True)
    assert (first["album"], first["albumartist"], first["title"]) == (
        ["Dethalbum IV"],
        ["Dethklok"],
        ["Track 1"],
    )
    assert second["title"] == ["Crush The Industry"]
    # Already in the library (a new album: its name and artist changed).
    new_id = saved["albumId"]
    assert new_id != album_id
    data = (await client.get("/rest/getAlbum", params=admin.params(id=new_id))).json()
    edited = data["subsonic-response"]["album"]
    assert (edited["name"], edited["artist"]) == ("Dethalbum IV", "Dethklok")
    assert [s["title"] for s in edited["song"]] == ["Track 1", "Crush The Industry"]


async def test_tag_editor_is_for_admins(
    app: FastAPI, user: SubsonicUser, album: tuple[str, list[Path]]
) -> None:
    album_id, _ = album
    async with signed_in(app, user) as web:
        assert (await web.get(f"/api/albums/{album_id}/tags")).status_code == 403
