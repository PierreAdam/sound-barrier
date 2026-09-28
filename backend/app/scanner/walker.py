"""Filesystem walk of a music folder. Blocking: run it in a thread."""

import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.scanner.formats import AUDIO_CONTENT_TYPES, IMAGE_CONTENT_TYPES, suffix_of

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def mtime_of(stat: os.stat_result) -> datetime:
    """Exact to the microsecond (the precision Postgres stores), so values compare equal."""
    return _EPOCH + timedelta(microseconds=stat.st_mtime_ns // 1000)


@dataclass(frozen=True)
class FileEntry:
    path: str  # relative to the music folder, "/" separated
    size: int
    mtime: datetime


@dataclass
class DirectoryEntry:
    path: str  # relative to the music folder, "" for the root
    name: str
    mtime: datetime
    audio_files: list[FileEntry] = field(default_factory=list[FileEntry])
    image_files: list[FileEntry] = field(default_factory=list[FileEntry])

    @property
    def parent_path(self) -> str | None:
        if self.path == "":
            return None
        return self.path.rpartition("/")[0]


def directory_identity(path: Path, stat: os.stat_result) -> tuple[int, int] | str:
    """Identifies a directory to detect symlink loops.

    Some network filesystems (e.g. SSHFS on Windows) report inode 0 for everything; the
    real path is used instead there.
    """
    if stat.st_ino:
        return (stat.st_dev, stat.st_ino)
    return os.path.normcase(os.path.realpath(path))


def walk(root: Path, start: str = "", *, recursive: bool = True) -> list[DirectoryEntry]:
    """Every directory under `root` (root included), parents before children.

    `start` (relative, "/" separated) walks only that sub-directory (paths stay relative
    to `root`); `recursive=False` lists only the starting directory itself.
    Hidden entries (starting with ".") are skipped. Directories are listed even when
    they contain no audio, so folder browsing matches the disk.
    """
    directories: list[DirectoryEntry] = []
    pending: deque[tuple[Path, str]] = deque([(root / start if start else root, start)])
    visited: set[tuple[int, int] | str] = set()  # guards against symlink loops
    while pending:
        current, rel = pending.popleft()
        try:
            stat = current.stat()
            entries = sorted(os.scandir(current), key=lambda e: e.name.casefold())
        except OSError as error:
            logger.warning("Cannot read directory %s: %s", current, error)
            continue
        identity = directory_identity(current, stat)
        if identity in visited:
            logger.warning("Skipping %s: already visited (symlink loop?)", current)
            continue
        visited.add(identity)
        directory = DirectoryEntry(rel, current.name if rel else "", mtime_of(stat))
        directories.append(directory)
        for entry in entries:
            if entry.name.startswith("."):
                continue
            child_rel = f"{rel}/{entry.name}" if rel else entry.name
            try:
                if entry.is_dir(follow_symlinks=True):
                    if recursive:
                        pending.append((Path(entry.path), child_rel))
                    continue
                if not entry.is_file(follow_symlinks=True):
                    continue
                suffix = suffix_of(entry.name)
                if suffix in AUDIO_CONTENT_TYPES:
                    target = directory.audio_files
                elif suffix in IMAGE_CONTENT_TYPES:
                    target = directory.image_files
                else:
                    continue
                file_stat = entry.stat(follow_symlinks=True)
            except OSError as error:
                logger.warning("Cannot read %s: %s", entry.path, error)
                continue
            target.append(FileEntry(child_rel, file_stat.st_size, mtime_of(file_stat)))
    return directories


def ancestors(path: str) -> list[str]:
    """Relative paths of the parents of `path`, root ("") first: "a/b/c" -> "", "a", "a/b"."""
    parts = path.split("/") if path else []
    return ["/".join(parts[:i]) for i in range(len(parts))]


def is_within(path: str, target: str) -> bool:
    """`path` is `target` or below it (relative paths, "/" separated)."""
    return path == target or path.startswith(f"{target}/")


def walk_targets(root: Path, targets: list[str]) -> list[DirectoryEntry]:
    """What a scan of `targets` only (sub-directories of `root`) needs: each target's
    parents (their own files only) then the target's whole tree, parents before
    children. A target (or parent) that no longer exists is simply absent."""
    found: dict[str, DirectoryEntry] = {}
    for target in sorted(set(targets)):
        chain_exists = True
        for parent in ancestors(target):
            if parent not in found:
                listed = walk(root, parent, recursive=False) if _is_dir(root, parent) else []
                if not listed:
                    chain_exists = False
                    break
                found[parent] = listed[0]
        if chain_exists and _is_dir(root, target):
            for entry in walk(root, target):
                found.setdefault(entry.path, entry)
    # Parents before children, as `walk` returns them.
    return sorted(found.values(), key=lambda e: (e.path.count("/") + bool(e.path), e.path))


def _is_dir(root: Path, relative: str) -> bool:
    return (root / relative if relative else root).is_dir()
