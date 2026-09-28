from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.db import Database
from app.scanner.scanner import run_scan
from tests.audio import album_tracks, make_track
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def search(client: AsyncClient, user: SubsonicUser, **params: str) -> dict[str, Any]:
    response = await client.get("/rest/search3", params=user.params(**params))
    data = response.json()["subsonic-response"]
    assert data["status"] == "ok", data
    return data["searchResult3"]


def names(result: dict[str, Any], kind: str, key: str = "name") -> list[str]:
    return [item[key] for item in result.get(kind, [])]


@pytest.fixture
async def library_content(db: Database, library: Path) -> None:
    album_tracks(library, "Dethklok", "The Dethalbum", 2)
    album_tracks(library, "Émilie Simon", "Végétal", 1)
    make_track(
        library / "Deaf Election" / "Falling in Flames" / "01 - Sleeper",
        title="Sleeper",
        artist="Deaf Election",
        albumartist="Deaf Election",
        album="Falling in Flames",
    )
    await run_scan(db)


async def test_search3(client: AsyncClient, user: SubsonicUser, library_content: None) -> None:
    result = await search(client, user, query="deth")
    assert names(result, "artist") == ["Dethklok"]
    assert names(result, "album") == ["The Dethalbum"]  # found through its artist too
    assert names(result, "song", "title") == ["Track 1", "Track 2"]

    # Accents, case and word order do not matter.
    result = await search(client, user, query="EMILIE vegetal")
    assert names(result, "album") == ["Végétal"]
    assert names(result, "artist") == []  # the artist name has no "vegetal"
    # A song is found by title, artist or album words.
    assert names(await search(client, user, query="flames sleeper"), "song", "title") == ["Sleeper"]
    nothing = await search(client, user, query="nothing like this")
    assert (names(nothing, "artist"), names(nothing, "album"), names(nothing, "song", "title")) == (
        [],
        [],
        [],
    )


async def test_empty_query_lists_everything_by_pages(
    client: AsyncClient, user: SubsonicUser, library_content: None
) -> None:
    """Clients synchronizing the whole library send an empty query."""
    everything = await search(client, user, query='""', songCount="100")
    assert len(everything["song"]) == 4
    assert len(everything["album"]) == 3
    page = await search(
        client, user, query="", songCount="2", songOffset="2", artistCount="0", albumCount="0"
    )
    assert (page["artist"], page["album"]) == ([], [])
    assert [s["id"] for s in page["song"]] == [s["id"] for s in everything["song"][2:]]
