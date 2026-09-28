from pathlib import Path

import pytest

from app.library_manager import files


def test_safe_component() -> None:
    assert files.safe_component('AC/DC: "Live"?', "x") == "AC_DC_ _Live__"
    assert files.safe_component("  Album.  ", "x") == "Album"
    assert files.safe_component("...", "Unknown") == "Unknown"


def test_ensure_within(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    (inbox / "a").mkdir(parents=True)
    # The path keeps the configured form (not the real / UNC one), normalized.
    assert files.ensure_within(inbox / "a", [inbox]) == inbox / "a"
    assert files.ensure_within(inbox / "a" / ".." / "a", [inbox]) == inbox / "a"
    assert files.ensure_within(inbox, [inbox]) == inbox
    for outside in (tmp_path, inbox / ".." / "other", tmp_path / "inbox-other"):
        with pytest.raises(files.OutsideAllowedFolderError):
            files.ensure_within(outside, [inbox])


def test_find_album_folders(tmp_path: Path) -> None:
    for folder in ("A/Album 1", "A/Album 2/CD1", "B/Album 3", "B/.hidden"):
        (tmp_path / folder).mkdir(parents=True)
    for song in (
        "A/Album 1/01.mp3",
        "A/Album 2/CD1/01.flac",
        "B/Album 3/01.m4a",
        "B/.hidden/x.mp3",
    ):
        (tmp_path / song).write_bytes(b"x")
    (tmp_path / "B" / "notes.txt").write_text("not audio")
    found = [p.relative_to(tmp_path).as_posix() for p in files.find_album_folders(tmp_path)]
    assert found == ["A/Album 1", "A/Album 2/CD1", "B/Album 3"]


def test_remove_emptied_folder(tmp_path: Path) -> None:
    album = tmp_path / "Artist" / "Album"
    album.mkdir(parents=True)
    (album / "cover.jpg").write_bytes(b"x")
    (album / "album.nfo").write_text("x")
    removed = files.remove_emptied_folder(album, tmp_path)
    assert removed == [album, album.parent]  # the artist folder became empty too
    assert tmp_path.exists()


def test_remove_emptied_folder_keeps_unknown_files(tmp_path: Path) -> None:
    album = tmp_path / "Artist" / "Album"
    album.mkdir(parents=True)
    (album / "booklet.pdf").write_bytes(b"x")
    assert files.remove_emptied_folder(album, tmp_path) == []
    assert (album / "booklet.pdf").exists()
