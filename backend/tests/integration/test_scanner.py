import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.core.db import Database
from app.models import Album, Artist, Artwork, Directory, Genre, MusicFolder, Scan, Song
from app.scanner.scanner import SCAN_LOCK_KEY, ScanAlreadyRunningError, run_scan
from tests.audio import COVER_JPG, album_tracks, make_track
from tests.integration.conftest import SubsonicUser

pytestmark = pytest.mark.integration


async def rows[T](db: Database, model: type[T], *where: Any) -> list[T]:
    async with db.session() as session:
        return list((await session.scalars(select(model).where(*where))).all())


async def one[T](db: Database, model: type[T], *where: Any) -> T:
    found = await rows(db, model, *where)
    assert len(found) == 1, found
    return found[0]


async def last_scan(db: Database) -> Scan:
    async with db.session() as session:
        scan = await session.scalar(select(Scan).order_by(Scan.id.desc()).limit(1))
        assert scan is not None
        return scan


def touch_later(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))


async def test_scan_library(db: Database, library: Path) -> None:
    album_tracks(library, "Dethklok", "The Dethalbum", 3, genre="Metal", date="2007-09-25")
    album_tracks(library, "Deaf Election", "Falling in Flames", 2, genre="Metal; Rock")
    (library / "Dethklok" / "The Dethalbum" / "cover.jpg").write_bytes(COVER_JPG.read_bytes())

    await run_scan(db)

    scan = await last_scan(db)
    assert (scan.status, scan.files_seen, scan.added, scan.updated) == ("done", 5, 5, 0)

    dethklok = await one(db, Artist, Artist.name == "Dethklok")
    assert dethklok.album_count == 1
    album = await one(db, Album, Album.name == "The Dethalbum")
    assert album.artist_id == dethklok.id
    assert (album.song_count, album.year, album.sort_name) == (3, 2007, "Dethalbum")
    assert album.duration_ms > 0

    cover = await one(db, Artwork, Artwork.id == album.artwork_id)
    assert (cover.source, cover.path) == ("file", "Dethklok/The Dethalbum/cover.jpg")

    songs = await rows(db, Song, Song.album_id == album.id)
    assert sorted((s.track_number, s.title) for s in songs) == [
        (1, "Track 1"),
        (2, "Track 2"),
        (3, "Track 3"),
    ]
    assert {s.content_type for s in songs} == {"audio/mpeg"}

    assert {g.name for g in await rows(db, Genre)} == {"Metal", "Rock"}

    root = await one(db, Directory, Directory.parent_id.is_(None))
    assert (root.path, root.name) == ("", "Music")
    assert {d.path for d in await rows(db, Directory, Directory.parent_id == root.id)} == {
        "Deaf Election",
        "Dethklok",
    }


async def test_rescan_is_incremental(db: Database, library: Path) -> None:
    tracks = album_tracks(library, "Artist", "Album", 3)
    await run_scan(db)
    ids_before = {s.path: s.id for s in await rows(db, Song)}

    await run_scan(db)
    scan = await last_scan(db)
    assert (scan.added, scan.updated, scan.removed) == (0, 0, 0)

    make_track(tracks[0].with_suffix(""), title="Renamed", artist="Artist", album="Album")
    touch_later(tracks[0])
    await run_scan(db)
    scan = await last_scan(db)
    assert (scan.added, scan.updated) == (0, 1)
    song = await one(db, Song, Song.title == "Renamed")
    assert song.id == ids_before[song.path]

    await run_scan(db, full=True)
    assert (await last_scan(db)).updated == 3
    assert {s.path: s.id for s in await rows(db, Song)} == ids_before


async def test_removed_files_are_soft_deleted_and_restored(db: Database, library: Path) -> None:
    tracks = album_tracks(library, "Artist", "Album", 2)
    album_tracks(library, "Other", "Kept", 1)  # the library never becomes empty
    await run_scan(db)
    song_id = (await one(db, Song, Song.path == "Artist/Album/01 - Track 1.mp3")).id

    backup = tracks[0].read_bytes()
    tracks[0].unlink()
    await run_scan(db)
    assert (await last_scan(db)).removed == 1
    song = await one(db, Song, Song.id == song_id)
    assert song.missing_since is not None
    assert (await one(db, Album, Album.name == "Album")).song_count == 1

    # Whole album gone: album and artist become missing too.
    tracks[1].unlink()
    await run_scan(db)
    assert (await one(db, Album, Album.name == "Album")).missing_since is not None
    assert (await one(db, Artist, Artist.name == "Artist")).missing_since is not None

    # The file comes back: same row, so stars / playlists would survive.
    tracks[0].write_bytes(backup)
    await run_scan(db)
    song = await one(db, Song, Song.id == song_id)
    assert song.missing_since is None
    album = await one(db, Album, Album.name == "Album")
    assert (album.missing_since, album.song_count) == (None, 1)
    assert (await one(db, Artist, Artist.name == "Artist")).missing_since is None


async def test_folder_that_suddenly_looks_empty_is_skipped(db: Database, library: Path) -> None:
    """An empty listing (drive not mounted yet, network glitch) must not hide the library."""
    tracks = album_tracks(library, "Artist", "Album", 2)
    await run_scan(db)
    for track in tracks:
        track.unlink()
    await run_scan(db)
    assert all(s.missing_since is None for s in await rows(db, Song))
    assert (await last_scan(db)).removed == 0


