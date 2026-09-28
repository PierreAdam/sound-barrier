from pathlib import Path

import pytest

from app.core.text import index_letter, normalize, strip_articles
from app.scanner.tags import (
    Contributor,
    _partial_date,  # pyright: ignore[reportPrivateUsage]
    build_track_tags,
    extract_picture,
    read_audio_file,
)
from tests.audio import COVER_JPG, FORMATS, make_track


@pytest.mark.parametrize("fmt", FORMATS)
def test_common_tags_in_every_format(tmp_path: Path, fmt: str) -> None:
    path = make_track(
        tmp_path / "track",
        fmt=fmt,
        title="Sleeper",
        artist="Deaf Election",
        albumartist="Deaf Election",
        album="Falling in Flames",
        tracknumber="3/10",
        discnumber="1/2",
        date="2012-05-11",
        genre="Metal",
        musicbrainz_albumid="e2799dc9-e1f2-4534-b579-96dde8043c61",
        releasetype="album",
    )
    audio = read_audio_file(path)
    assert audio is not None
    tags = audio.tags
    assert tags.title == "Sleeper"
    assert tags.artists == ["Deaf Election"]
    assert tags.display_artist == "Deaf Election"
    assert tags.album == "Falling in Flames"
    assert tags.album_artists == ["Deaf Election"]
    assert (tags.track_number, tags.track_total) == (3, 10)
    assert (tags.disc_number, tags.disc_total) == (1, 2)
    assert tags.date == "2012-05-11"
    assert tags.year == 2012
    assert tags.genres == ["Metal"]
    assert tags.mbz_album_id == "e2799dc9-e1f2-4534-b579-96dde8043c61"
    assert tags.release_types == ["album"]
    assert not tags.has_picture
    assert 900 <= audio.info.duration_ms <= 1200
    assert audio.info.channels == 2


@pytest.mark.parametrize("fmt", FORMATS)
def test_embedded_picture(tmp_path: Path, fmt: str) -> None:
    path = make_track(tmp_path / "track", fmt=fmt, title="x", picture=True)
    audio = read_audio_file(path)
    assert audio is not None and audio.tags.has_picture
    picture = extract_picture(path)
    assert picture == (COVER_JPG.read_bytes(), "image/jpeg")


@pytest.mark.parametrize("fmt", ["mp3", "flac", "m4a"])
def test_multi_valued_artists(tmp_path: Path, fmt: str) -> None:
    path = make_track(
        tmp_path / "track",
        fmt=fmt,
        title="Duet",
        artist="Alice feat. Bob",
        artists=["Alice", "Bob"],
        musicbrainz_artistid=["id-alice", "id-bob"],
    )
    audio = read_audio_file(path)
    assert audio is not None
    assert audio.tags.artists == ["Alice", "Bob"]
    assert audio.tags.artist_mbz_ids == ["id-alice", "id-bob"]
    assert audio.tags.display_artist == "Alice feat. Bob"


def test_raw_tag_mapping() -> None:
    tags = build_track_tags(
        {
            "title": ["  Song  "],
            "genre": ["Rock; Pop", "Rock"],
            "performer:guitar": ["Carol"],
            "composer": ["Dave"],
            "bpm": ["0"],
            "compilation": ["1"],
            "explicit": ["1"],
            "replaygain_track_gain": ["-7.25 dB"],
            "originalyear": ["1999"],
        },
        has_picture=False,
    )
    assert tags.title == "Song"
    assert tags.genres == ["Rock", "Pop"]
    assert Contributor("Carol", "performer", "guitar") in tags.contributors
    assert tags.composers == ["Dave"]
    assert tags.bpm is None
    assert tags.compilation
    assert tags.explicit_status == "explicit"
    assert tags.replaygain_track_gain == -7.25
    assert tags.year == 1999


def test_unreadable_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.mp3"
    path.write_bytes(b"not audio")
    assert read_audio_file(path) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2012", "2012"),
        ("2012-05", "2012-05"),
        ("2012-05-11T10:00:00", "2012-05-11"),
        ("nope", None),
        (None, None),
    ],
)
def test_partial_date(value: str | None, expected: str | None) -> None:
    assert _partial_date(value) == expected


def test_text_helpers() -> None:
    assert normalize("  Beyoncé   Knowles ") == "beyonce knowles"
    assert strip_articles("The Dethalbum") == "Dethalbum"
    assert strip_articles("The") == "The"
    assert strip_articles("Theatre") == "Theatre"
    assert index_letter("Émilie") == "E"
    assert index_letter("2Pac") == "#"
