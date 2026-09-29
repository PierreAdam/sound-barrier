from pathlib import Path

import pytest

from app.library_manager.spoken_review import clean_chapter, clean_title, find_units
from tests.audio import make_track


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("3 HARRY POTTER AND THE PRISONER OF AZKABAN", "Harry Potter and the Prisoner of Azkaban"),
        (
            "HP03: Harry Potter And The Prisoner Of Azkaban",
            "Harry Potter And The Prisoner Of Azkaban",
        ),
        ("The Hobbit (Unabridged) [MP3 64kbps]", "The Hobbit"),
        ("1984", "1984"),
        ("Dune Audiobook", "Dune"),
    ],
)
def test_clean_title(raw: str, clean: str) -> None:
    assert clean_title(raw) == clean


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("CH01 OWL POST", "Owl Post"),
        ("Chapter 01 - The Boy Who Lived_01", "The Boy Who Lived"),
        ("Chapter 01 - The Worst Birthday 01", "The Worst Birthday"),
        (
            "Carl's Doomsday Scenario: Dungeon Crawler Carl, Book 2",
            "Carl's Doomsday Scenario: Dungeon Crawler Carl, Book 2",
        ),
        ("Track 3. Hello", "Hello"),
        ("Chapter 3", "Chapter 3"),
        ("1984", "1984"),
    ],
)
def test_clean_chapter(raw: str, clean: str) -> None:
    assert clean_chapter(raw) == clean


def test_disc_folders_belong_to_their_book(tmp_path: Path) -> None:
    for folder in (
        "Series/Book 1/CD1",
        "Series/Book 1/CD 2",
        "Series/Book 2",
        "Series/Book 3/Part 1",
    ):
        make_track(tmp_path / folder / "01", title="x")
    units = find_units(tmp_path / "Series")
    names = [[p.relative_to(tmp_path).as_posix() for p in unit] for unit in units]
    assert sorted(names) == [
        ["Series/Book 1", "Series/Book 1/CD1", "Series/Book 1/CD 2"],
        ["Series/Book 2"],
        ["Series/Book 3", "Series/Book 3/Part 1"],
    ]


@pytest.mark.parametrize(
    ("title", "series", "clean"),
    [
        (
            "Harry Potter and the Prisoner of Azkaban, Book 3",
            "Harry Potter",
            "Harry Potter and the Prisoner of Azkaban",
        ),
        (
            "Carl's Doomsday Scenario: Dungeon Crawler Carl, Book 2",
            "Dungeon Crawler Carl",
            "Carl's Doomsday Scenario",
        ),
        ("The Way of Kings (Book 1)", "The Stormlight Archive", "The Way of Kings"),
        ("Dune", None, "Dune"),
    ],
)
def test_audible_titles_without_their_series(title: str, series: str | None, clean: str) -> None:
    from app.external.books import without_series

    assert without_series(title, series) == clean
