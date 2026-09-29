"""A podcast's / audiobook's details (admins can change them after the import).

The details live in the files' tags, as the import review wrote them: title (album),
author (album artist and artist), narrator (composer), series and number (grouping,
"Series, Book 3"), year, genre, description (comment). The scanner reads them back onto
the album (Album.description, narrator, series, series_number).

Each file's title (a "hard" chapter) and the chapters inside it ("soft" chapters: an M4B's
chapter list, MP3 CHAP frames, library_manager/chapters.py) can be changed too.

Changing the title or the author also renames the book's folder, as the import lays them
out (`<Author>/<Title>`, podcasts `<Show>`), when it is laid out that way. The songs keep
their ids (their paths are updated before the targeted scan), so bookmarks, play counts,
playlists and transcripts follow.
"""

import asyncio
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import natural_key
from app.library_manager import chapters as chapter_files
from app.library_manager import files, spoken_review
from app.models import Album, AlbumGenre, Genre, MusicFolder, Song
from app.services import music_folders
from app.services.scans import ScanManager


class DetailsError(Exception):
    """The details cannot be applied (e.g. the new folder is another book's)."""


@dataclass
class FileChapter:
    start_ms: int
    title: str


@dataclass
class FileDetails:
    """A file of the book: its title, and the chapters inside it (None: left as they are)."""

    id: uuid.UUID
    title: str
    chapters: list[FileChapter] | None = None
    # Read only (details()):
    file_name: str = ""
    duration_ms: int = 0
    can_write_chapters: bool = False


@dataclass
class Details:
    title: str
    author: str
    narrator: str | None
    series: str | None
    series_number: str | None
    year: int | None
    genre: str | None
    description: str | None
    files: list[FileDetails] | None = None  # in listening order; None: left as they are


@dataclass
class _Book:
    album: Album
    folder: MusicFolder
    songs: list[Song]


async def _book(session: AsyncSession, album_id: uuid.UUID) -> _Book | None:
    album = await session.get(Album, album_id)
    if album is None:
        return None
    rows = (
        await session.execute(
            select(Song, MusicFolder)
            .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
            .where(Song.album_id == album_id, Song.missing_since.is_(None))
            .order_by(Song.path)
        )
    ).all()
    spoken = [(song, folder) for song, folder in rows if folder.kind in music_folders.SPOKEN_KINDS]
    if not spoken:
        return None
    return _Book(album, spoken[0][1], [song for song, _ in spoken])


async def genre_of(session: AsyncSession, album_id: uuid.UUID) -> str | None:
    return await session.scalar(
        select(Genre.name)
        .join(AlbumGenre, AlbumGenre.genre_id == Genre.id)
        .where(AlbumGenre.album_id == album_id)
        .order_by(AlbumGenre.position)
        .limit(1)
    )


def _file_details(song: Song) -> FileDetails:
    return FileDetails(
        id=song.id,
        title=song.title,
        chapters=[FileChapter(int(c["startMs"]), str(c["title"])) for c in song.chapters or []],
        file_name=Path(song.path).name,
        duration_ms=song.duration_ms,
        can_write_chapters=chapter_files.can_write(Path(song.path)),
    )


def _listening_order(songs: list[Song], kind: str) -> list[Song]:
    if kind == music_folders.AUDIOBOOKS:
        return sorted(
            songs,
            key=lambda s: (s.disc_number or 1, s.track_number or 0, natural_key(s.path)),
        )
    return sorted(songs, key=lambda s: s.path)


async def details(session: AsyncSession, album_id: uuid.UUID) -> Details | None:
    book = await _book(session, album_id)
    if book is None:
        return None
    album = book.album
    return Details(
        title=album.name,
        author=album.display_artist,
        narrator=album.narrator,
        series=album.series,
        series_number=album.series_number,
        year=album.year,
        genre=await genre_of(session, album_id),
        description=album.description,
        files=[_file_details(s) for s in _listening_order(book.songs, book.folder.kind)],
    )


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def _write(path: Path, kind: str, new: Details, title: str | None) -> None:
    import mediafile

    try:
        media: Any = mediafile.MediaFile(str(path))
        if title is not None:
            media.title = title
        media.album = new.title
        media.albumartist = new.author or None
        media.artist = new.author or None
        media.genre = new.genre
        media.comments = new.description
        if kind == music_folders.AUDIOBOOKS:
            media.composer = new.narrator
            number = f", Book {new.series_number}" if new.series and new.series_number else ""
            media.grouping = f"{new.series}{number}" if new.series else None
            media.year = new.year
            media.month = media.day = None
        media.save()
    except (mediafile.UnreadableFileError, OSError, ValueError) as error:
        raise DetailsError(f"Cannot write the tags of {path.name}: {error}") from error


