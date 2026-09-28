"""File-system helpers for library management. Blocking: call them in a thread."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.library_manager.tagger import ItemInfo
from app.scanner.formats import AUDIO_CONTENT_TYPES, IMAGE_CONTENT_TYPES, suffix_of
from app.scanner.tags import read_audio_file

# Files that may stay in an album folder once its songs are deleted; the folder is then
# removed with them. Anything else (unknown files, subfolders) keeps the folder.
SIDECAR_SUFFIXES = frozenset(IMAGE_CONTENT_TYPES) | {
    "nfo",
    "cue",
    "log",
    "m3u",
    "m3u8",
    "txt",
    "accurip",
    "sfv",
    "md5",
}

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class OutsideAllowedFolderError(Exception):
    pass


def real(path: str | Path) -> Path:
    return Path(os.path.realpath(path))


def ensure_within(path: str | Path, roots: list[Path]) -> Path:
    """`path` (absolute, normalized) if it is inside one of `roots`, else
    OutsideAllowedFolderError: guards every path received from the web UI.

    Containment is checked on the real paths (symlinks and `..` resolved), but the path
    returned keeps the form of the configured root: on Windows the real path of a mapped
    network drive (W:\\...) is its UNC form (\\\\server\\...), which should not leak.
    """
    logical = Path(os.path.normpath(os.path.abspath(path)))
    target = real(logical)
    for root in roots:
        real_root = real(root)
        if target == real_root or target.is_relative_to(real_root):
            return logical
    raise OutsideAllowedFolderError(str(path))


def is_audio(path: Path) -> bool:
    return suffix_of(path.name) in AUDIO_CONTENT_TYPES


def safe_component(value: str, fallback: str) -> str:
    """A file / folder name valid on every OS (no separators, no trailing dot or space)."""
    cleaned = _UNSAFE.sub("_", value).strip().rstrip(". ")
    return (cleaned or fallback)[:180]


@dataclass(frozen=True)
class FolderEntry:
    name: str
    path: str
    is_dir: bool
    audio_files: int  # direct audio files (folders) / 1 or 0 (files)
    size: int  # bytes (files only)


def list_folder(folder: Path) -> list[FolderEntry]:
    """Visible sub-folders then files of `folder`, sorted by name."""
    entries: list[FolderEntry] = []
    for entry in sorted(os.scandir(folder), key=lambda e: (not e.is_dir(), e.name.casefold())):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            try:
                count = sum(1 for child in os.scandir(entry.path) if is_audio(Path(child.name)))
            except OSError:
                count = 0
            entries.append(FolderEntry(entry.name, entry.path, True, count, 0))
        elif entry.is_file():
            path = Path(entry.path)
            entries.append(
                FolderEntry(
                    entry.name, entry.path, False, int(is_audio(path)), entry.stat().st_size
                )
            )
    return entries


def find_album_folders(root: Path) -> list[Path]:
    """`root` and every sub-folder that directly contains audio files (one album each)."""
    albums: list[Path] = []
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        if any(is_audio(Path(name)) for name in files):
            albums.append(Path(current))
    return albums


def read_items(folder: Path) -> list[ItemInfo]:
    """The audio files directly in `folder`, with their current tags."""
    items: list[ItemInfo] = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
        if not path.is_file() or not is_audio(path):
            continue
        audio = read_audio_file(path)
        if audio is None:
            continue
        tags = audio.tags
        items.append(
            ItemInfo(
                path=str(path),
                title=tags.title,
                artist=tags.display_artist,
                album=tags.album,
                album_artist=tags.display_album_artist,
                track=tags.track_number,
                disc=tags.disc_number,
                year=tags.year,
                duration_ms=audio.info.duration_ms,
            )
        )
    return items


def remove_emptied_folder(folder: Path, stop_at: Path) -> list[Path]:
    """After deleting songs: removes `folder` if only sidecar files remain in it (covers,
    .nfo, .cue...), then its parents up to `stop_at` (excluded) while they are empty.
    Returns the removed folders."""
    removed: list[Path] = []
    current = folder
    stop = real(stop_at)
    while real(current) != stop and real(current).is_relative_to(stop):
        try:
            children = list(current.iterdir())
        except OSError:
            break
        if any(c.is_dir() or suffix_of(c.name) not in SIDECAR_SUFFIXES for c in children):
            break
        for child in children:
            child.unlink()
        current.rmdir()
        removed.append(current)
        current = current.parent
    return removed
