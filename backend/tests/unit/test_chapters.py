"""Chapters written into audio files, read back by the scanner."""

import shutil
from pathlib import Path

import pytest

from app.library_manager.chapters import Chapter, ChapterWriteError, write
from app.scanner.tags import read_audio_file
from tests.audio import FIXTURES, make_track

CHAPTERS = [
    Chapter(0, "Opening Credits"),
    Chapter(300, "Part I = Chapter 1; #1"),  # characters ffmpeg's metadata format escapes
    Chapter(700, "Chapter 2"),
]


def _read(path: Path) -> list[tuple[int, str]]:
    audio = read_audio_file(path)
    assert audio is not None
    return [(c.start_ms, c.title) for c in audio.chapters]


@pytest.mark.parametrize(
    "fmt",
    [
        "mp3",
        pytest.param(
            "m4a", marks=pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="no ffmpeg")
        ),
    ],
)
def test_write_and_replace(tmp_path: Path, fmt: str) -> None:
    path = make_track(tmp_path / "book", fmt=fmt, album="A Book", artist="An Author", picture=True)
    write(path, CHAPTERS, 1000)
    assert _read(path) == [(c.start_ms, c.title) for c in CHAPTERS]
    audio = read_audio_file(path)
    assert audio is not None
    assert (audio.tags.album, audio.tags.has_picture) == ("A Book", True)  # tags kept

    write(path, [Chapter(0, "A"), Chapter(500, "B")], 1000)  # replaced, not added
    assert _read(path) == [(0, "A"), (500, "B")]


def test_needs_two_chapters_and_a_known_format(tmp_path: Path) -> None:
    mp3 = make_track(tmp_path / "one", fmt="mp3")
    with pytest.raises(ChapterWriteError):
        write(mp3, [Chapter(0, "Only one")], 1000)
    flac = tmp_path / "book.flac"
    shutil.copyfile(FIXTURES / "silence.flac", flac)
    with pytest.raises(ChapterWriteError, match="MP3 and M4A"):
        write(flac, CHAPTERS, 1000)
