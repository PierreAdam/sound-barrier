"""Permanent deletion of songs / albums from the library: files on disk, then database.

Only files inside their music folder are touched (checked on the real path), and album
folders are removed only when nothing but sidecar files (covers, .nfo, .cue...) is left.
A deleted file's own lyrics / subtitles (same name: `.lrc`, `.srt`, `.vtt`, e.g. an
audiobook's transcript) go with it: they would be of nothing any more.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_manager import files
from app.models import Album, AlbumArtist, Artist, Directory, MusicFolder, Song, SongArtist
from app.scanner.scanner import refresh_derived_data

# Called with the deleted files of one music folder (e.g. ImportManager.forget).
type Forget = Callable[[list[Path], Path], Awaitable[None]]

# Next to an audio file, with its name: its lyrics or subtitles (services/transcripts.py).
COMPANION_SUFFIXES = (".lrc", ".srt", ".vtt")


@dataclass
class DeletionResult:
    songs: int = 0
    files_deleted: int = 0
    files_already_gone: int = 0
    folders_removed: list[str] = field(default_factory=list[str])
    # Folders that changed on disk, to rescan: music folder id -> relative directories.
    directories: dict[int, set[str]] = field(default_factory=dict[int, set[str]])


def _delete_files(plan: list[tuple[Path, Path]]) -> tuple[DeletionResult, dict[Path, list[Path]]]:
    """plan: (music folder root, file). Returns the result and removed folders per root."""
    result = DeletionResult()
    folders: dict[Path, set[Path]] = {}
    for root, path in plan:
        target = files.ensure_within(path, [root])
        if target.exists():
            target.unlink()
            result.files_deleted += 1
        else:
            result.files_already_gone += 1
        for suffix in COMPANION_SUFFIXES:
            companion = files.ensure_within(path.with_suffix(suffix), [root])
            if companion.is_file():
                companion.unlink()
        folders.setdefault(root, set()).add(path.parent)
    removed: dict[Path, list[Path]] = {}
    for root, parents in folders.items():
        # Deepest first, so a disc folder goes before its album folder.
        for folder in sorted(parents, key=lambda p: len(p.parts), reverse=True):
            if folder.exists():
                removed.setdefault(root, []).extend(files.remove_emptied_folder(folder, root))
    return result, removed


async def delete_songs(
    session: AsyncSession, song_ids: list[uuid.UUID], forget: Forget
) -> DeletionResult:
    rows = (
        await session.execute(
            select(Song.id, Song.path, Song.music_folder_id, MusicFolder.path)
            .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
            .where(Song.id.in_(song_ids))
        )
    ).all()
    if not rows:
        return DeletionResult()
    plan = [(Path(root), Path(root) / path) for _, path, _, root in rows]
    result, removed = await asyncio.to_thread(_delete_files, plan)
    result.songs = len(rows)
    for _, path, folder_id, _ in rows:
        result.directories.setdefault(folder_id, set()).add(path.rpartition("/")[0])

    # Database: the songs (stars, play counts, playlist entries go with them), the folders
    # removed from disk, then albums and artists left without any song.
    await session.execute(delete(Song).where(Song.id.in_([r[0] for r in rows])))
    folder_ids = {Path(root): folder_id for _, _, folder_id, root in rows}
    for root, folders in removed.items():
        relative = [folder.relative_to(root).as_posix() for folder in folders]
        await session.execute(
            delete(Directory).where(
                Directory.music_folder_id == folder_ids[root], Directory.path.in_(relative)
            )
        )
        result.folders_removed += relative
    await session.execute(delete(Album).where(~exists().where(Song.album_id == Album.id)))
    await session.execute(
        delete(Artist).where(
            ~or_(
                exists().where(Song.artist_id == Artist.id),
                exists().where(SongArtist.artist_id == Artist.id),
                exists().where(Album.artist_id == Artist.id),
                exists().where(AlbumArtist.artist_id == Artist.id),
            )
        )
    )
    await refresh_derived_data(session)
    by_root: dict[Path, list[Path]] = {}
    for root, path in plan:
        by_root.setdefault(root, []).append(path)
    for root, paths in by_root.items():
        await forget(paths, root)
    return result


async def delete_albums(
    session: AsyncSession, album_ids: list[uuid.UUID], forget: Forget
) -> DeletionResult:
    song_ids = (await session.scalars(select(Song.id).where(Song.album_id.in_(album_ids)))).all()
    return await delete_songs(session, list(song_ids), forget)