def _import_kind(kind: str) -> str:
    return spoken_review.AUDIOBOOK if kind == music_folders.AUDIOBOOKS else spoken_review.PODCAST


def _layout(kind: str, title: str, author: str, root: Path) -> Path:
    metadata = spoken_review.SpokenMetadata(title=title, author=author)
    return spoken_review.target_folder(_import_kind(kind), metadata, root)


def _plan_rename(book: _Book, old: Details, new: Details) -> tuple[Path, Path] | None:
    """(the book's folder, its new place) when the title / author change moves it; None
    when it stays (not laid out as the import does, or the same folder)."""
    if (old.title, old.author) == (new.title, new.author):
        return None
    root = Path(book.folder.path)
    parents = {Path(song.path).parent for song in book.songs}
    if len(parents) != 1:
        return None  # files in several folders: left where they are
    current = root / parents.pop()
    expected = _layout(book.folder.kind, old.title, old.author, root)
    if files.real(expected) != files.real(current):
        return None  # not <Author>/<Title>: not ours to move
    target = _layout(book.folder.kind, new.title, new.author, root)
    if files.real(target) == files.real(current):
        return None
    if target.exists():
        raise DetailsError(
            f"{target.relative_to(root).as_posix()} already exists: another book has this "
            "title (and author)"
        )
    return current, target


def _move(current: Path, target: Path, root: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    current.rename(target)
    if current.parent != root and current.parent.exists():
        files.remove_emptied_folder(current.parent, root)


async def change(
    session: AsyncSession, scans: ScanManager, album_id: uuid.UUID, new: Details
) -> uuid.UUID:
    """Writes the new details into the book's files (and moves its folder when its title
    or author changes); returns the album's id afterwards (it changes with its name)."""
    book = await _book(session, album_id)
    if book is None:
        raise DetailsError("No such podcast or audiobook")
    new = Details(
        title=new.title.strip(),
        author=new.author.strip(),
        narrator=_clean(new.narrator),
        series=_clean(new.series),
        series_number=_clean(new.series_number) if _clean(new.series) else None,
        year=new.year,
        genre=_clean(new.genre),
        description=_clean(new.description),
        files=new.files,
    )
    if not new.title:
        raise DetailsError("Give the title")
    if book.folder.kind == music_folders.AUDIOBOOKS and not new.author:
        raise DetailsError("Give the author")
    old = await details(session, album_id)
    assert old is not None
    root = Path(book.folder.path)
    rename = _plan_rename(book, old, new)
    changes = {f.id: f for f in new.files or []}

    for song in book.songs:
        change_of = changes.get(song.id)
        title = " ".join(change_of.title.split()) if change_of else None
        if title is not None and (not title or title == song.title):
            title = None
        await asyncio.to_thread(_write, root / song.path, book.folder.kind, new, title)
        if change_of is not None and change_of.chapters is not None:
            given = [(c.start_ms, " ".join(c.title.split())) for c in change_of.chapters]
            known = [(int(c["startMs"]), str(c["title"])) for c in song.chapters or []]
            if given != known:
                try:
                    await asyncio.to_thread(
                        chapter_files.write,
                        root / song.path,
                        [chapter_files.Chapter(start, text) for start, text in given],
                        song.duration_ms,
                    )
                except chapter_files.ChapterWriteError as error:
                    raise DetailsError(str(error)) from error
    targets = sorted({Path(song.path).parent.as_posix() for song in book.songs})
    if rename is not None:
        current, target = rename
        await asyncio.to_thread(_move, current, target, root)
        old_prefix = current.relative_to(root).as_posix() + "/"
        new_prefix = target.relative_to(root).as_posix() + "/"
        for song in book.songs:
            if song.path.startswith(old_prefix):
                # The same song at its new place (the scanner then updates the rest).
                await session.execute(
                    update(Song)
                    .where(Song.id == song.id)
                    .values(path=new_prefix + song.path[len(old_prefix) :])
                )
        await session.commit()
        targets.append(new_prefix.rstrip("/"))
    first = book.songs[0].id
    await scans.scan_paths(book.folder.id, targets, reread=True)
    session.expire_all()
    album_now = await session.scalar(select(Song.album_id).where(Song.id == first))
    return album_now or album_id