async def test_inaccessible_folder_is_skipped(db: Database, library: Path) -> None:
    album_tracks(library, "Artist", "Album", 2)
    await run_scan(db)
    renamed = library.with_name("unmounted")
    library.rename(renamed)
    try:
        await run_scan(db)
    finally:
        renamed.rename(library)
    assert all(s.missing_since is None for s in await rows(db, Song))
    assert (await last_scan(db)).removed == 0


async def test_untagged_file_and_compilation(db: Database, library: Path) -> None:
    make_track(library / "Misc" / "Some Folder" / "my song")
    for n, artist in enumerate(["Band A", "Band B"], start=1):
        make_track(
            library / "Compilations" / "Hits" / f"{n:02d}",
            title=f"Hit {n}",
            artist=artist,
            album="Hits",
            compilation="1",
        )
    await run_scan(db)

    song = await one(db, Song, Song.path == "Misc/Some Folder/my song.mp3")
    assert song.title == "my song"
    assert (await one(db, Album, Album.id == song.album_id)).name == "Some Folder"
    assert (await one(db, Artist, Artist.id == song.artist_id)).name == "[Unknown Artist]"

    hits = await one(db, Album, Album.name == "Hits")
    assert hits.is_compilation and hits.song_count == 2
    assert (await one(db, Artist, Artist.id == hits.artist_id)).name == "Various Artists"


async def test_name_only_artist_joins_musicbrainz_artist(db: Database, library: Path) -> None:
    make_track(
        library / "A" / "One" / "01",
        title="With id",
        artist="Dethklok",
        album="One",
        musicbrainz_artistid="1afcd689-9be4-4d1a-a9fa-49e086250f51",
    )
    make_track(library / "A" / "Two" / "01", title="Without id", artist="dethklok", album="Two")
    await run_scan(db)
    artist = await one(db, Artist)
    assert artist.match_key == "mbz:1afcd689-9be4-4d1a-a9fa-49e086250f51"
    assert artist.album_count == 2


async def test_embedded_artwork_used_without_folder_image(db: Database, library: Path) -> None:
    make_track(library / "A" / "B" / "01", title="x", artist="A", album="B", picture=True)
    await run_scan(db)
    album = await one(db, Album)
    artwork = await one(db, Artwork, Artwork.id == album.artwork_id)
    assert (artwork.source, artwork.path) == ("embedded", "A/B/01.mp3")


async def test_only_one_scan_at_a_time(db: Database, library: Path) -> None:
    async with db.engine.connect() as connection:
        await connection.execute(text(f"SELECT pg_advisory_lock({SCAN_LOCK_KEY})"))
        with pytest.raises(ScanAlreadyRunningError):
            await run_scan(db)
        await connection.execute(text(f"SELECT pg_advisory_unlock({SCAN_LOCK_KEY})"))


async def test_scan_endpoints(
    client: AsyncClient, db: Database, library: Path, user: SubsonicUser, admin: SubsonicUser
) -> None:
    album_tracks(library, "Artist", "Album", 2)

    data = (await client.get("/rest/startScan", params=user.params())).json()
    assert data["subsonic-response"]["error"]["code"] == 50

    data = (await client.get("/rest/startScan", params=admin.params())).json()
    assert data["subsonic-response"]["scanStatus"]["scanning"] is True

    for _ in range(100):
        status = (await client.get("/rest/getScanStatus", params=user.params())).json()
        if not status["subsonic-response"]["scanStatus"]["scanning"]:
            break
        await asyncio.sleep(0.05)
    scan_status = status["subsonic-response"]["scanStatus"]
    assert scan_status["scanning"] is False
    assert scan_status["count"] == 2
    assert "lastScan" in scan_status
    assert len(await rows(db, MusicFolder)) == 1


async def test_targeted_scan(db: Database, library: Path) -> None:
    kept = album_tracks(library, "Band", "Old Album", 2)
    await run_scan(db)
    folder = await one(db, MusicFolder)

    # A new album, and a change elsewhere that a targeted scan must not see.
    album_tracks(library, "Band", "New Album", 2)
    kept[0].unlink()
    await run_scan(db, targets={folder.id: ["Band/New Album"]})

    scan = await last_scan(db)
    assert (scan.kind, scan.status, scan.files_seen, scan.added) == ("targeted", "done", 2, 2)
    new = await one(db, Album, Album.name == "New Album")
    assert new.song_count == 2
    old = await one(db, Album, Album.name == "Old Album")
    assert old.song_count == 2  # outside the target: untouched
    assert (await one(db, Artist, Artist.name == "Band")).album_count == 2


async def test_targeted_scan_of_a_removed_folder(db: Database, library: Path) -> None:
    album_tracks(library, "Band", "Album", 2)
    album_tracks(library, "Other", "Album", 1)
    await run_scan(db)
    folder = await one(db, MusicFolder)

    for path in (library / "Band" / "Album").iterdir():
        path.unlink()
    (library / "Band" / "Album").rmdir()
    (library / "Band").rmdir()
    await run_scan(db, targets={folder.id: ["Band/Album"]})

    songs = await rows(db, Song, Song.missing_since.is_(None))
    assert [s.path for s in songs] == ["Other/Album/01 - Track 1.mp3"]
    gone = await rows(db, Directory, Directory.missing_since.is_not(None))
    assert sorted(d.path for d in gone) == ["Band", "Band/Album"]
    assert (await one(db, Artist, Artist.name == "Band")).missing_since is not None
