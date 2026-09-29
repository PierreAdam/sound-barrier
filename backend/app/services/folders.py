"""Folder browsing (Subsonic getIndexes, getMusicDirectory, getAlbumList, search2): the
library as its directories on disk, for clients that browse by folders (e.g. DSub).

Each music folder has a root directory row (path ""); its sub-directories are the index
("artists"). Albums found by tags are given as the directory of their first song.
"""

import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize
from app.models import Album, AppUser, Directory, Scan, Song
from app.services import browsing
from app.services.browsing import AlbumEntry, SongEntry


@dataclass
class FolderEntry:
    directory: Directory
    album: AlbumEntry | None = None  # when the folder is (the start of) an album


@dataclass
class DirectoryListing:
    directory: Directory
    parent_id: uuid.UUID | None  # None for a music folder's root (not browsable above)
    folders: list[Directory] = field(default_factory=list[Directory])
    songs: list[SongEntry] = field(default_factory=list[SongEntry])


def _present(folder_ids: list[int]) -> list[ColumnElement[bool]]:
    return [Directory.missing_since.is_(None), Directory.music_folder_id.in_(folder_ids)]


async def last_modified(session: AsyncSession) -> datetime | None:
    """When the library last changed (the end of the last scan)."""
    return await session.scalar(select(func.max(Scan.finished_at)))


async def top_folders(
    session: AsyncSession, user: AppUser, music_folder_id: int | None = None
) -> tuple[list[Directory], list[SongEntry]]:
    """The directories right under the music folders' roots (the index), and the songs
    lying directly in a root."""
    folder_ids = await browsing.visible_folder_ids(session, user, music_folder_id)
    roots = (
        await session.scalars(
            select(Directory.id).where(Directory.parent_id.is_(None), *_present(folder_ids))
        )
    ).all()
    folders = list(
        (
            await session.scalars(
                select(Directory)
                .where(Directory.parent_id.in_(roots), *_present(folder_ids))
                .order_by(func.lower(Directory.name))
            )
        ).all()
    )
    songs = await browsing.directory_songs(session, user, list(roots))
    return folders, songs


async def listing(
    session: AsyncSession, user: AppUser, directory_id: uuid.UUID
) -> DirectoryListing | None:
    """A directory's sub-directories and songs. An album id is accepted too (some
    clients mix ids): its first song's directory."""
    folder_ids = await browsing.visible_folder_ids(session, user)
    directory = await session.scalar(
        select(Directory).where(Directory.id == directory_id, *_present(folder_ids))
    )
    if directory is None:
        album_dirs = await album_directories(session, [directory_id])
        if directory_id not in album_dirs:
            return None
        directory = await session.get(Directory, album_dirs[directory_id])
        if directory is None:
            return None
    folders = list(
        (
            await session.scalars(
                select(Directory)
                .where(Directory.parent_id == directory.id, *_present(folder_ids))
                .order_by(func.lower(Directory.name))
            )
        ).all()
    )
    songs = await browsing.directory_songs(session, user, [directory.id])
    return DirectoryListing(directory, directory.parent_id, folders, songs)


async def album_directories(
    session: AsyncSession, album_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """Album id -> the directory of its first song (disc, track)."""
    if not album_ids:
        return {}
    rows = await session.execute(
        select(Song.album_id, Song.directory_id)
        .where(Song.album_id.in_(album_ids), Song.missing_since.is_(None))
        .ext(distinct_on(Song.album_id))
        .order_by(
            Song.album_id,
            func.coalesce(Song.disc_number, 0),
            func.coalesce(Song.track_number, 0),
            Song.path,
        )
    )
    return {album_id: directory_id for album_id, directory_id in rows}


async def album_folders(session: AsyncSession, albums: list[AlbumEntry]) -> list[FolderEntry]:
    """Albums (from an album list or a search) as folders, in the same order."""
    directory_of = await album_directories(session, [a.album.id for a in albums])
    directories = {
        d.id: d
        for d in (
            await session.scalars(
                select(Directory).where(Directory.id.in_(set(directory_of.values())))
            )
        ).all()
    }
    result: list[FolderEntry] = []
    for album in albums:
        directory = directories.get(directory_of.get(album.album.id, uuid.UUID(int=0)))
        if directory is not None:
            result.append(FolderEntry(directory, album))
    return result


async def search_top_folders(
    session: AsyncSession, user: AppUser, query: str, count: int, offset: int
) -> list[Directory]:
    """Index directories ("artists") whose name contains every word of `query`."""
    folders, _ = await top_folders(session, user)
    words = browsing.search_words(query)
    found = [f for f in folders if all(w in normalize(f.name) for w in words)]
    return found[max(0, offset) : max(0, offset) + max(0, count)]


# --- folder ids of the ID3 world (getArtistInfo, getAlbumInfo, getSimilarSongs) ---------


def _under(directory: Directory) -> ColumnElement[bool]:
    """The songs inside `directory` (at any depth)."""
    inside = Song.music_folder_id == directory.music_folder_id
    if not directory.path:
        return inside
    return inside & Song.path.startswith(f"{directory.path}/", autoescape=True)


async def artist_of_directory(session: AsyncSession, directory: Directory) -> uuid.UUID | None:
    """The album artist of most songs inside the folder (an artist folder of the index)."""
    return await session.scalar(
        select(Album.artist_id)
        .join(Song, Song.album_id == Album.id)
        .where(_under(directory), Song.missing_since.is_(None))
        .group_by(Album.artist_id)
        .order_by(func.count().desc())
        .limit(1)
    )


async def album_of_directory(session: AsyncSession, directory: Directory) -> uuid.UUID | None:
    """The album of most songs of the folder (its own songs first, else those inside)."""
    for where in (Song.directory_id == directory.id, _under(directory)):
        album_id = await session.scalar(
            select(Song.album_id)
            .where(where, Song.missing_since.is_(None))
            .group_by(Song.album_id)
            .order_by(func.count().desc())
            .limit(1)
        )
        if album_id is not None:
            return album_id
    return None


async def directory_of_artist(session: AsyncSession, artist_id: uuid.UUID) -> Directory | None:
    """The index folder (right under a music folder's root) holding most of the artist's
    songs: the artist as folder-browsing clients know it."""
    rows = (
        await session.execute(
            select(Song.music_folder_id, Song.path)
            .join(Album, Album.id == Song.album_id)
            .where(Album.artist_id == artist_id, Song.missing_since.is_(None))
            .limit(200)
        )
    ).all()
    tops = Counter((folder, path.split("/")[0]) for folder, path in rows if "/" in path)
    if not tops:
        return None
    (folder_id, top), _ = tops.most_common(1)[0]
    return await session.scalar(
        select(Directory).where(
            Directory.music_folder_id == folder_id,
            Directory.path == top,
            Directory.missing_since.is_(None),
        )
    )
