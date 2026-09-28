"""The beets tagger, offline: MusicBrainz is replaced by a fake metadata source."""

import os
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import mutagen
import pytest
from beets import metadata_plugins
from beets.autotag.hooks import AlbumInfo, TrackInfo

from app.library_manager import files
from app.library_manager.beets_tagger import BeetsTagger
from app.library_manager.tagger import (
    ImportMode,
    ImportOptions,
    Recommendation,
    TaggerError,
    TaggerLibrary,
)
from tests.audio import make_track

RELEASE_ID = "11111111-2222-3333-4444-555555555555"


def _release() -> AlbumInfo:
    tracks = [
        TrackInfo(
            title=f"Track {n}",
            track_id=f"track-{n}",
            artist="Dethklok",
            length=1.0,
            index=n,
            medium=1,
            medium_index=n,
        )
        for n in (1, 2)
    ]
    return AlbumInfo(
        tracks=tracks,
        album="Dethalbum IV",
        album_id=RELEASE_ID,
        artist="Dethklok",
        artist_id="artist-1",
        year=2023,
        country="XW",
        media="Digital Media",
        mediums=1,
        data_source="MusicBrainz",
    )


@pytest.fixture
def lookups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records the searches; every search finds the release."""
    calls: list[str] = []

    def candidates(items: Any, artist: str, album: str, va_likely: bool) -> Iterator[AlbumInfo]:
        calls.append(f"search {artist} / {album}")
        yield _release()

    def albums_for_ids(ids: list[str]) -> Iterator[AlbumInfo]:
        calls.append(f"ids {ids}")
        yield from (_release() for i in ids if RELEASE_ID in i)

    monkeypatch.setattr(metadata_plugins, "candidates", candidates)
    monkeypatch.setattr(metadata_plugins, "albums_for_ids", albums_for_ids)
    return calls


@pytest.fixture
def tagger(tmp_path: Path) -> BeetsTagger:
    beets_dir = tmp_path / "beets"
    beets_dir.mkdir()
    # No fetchart / embedart: they would download covers.
    (beets_dir / "config.yaml").write_text("plugins: []\n")
    return BeetsTagger(beets_dir)


@pytest.fixture
def download(tmp_path: Path) -> Path:
    """An album tagged like the Dethalbum IV download."""
    folder = tmp_path / "downloads" / "Dethklok (FLAC)" / "2023 - Dethalbum IV"
    for n in (1, 2):
        make_track(
            folder / f"{n:02d} - Track {n}",
            title=f"Track {n}",
            artist="Metalocalypse: Dethklok",
            albumartist="Metalocalypse: Dethklok",
            album="Dethalbum Iv",
            tracknumber=f"{n}/2",
        )
    return folder


def test_identify_and_search(tagger: BeetsTagger, download: Path, lookups: list[str]) -> None:
    items = files.read_items(download)
    found = tagger.identify(items)
    assert lookups == ["search Metalocalypse: Dethklok / Dethalbum Iv"]
    best = found.candidates[0]
    assert (best.artist, best.album, best.year, best.id) == (
        "Dethklok",
        "Dethalbum IV",
        2023,
        RELEASE_ID,
    )
    assert best.url == f"https://musicbrainz.org/release/{RELEASE_ID}"
    assert [t.item_index for t in best.tracks] == [0, 1]
    assert found.recommendation is not Recommendation.NONE

    tagger.search(items, artist="Dethklok")  # album taken from the current tags
    assert lookups[-1] == "search Dethklok / Dethalbum Iv"
    by_url = tagger.search(items, release_id=f"https://musicbrainz.org/release/{RELEASE_ID}")
    assert lookups[-1].startswith("ids ")
    assert [c.id for c in by_url.candidates] == [RELEASE_ID]


def test_apply_candidate(
    tagger: BeetsTagger, download: Path, tmp_path: Path, lookups: list[str]
) -> None:
    items = files.read_items(download)
    candidate = tagger.identify(items).candidates[0]
    library = tmp_path / "library"
    library.mkdir()

    paths = tagger.apply(items, candidate, library, ImportOptions())

    assert [p.relative_to(library).as_posix() for p in paths] == [
        "Dethklok/Dethalbum IV/01 - Track 1.mp3",
        "Dethklok/Dethalbum IV/02 - Track 2.mp3",
    ]
    tags: Any = mutagen.File(paths[0], easy=True)
    assert tags["albumartist"] == ["Dethklok"]
    assert tags["musicbrainz_albumid"] == [RELEASE_ID]
    # Copy mode: the download keeps its files and tags.
    source: Any = mutagen.File(files.read_items(download)[0].path, easy=True)
    assert source["albumartist"] == ["Metalocalypse: Dethklok"]

    # Imported once: beets refuses it again.
    with pytest.raises(TaggerError, match="already in beets' library"):
        tagger.apply(items, candidate, library, ImportOptions())

    # After a deletion in Sound-Barrier, beets forgets the album: it can come back.
    for path in paths:
        path.unlink()
    # From another thread than the import (beets keeps the music folder per context).
    forget_thread = threading.Thread(target=tagger.forget, args=(paths, library))
    forget_thread.start()
    forget_thread.join()
    assert len(tagger.apply(items, candidate, library, ImportOptions())) == 2


def test_apply_as_is(tagger: BeetsTagger, download: Path, tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    paths = tagger.apply(files.read_items(download), None, library, ImportOptions())
    # beets' path format with the current tags (":" is not allowed in file names).
    assert paths[0].relative_to(library).as_posix() == (
        "Metalocalypse_ Dethklok/Dethalbum Iv/01 - Track 1.mp3"
    )


def test_release_gone(
    tagger: BeetsTagger, download: Path, tmp_path: Path, lookups: list[str]
) -> None:
    items = files.read_items(download)
    candidate = tagger.identify(items).candidates[0]
    candidate.id = "99999999-0000-0000-0000-000000000000"  # no longer found
    with pytest.raises(TaggerError, match="not found again"):
        tagger.apply(items, candidate, tmp_path, ImportOptions())


def test_adopt_in_place(tagger: BeetsTagger, tmp_path: Path, lookups: list[str]) -> None:
    """Library files not in beets yet: matched, tagged where they are, never moved."""
    library = tmp_path / "library"
    album = library / "Metalocalypse_ Dethklok" / "Dethalbum Iv"
    for n in (1, 2):
        make_track(
            album / f"0{n} - Track {n}",
            title=f"Track {n}",
            artist="Metalocalypse: Dethklok",
            albumartist="Metalocalypse: Dethklok",
            album="Dethalbum Iv",
            tracknumber=f"{n}/2",
        )
    before = sorted(p.name for p in album.iterdir())
    assert tagger.library(library) == TaggerLibrary(0, set(), [])

    items = files.read_items(album)
    candidate = tagger.identify(items).candidates[0]
    paths = tagger.apply(items, candidate, library, ImportOptions(mode=ImportMode.IN_PLACE))

    assert paths == [album / "01 - Track 1.mp3", album / "02 - Track 2.mp3"]
    assert sorted(p.name for p in album.iterdir()) == before  # nothing moved or renamed
    tags: Any = mutagen.File(paths[0], easy=True)
    assert tags["albumartist"] == ["Dethklok"]  # tags written in place
    known = tagger.library(library)
    assert known is not None
    assert known.albums == 1
    assert known.paths == {
        "Metalocalypse_ Dethklok/Dethalbum Iv/01 - Track 1.mp3",
        "Metalocalypse_ Dethklok/Dethalbum Iv/02 - Track 2.mp3",
    }

    paths[1].unlink()  # deleted outside Sound-Barrier
    known = tagger.library(library)
    assert known is not None and known.missing == [
        "Metalocalypse_ Dethklok/Dethalbum Iv/02 - Track 2.mp3"
    ]
    assert tagger.forget_missing(library) == 1
    known = tagger.library(library)
    assert known is not None and (len(known.paths), known.missing) == (1, [])


def test_penalties_explain_the_match(
    tagger: BeetsTagger, download: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What `beet import` shows: why a candidate is not 100 %, and what differs."""
    release = _release()
    release.tracks[1].length = 300.0  # the second file is much shorter

    def candidates(*_: Any) -> Iterator[AlbumInfo]:
        yield release

    monkeypatch.setattr(metadata_plugins, "candidates", candidates)
    candidate = tagger.identify(files.read_items(download)).candidates[0]

    by_key = {p.key: p for p in candidate.penalties}
    artist = by_key["artist"]
    assert (artist.label, artist.current, artist.proposed) == (
        "Album artist",
        "Metalocalypse: Dethklok",
        "Dethklok",
    )
    assert by_key["tracks"].detail == "1 of 2: duration"
    assert [t.issues for t in candidate.tracks] == [[], ["duration"]]
    # The shares add up to what the match lacks.
    assert abs(sum(p.share for p in candidate.penalties) - candidate.distance) < 0.001
    assert candidate.penalties == sorted(candidate.penalties, key=lambda p: -p.share)


def test_write_tags_keeps_beets_in_sync(
    tagger: BeetsTagger, download: Path, tmp_path: Path, lookups: list[str]
) -> None:
    from beets.dbcore.query import PathQuery

    from app.library_manager.tag_files import TagChange

    library = tmp_path / "library"
    library.mkdir()
    items = files.read_items(download)
    paths = tagger.apply(items, tagger.identify(items).candidates[0], library, ImportOptions())
    tagger.write_tags([TagChange(paths[0], {"title": "Edited", "year": 1999})], library)

    tags: Any = mutagen.File(paths[0], easy=True)
    assert tags["title"] == ["Edited"]
    lib = tagger._library(library)  # pyright: ignore[reportPrivateUsage]
    (item,) = lib.items(PathQuery("path", os.fsencode(paths[0])))
    assert (item.title, item.year) == ("Edited", 1999)
    assert item.get_album().year == 1999  # the album row follows
    assert (item.month, item.day) == (0, 0)  # the old date no longer applies
