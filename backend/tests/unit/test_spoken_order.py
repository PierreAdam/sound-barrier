from types import SimpleNamespace
from typing import Any, cast

from app.services import music_folders
from app.services.browsing import SongEntry
from app.services.spoken import _order  # pyright: ignore[reportPrivateUsage]


def _chapter(path: str, track: int | None, disc: int | None = None) -> SongEntry:
    song = SimpleNamespace(path=path, track_number=track, disc_number=disc)
    return cast(SongEntry, SimpleNamespace(song=cast(Any, song)))


def _paths(chapters: list[SongEntry]) -> list[str]:
    return [c.song.path for c in _order(music_folders.AUDIOBOOKS, chapters)]


def test_consistent_track_numbers_decide() -> None:
    chapters = [_chapter("b.mp3", 1), _chapter("a.mp3", 2), _chapter("c.mp3", 1, disc=2)]
    assert _paths(chapters) == ["b.mp3", "a.mp3", "c.mp3"]


def test_leftover_track_numbers_fall_back_to_file_names() -> None:
    # A CD rip's numbers: duplicates and numbers above the chapter count.
    chapters = [
        _chapter("Book/CH10 Hallowe'en.mp3", 41),
        _chapter("Book/CH2 The Vanishing Glass.mp3", 29),
        _chapter("Book/CH1 The Boy Who Lived.mp3", 1),
        _chapter("Book/CH6 The Journey.mp3", 1),
    ]
    assert _paths(chapters) == [
        "Book/CH1 The Boy Who Lived.mp3",
        "Book/CH2 The Vanishing Glass.mp3",
        "Book/CH6 The Journey.mp3",
        "Book/CH10 Hallowe'en.mp3",
    ]


def test_missing_track_numbers_fall_back_to_file_names() -> None:
    chapters = [_chapter("02.mp3", None), _chapter("01.mp3", 2), _chapter("10.mp3", 1)]
    assert _paths(chapters) == ["01.mp3", "02.mp3", "10.mp3"]
