"""Library status (Manage Library, "Library" tab): the library against the tagger's own
database (beets), and the album folders that database does not know yet."""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_manager.imports import ImportManager
from app.models import Album, MusicFolder, Song


@dataclass
class UnknownFolder:
    """An album folder with songs the tagger's database does not know."""

    path: str  # relative to the library folder, "/" separated
    artist: str
    album: str
    songs: int
    unknown_songs: int


@dataclass
class LibraryStatus:
    albums: int
    songs: int
    has_tagger_database: bool
    tagger_albums: int = 0
    tagger_songs: int = 0  # library songs the tagger knows
    tagger_missing: int = 0  # tagger entries whose file is gone
    unknown_folders: list[UnknownFolder] = field(default_factory=list[UnknownFolder])


async def library_status(
    session: AsyncSession, imports: ImportManager, folder: MusicFolder
) -> LibraryStatus:
    root = Path(folder.path)
    rows = (
        await session.execute(
            select(Song.path, Album.id, Album.name, Album.display_artist)
            .join(Album, Album.id == Song.album_id)
            .where(Song.music_folder_id == folder.id, Song.missing_since.is_(None))
        )
    ).all()
    albums = {album_id for _, album_id, _, _ in rows}
    known = await imports.call_tagger(imports.tagger.library, root)
    if known is None:
        return LibraryStatus(len(albums), len(rows), has_tagger_database=False)

    folders: dict[str, UnknownFolder] = {}
    known_songs = 0
    for path, _, album, artist in rows:
        directory = path.rpartition("/")[0]
        entry = folders.get(directory)
        if entry is None:
            entry = folders[directory] = UnknownFolder(directory, artist, album, 0, 0)
        entry.songs += 1
        if path in known.paths:
            known_songs += 1
        else:
            entry.unknown_songs += 1
    unknown = sorted(
        (f for f in folders.values() if f.unknown_songs),
        key=lambda f: (f.artist.casefold(), f.album.casefold(), f.path),
    )
    return LibraryStatus(
        len(albums),
        len(rows),
        has_tagger_database=True,
        tagger_albums=known.albums,
        tagger_songs=known_songs,
        tagger_missing=len(known.missing),
        unknown_folders=unknown,
    )
