import os
from pathlib import Path

import pytest

from app.scanner.walker import ancestors, walk, walk_targets


def _layout(root: Path) -> None:
    for album in ("Artist A/Album 1", "Artist A/Album 2", "Artist B/Album 3"):
        (root / album).mkdir(parents=True)
        (root / album / "01 - Song.mp3").write_bytes(b"x")
    (root / "Artist A" / "Album 1" / "cover.jpg").write_bytes(b"x")
    (root / ".hidden").mkdir()
    (root / "notes.txt").write_text("ignored")


def test_walk_lists_directories_and_files(tmp_path: Path) -> None:
    _layout(tmp_path)
    entries = {e.path: e for e in walk(tmp_path)}
    assert set(entries) == {
        "",
        "Artist A",
        "Artist A/Album 1",
        "Artist A/Album 2",
        "Artist B",
        "Artist B/Album 3",
    }
    album = entries["Artist A/Album 1"]
    assert [f.path for f in album.audio_files] == ["Artist A/Album 1/01 - Song.mp3"]
    assert [f.path for f in album.image_files] == ["Artist A/Album 1/cover.jpg"]
    assert album.parent_path == "Artist A"


def test_walk_without_inode_numbers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SSHFS on Windows reports st_ino = 0 for every directory."""
    _layout(tmp_path)
    real_stat = Path.stat

    def stat_without_inode(self: Path, *args: object, **kwargs: object) -> os.stat_result:
        result = real_stat(self, *args, **kwargs)  # type: ignore[arg-type]
        values = list(result[:10])
        values[1] = 0  # st_ino
        return os.stat_result(values, {"st_mtime_ns": result.st_mtime_ns})

    monkeypatch.setattr(Path, "stat", stat_without_inode)
    assert len(walk(tmp_path)) == 6


def test_walk_targets(tmp_path: Path) -> None:
    _layout(tmp_path)
    (tmp_path / "Artist A" / "stray.mp3").write_bytes(b"x")
    entries = walk_targets(tmp_path, ["Artist A/Album 2", "Gone/Album"])
    # The parents (their own files only), then the target tree; nothing for "Gone".
    assert [e.path for e in entries] == ["", "Artist A", "Artist A/Album 2"]
    assert [f.path for f in entries[1].audio_files] == ["Artist A/stray.mp3"]
    assert [f.path for f in entries[2].audio_files] == ["Artist A/Album 2/01 - Song.mp3"]


def test_ancestors() -> None:
    assert ancestors("a/b/c") == ["", "a", "a/b"]
    assert ancestors("a") == [""]
