from pathlib import Path

from app.library_manager.kind_hints import hint
from tests.audio import make_track


def test_audiobook_words_in_a_folder_name(tmp_path: Path) -> None:
    make_track(tmp_path / "Author - Saga 1-7 Unabridged" / "Book 1" / "01", title="x")
    found = hint(tmp_path / "Author - Saga 1-7 Unabridged")
    assert found is not None
    assert (found.kind, found.reason) == ("audiobook", 'name ("Unabridged")')


def test_podcast_word_in_a_sub_folder(tmp_path: Path) -> None:
    make_track(tmp_path / "Downloads batch" / "My Podcast" / "ep1", title="x")
    found = hint(tmp_path / "Downloads batch")
    assert found is not None and found.kind == "podcast"


def test_m4b_files(tmp_path: Path) -> None:
    folder = tmp_path / "Some Book"
    folder.mkdir()
    (folder / "book.m4b").write_bytes(b"")
    found = hint(folder)
    assert found is not None and (found.kind, found.reason) == ("audiobook", "M4B files")


def test_genre_tag(tmp_path: Path) -> None:
    make_track(tmp_path / "1 THE FIRST BOOK" / "CH01", title="x", genre="Audiobook")
    found = hint(tmp_path / "1 THE FIRST BOOK")
    assert found is not None and (found.kind, found.reason) == ("audiobook", 'genre "Audiobook"')


def test_music_has_no_hint(tmp_path: Path) -> None:
    make_track(tmp_path / "Band" / "Album (2020)" / "01", title="x", genre="Metal")
    assert hint(tmp_path / "Band") is None
