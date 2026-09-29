"""Read-only queries over the library, scoped to the folders a user may access."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, SQLColumnExpression, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize
from app.models import (
    Album,
    AlbumAnnotation,
    AlbumArtist,
    AlbumGenre,
    AppUser,
    Artist,
    ArtistAnnotation,
    Bookmark,
    Genre,
    MusicFolder,
    Song,
    SongAnnotation,
    SongArtist,
    SongGenre,
)
from app.services import music_folders, server_settings


class FolderNotAccessibleError(Exception):
    pass


def parse_id(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


@dataclass(frozen=True)
class ArtistEntry:
    artist: Artist
    album_count: int  # albums visible in the requested folders
    starred_at: datetime | None
    rating: int | None


@dataclass(frozen=True)
class NamedRef:
    id: uuid.UUID
    name: str


@dataclass(frozen=True)
class RoleRef:
    role: str
    sub_role: str
    artist: NamedRef


@dataclass(frozen=True)
class AlbumEntry:
    album: Album
    song_count: int  # songs visible to the user
    duration_ms: int
    starred_at: datetime | None
    rating: int | None
    genres: list[str] = field(default_factory=list[str])
    artists: list[NamedRef] = field(default_factory=list[NamedRef])
    play_count: int = 0  # by the user
    played: datetime | None = None  # last played by the user


@dataclass(frozen=True)
class SongEntry:
    song: Song
    album: Album
    starred_at: datetime | None
    rating: int | None
    play_count: int
    last_played_at: datetime | None
    genres: list[str] = field(default_factory=list[str])
    roles: list[RoleRef] = field(default_factory=list[RoleRef])
    bookmark_ms: int | None = None  # where the user stopped (audiobooks, podcasts)
    folder_kind: str = "music"  # of its library folder: music, podcasts, audiobooks

    def artists(self, role: str) -> list[NamedRef]:
        return [r.artist for r in self.roles if r.role == role]


def music_album_ids() -> Select[uuid.UUID]:
    """Albums with songs in music folders (not podcasts or audiobooks), for queries that
    do not go through the user's folders."""
    return (
        select(Song.album_id)
        .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
        .where(MusicFolder.kind == music_folders.MUSIC)
    )


async def enabled_kinds(session: AsyncSession) -> list[str]:
    """Music, and the spoken kinds an admin turned on."""
    spoken = await server_settings.get_spoken_audio(session)
    return [music_folders.MUSIC, *(k for k in music_folders.SPOKEN_KINDS if spoken.enabled(k))]


async def playable_folder_ids(session: AsyncSession, user: AppUser) -> list[int]:
    """Every folder whose songs the user may play: music, and podcasts / audiobooks when
    on (stream, getSong, bookmarks). Lists and searches use visible_folder_ids."""
    kinds = await enabled_kinds(session)
    return [f.id for f in await music_folders.list_for_user(session, user, kinds)]


async def spoken_folder_ids(session: AsyncSession, user: AppUser, kind: str) -> list[int]:
    """The user's folders of a spoken kind, if it is on."""
    if kind not in await enabled_kinds(session):
        return []
    return [f.id for f in await music_folders.list_for_user(session, user, (kind,))]


async def visible_folder_ids(
    session: AsyncSession, user: AppUser, music_folder_id: int | None = None
) -> list[int]:
    """The user's music folders (never podcasts or audiobooks), or only
    `music_folder_id` if given (and accessible)."""
    allowed = [f.id for f in await music_folders.list_for_user(session, user)]
    if music_folder_id is None:
        return allowed
    if music_folder_id not in allowed:
        raise FolderNotAccessibleError(music_folder_id)
    return [music_folder_id]


def _visible_song(folder_ids: list[int]) -> ColumnElement[bool]:
    return Song.missing_since.is_(None) & Song.music_folder_id.in_(folder_ids)


# --- artists ----------------------------------------------------------------


async def list_album_artists(
    session: AsyncSession, user: AppUser, music_folder_id: int | None = None
) -> Sequence[ArtistEntry]:
    """Album artists with at least one present album in the visible folders, by sort name."""
    folder_ids = await visible_folder_ids(session, user, music_folder_id)
    return await _artist_entries(session, user, folder_ids)


async def get_artist(
    session: AsyncSession, user: AppUser, artist_id: uuid.UUID
) -> tuple[ArtistEntry, list[AlbumEntry]] | None:
    """An album artist and their visible albums (oldest first)."""
    folder_ids = await visible_folder_ids(session, user)
    entries = await _artist_entries(session, user, folder_ids, Artist.id == artist_id)
    if not entries:
        return None
    albums = await _album_entries(
        session,
        user,
        folder_ids,
        Album.id.in_(
            select(AlbumArtist.album_id).where(
                AlbumArtist.artist_id == artist_id, AlbumArtist.role == "albumartist"
            )
        ),
        order_by=(func.coalesce(Album.year, 9999), func.lower(Album.sort_name)),
    )
    return entries[0], albums


async def _artist_entries(
    session: AsyncSession,
    user: AppUser,
    folder_ids: list[int],
    *where: ColumnElement[bool],
    order_by: Sequence[Any] = (),
    limit: int | None = None,
    offset: int = 0,
) -> list[ArtistEntry]:
    album_counts = (
        select(AlbumArtist.artist_id, func.count(distinct(Album.id)).label("album_count"))
        .join(Album, Album.id == AlbumArtist.album_id)
        .join(Song, Song.album_id == Album.id)
        .where(AlbumArtist.role == "albumartist", Album.missing_since.is_(None))
        .where(_visible_song(folder_ids))
        .group_by(AlbumArtist.artist_id)
        .subquery()
    )
    rows = await session.execute(
        select(
            Artist, album_counts.c.album_count, ArtistAnnotation.starred_at, ArtistAnnotation.rating
        )
        .join(album_counts, album_counts.c.artist_id == Artist.id)
        .outerjoin(
            ArtistAnnotation,
            (ArtistAnnotation.item_id == Artist.id) & (ArtistAnnotation.user_id == user.id),
        )
        .where(*where)
        .order_by(*order_by, func.lower(Artist.sort_name), Artist.name)
        .limit(limit)
        .offset(offset)
    )
    return [ArtistEntry(a, count, starred, rating) for a, count, starred, rating in rows]


# --- albums -----------------------------------------------------------------


async def get_album(
    session: AsyncSession, user: AppUser, album_id: uuid.UUID
) -> tuple[AlbumEntry, list[SongEntry]] | None:
    folder_ids = await visible_folder_ids(session, user)
    albums = await _album_entries(session, user, folder_ids, Album.id == album_id)
    if not albums:
        return None
    songs = await _song_entries(
        session,
        user,
        folder_ids,
        Song.album_id == album_id,
        order_by=(
            func.coalesce(Song.disc_number, 0),
            func.coalesce(Song.track_number, 0),
            Song.path,
        ),
    )
    return albums[0], songs


async def _album_entries(
    session: AsyncSession,
    user: AppUser,
    folder_ids: list[int],
    *where: ColumnElement[bool],
    order_by: Sequence[Any] = (),
    limit: int | None = None,
    offset: int = 0,
) -> list[AlbumEntry]:
    stats = (
        select(
            Song.album_id,
            func.count(Song.id).label("songs"),
            func.coalesce(func.sum(Song.duration_ms), 0).label("duration"),
        )
        .where(_visible_song(folder_ids))
        .group_by(Song.album_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                Album,
                stats.c.songs,
                stats.c.duration,
                AlbumAnnotation.starred_at,
                AlbumAnnotation.rating,
                AlbumAnnotation.play_count,
                AlbumAnnotation.last_played_at,
            )
            .join(stats, stats.c.album_id == Album.id)
            .outerjoin(
                AlbumAnnotation,
                (AlbumAnnotation.item_id == Album.id) & (AlbumAnnotation.user_id == user.id),
            )
            .where(Album.missing_since.is_(None), *where)
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    ids = [row[0].id for row in rows]
    genres = await _names_by_owner(
        session,
        select(AlbumGenre.album_id, Genre.name)
        .join(Genre, Genre.id == AlbumGenre.genre_id)
        .where(AlbumGenre.album_id.in_(ids))
        .order_by(AlbumGenre.position),
    )
    artists: dict[uuid.UUID, list[NamedRef]] = {}
    for album_id, artist_id, name in await session.execute(
        select(AlbumArtist.album_id, Artist.id, Artist.name)
        .join(Artist, Artist.id == AlbumArtist.artist_id)
        .where(AlbumArtist.album_id.in_(ids), AlbumArtist.role == "albumartist")
        .order_by(AlbumArtist.position)
    ):
        artists.setdefault(album_id, []).append(NamedRef(artist_id, name))
    return [
        AlbumEntry(
            album,
            songs,
            int(duration),
            starred,
            rating,
            genres.get(album.id, []),
            artists.get(album.id, []),
            play_count or 0,
            played,
        )
        for album, songs, duration, starred, rating, play_count, played in rows
    ]


# --- album lists (getAlbumList2, home page) ---------------------------------------

ALBUM_LIST_TYPES = (
    "random",
    "newest",
    "frequent",
    "recent",
    "highest",
    "starred",
    "alphabeticalByName",
    "alphabeticalByArtist",
    "byYear",
    "byGenre",
)
MAX_ALBUM_LIST_SIZE = 500


class InvalidAlbumListError(ValueError):
    pass


async def album_list(
    session: AsyncSession,
    user: AppUser,
    list_type: str,
    *,
    size: int = 10,
    offset: int = 0,
    music_folder_id: int | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    genre: str | None = None,
) -> list[AlbumEntry]:
    """Albums for one of the Subsonic list types. "frequent" / "recent" / "highest" /
    "starred" are the user's own (plays, ratings, stars); "newest" is by date added."""
    folder_ids = await visible_folder_ids(session, user, music_folder_id)
    size = max(0, min(size, MAX_ALBUM_LIST_SIZE))
    where: list[ColumnElement[bool]] = []
    match list_type:
        case "random":
            order: list[Any] = [func.random()]
        case "newest":
            order = [Album.created_at.desc(), Album.sort_name]
        case "frequent":
            where.append(AlbumAnnotation.play_count > 0)
            order = [AlbumAnnotation.play_count.desc(), AlbumAnnotation.last_played_at.desc()]
        case "recent":
            where.append(AlbumAnnotation.last_played_at.is_not(None))
            order = [AlbumAnnotation.last_played_at.desc()]
        case "highest":
            where.append(AlbumAnnotation.rating.is_not(None))
            order = [AlbumAnnotation.rating.desc(), Album.sort_name]
        case "starred":
            where.append(AlbumAnnotation.starred_at.is_not(None))
            order = [AlbumAnnotation.starred_at.desc()]
        case "alphabeticalByName":
            order = [func.lower(Album.sort_name), Album.id]
        case "alphabeticalByArtist":
            order = [func.lower(Album.display_artist), func.lower(Album.sort_name), Album.id]
        case "byYear":
            if from_year is None or to_year is None:
                raise InvalidAlbumListError("byYear needs fromYear and toYear")
            low, high = sorted((from_year, to_year))
            where.append(Album.year.between(low, high))
            # fromYear > toYear: newest first (as in the Subsonic API).
            order = [Album.year.desc() if from_year > to_year else Album.year, Album.sort_name]
        case "byGenre":
            if not genre:
                raise InvalidAlbumListError("byGenre needs genre")
            where.append(
                select(AlbumGenre.album_id)
                .join(Genre, Genre.id == AlbumGenre.genre_id)
                .where(AlbumGenre.album_id == Album.id, func.lower(Genre.name) == genre.lower())
                .exists()
            )
            order = [func.lower(Album.sort_name)]
        case _:
            raise InvalidAlbumListError(f"Unknown list type: {list_type}")
    return await _album_entries(
        session, user, folder_ids, *where, order_by=order, limit=size, offset=offset
    )


# --- songs ------------------------------------------------------------------


async def get_song(session: AsyncSession, user: AppUser, song_id: uuid.UUID) -> SongEntry | None:
    """A song the user may play (music, or a podcast / audiobook when that kind is on)."""
    folder_ids = await playable_folder_ids(session, user)
    songs = await _song_entries(session, user, folder_ids, Song.id == song_id)
    return songs[0] if songs else None


async def directory_songs(
    session: AsyncSession, user: AppUser, directory_ids: Sequence[uuid.UUID]
) -> list[SongEntry]:
    """The visible songs lying directly in these directories, in track order."""
    if not directory_ids:
        return []
    folder_ids = await visible_folder_ids(session, user)
    return await _song_entries(
        session,
        user,
        folder_ids,
        Song.directory_id.in_(directory_ids),
        order_by=(
            func.coalesce(Song.disc_number, 0),
            func.coalesce(Song.track_number, 0),
            Song.path,
        ),
    )


async def artist_songs(
    session: AsyncSession, user: AppUser, artist_id: uuid.UUID
) -> list[SongEntry]:
    """The visible songs of an artist (as track artist or album artist), oldest album
    first."""
    folder_ids = await visible_folder_ids(session, user)
    return await _song_entries(
        session,
        user,
        folder_ids,
        (Song.artist_id == artist_id) | (Album.artist_id == artist_id),
        order_by=(
            func.coalesce(Album.year, 0),
            Album.sort_name,
            func.coalesce(Song.disc_number, 0),
            func.coalesce(Song.track_number, 0),
        ),
    )


async def get_songs(
    session: AsyncSession, user: AppUser, song_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, SongEntry]:
    """The songs among `song_ids` the user can play (present, in their folders; queues,
    playlists and bookmarks may hold podcast episodes and audiobook chapters)."""
    if not song_ids:
        return {}
    folder_ids = await playable_folder_ids(session, user)
    entries = await _song_entries(session, user, folder_ids, Song.id.in_(set(song_ids)))
    return {entry.song.id: entry for entry in entries}


async def folder_songs(
    session: AsyncSession,
    user: AppUser,
    folder_ids: list[int],
    *where: ColumnElement[bool],
    order_by: Sequence[Any] = (),
) -> list[SongEntry]:
    """The present songs of these folders (e.g. a podcasts folder, spoken_folder_ids)."""
    if not folder_ids:
        return []
    return await _song_entries(session, user, folder_ids, *where, order_by=order_by)


async def _song_entries(
    session: AsyncSession,
    user: AppUser,
    folder_ids: list[int],
    *where: ColumnElement[bool],
    order_by: Sequence[Any] = (),
    limit: int | None = None,
    offset: int = 0,
) -> list[SongEntry]:
    rows = (
        await session.execute(
            select(
                Song,
                Album,
                SongAnnotation.starred_at,
                SongAnnotation.rating,
                SongAnnotation.play_count,
                SongAnnotation.last_played_at,
                Bookmark.position_ms,
                MusicFolder.kind,
            )
            .join(Album, Album.id == Song.album_id)
            .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
            .outerjoin(
                SongAnnotation,
                (SongAnnotation.item_id == Song.id) & (SongAnnotation.user_id == user.id),
            )
            .outerjoin(Bookmark, (Bookmark.song_id == Song.id) & (Bookmark.user_id == user.id))
            .where(_visible_song(folder_ids), *where)
            .order_by(*order_by)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    ids = [row[0].id for row in rows]
    genres = await _names_by_owner(
        session,
        select(SongGenre.song_id, Genre.name)
        .join(Genre, Genre.id == SongGenre.genre_id)
        .where(SongGenre.song_id.in_(ids))
        .order_by(SongGenre.position),
    )
    roles: dict[uuid.UUID, list[RoleRef]] = {}
    for song_id, role, sub_role, artist_id, name in await session.execute(
        select(SongArtist.song_id, SongArtist.role, SongArtist.sub_role, Artist.id, Artist.name)
        .join(Artist, Artist.id == SongArtist.artist_id)
        .where(SongArtist.song_id.in_(ids))
        .order_by(SongArtist.position)
    ):
        roles.setdefault(song_id, []).append(RoleRef(role, sub_role, NamedRef(artist_id, name)))
    return [
        SongEntry(
            song,
            album,
            starred,
            rating,
            play_count or 0,
            played,
            genres.get(song.id, []),
            roles.get(song.id, []),
            bookmark,
            kind,
        )
        for song, album, starred, rating, play_count, played, bookmark, kind in rows
    ]


async def _names_by_owner(
    session: AsyncSession, statement: Select[uuid.UUID, str]
) -> dict[uuid.UUID, list[str]]:
    """Runs a (owner id, name) query and groups the names by owner."""
    result: dict[uuid.UUID, list[str]] = {}
    for owner_id, name in await session.execute(statement):
        result.setdefault(owner_id, []).append(name)
    return result


# --- search (search3, web UI) -------------------------------------------------

MAX_SEARCH_COUNT = 500


@dataclass
class SearchResult:
    artists: list[ArtistEntry]
    albums: list[AlbumEntry]
    songs: list[SongEntry]


def search_words(query: str) -> list[str]:
    """The words to find. Clients send "" (or '""') to list everything (full sync)."""
    return normalize(query.strip().strip('"')).split()


def _all_words(text: SQLColumnExpression[str], words: list[str]) -> list[ColumnElement[bool]]:
    return [text.contains(word, autoescape=True) for word in words]


def _starts_first(text: SQLColumnExpression[str], words: list[str]) -> list[Any]:
    """Results starting with the query come first."""
    if not words:
        return []
    return [case((text.startswith(" ".join(words), autoescape=True), 0), else_=1)]


async def search(
    session: AsyncSession,
    user: AppUser,
    query: str,
    *,
    artist_count: int = 20,
    artist_offset: int = 0,
    album_count: int = 20,
    album_offset: int = 0,
    song_count: int = 20,
    song_offset: int = 0,
    music_folder_id: int | None = None,
) -> SearchResult:
    """Artists (by name), albums (name and artist) and songs (title, artist and album)
    containing every word of `query`, ignoring case and accents."""
    folder_ids = await visible_folder_ids(session, user, music_folder_id)
    words = search_words(query)

    def count(value: int) -> int:
        return max(0, min(value, MAX_SEARCH_COUNT))

    artists: list[ArtistEntry] = []
    if count(artist_count):
        artists = await _artist_entries(
            session,
            user,
            folder_ids,
            *_all_words(Artist.name_search, words),
            order_by=_starts_first(Artist.name_search, words),
            limit=count(artist_count),
            offset=max(0, artist_offset),
        )

    albums: list[AlbumEntry] = []
    if count(album_count):
        album_artist = (
            select(Artist.name_search).where(Artist.id == Album.artist_id).scalar_subquery()
        )
        album_text = Album.name_search + " " + func.coalesce(album_artist, "")
        albums = await _album_entries(
            session,
            user,
            folder_ids,
            *_all_words(album_text, words),
            order_by=[
                *_starts_first(Album.name_search, words),
                func.lower(Album.sort_name),
                Album.id,
            ],
            limit=count(album_count),
            offset=max(0, album_offset),
        )

    songs: list[SongEntry] = []
    if count(song_count):
        song_artist = (
            select(Artist.name_search).where(Artist.id == Song.artist_id).scalar_subquery()
        )
        song_text = (
            Song.title_search + " " + func.coalesce(song_artist, "") + " " + Album.name_search
        )
        songs = await _song_entries(
            session,
            user,
            folder_ids,
            *_all_words(song_text, words),
            # Songs of an album stay in track order.
            order_by=[
                *_starts_first(Song.title_search, words),
                func.lower(Album.sort_name),
                Album.id,
                func.coalesce(Song.disc_number, 0),
                func.coalesce(Song.track_number, 0),
                Song.id,
            ],
            limit=count(song_count),
            offset=max(0, song_offset),
        )
    return SearchResult(artists, albums, songs)


# Query helpers for the other services (stars, lists...).
artist_entries = _artist_entries
album_entries = _album_entries
song_entries = _song_entries

MAX_SONG_LIST = 500


async def random_songs(
    session: AsyncSession,
    user: AppUser,
    *,
    size: int = 10,
    genre: str | None = None,
    from_year: int | None = None,
    to_year: int | None = None,
    music_folder_id: int | None = None,
) -> list[SongEntry]:
    folder_ids = await visible_folder_ids(session, user, music_folder_id)
    where: list[ColumnElement[bool]] = []
    if genre:
        where.append(_has_genre(genre))
    if from_year is not None:
        where.append(Song.year >= from_year)
    if to_year is not None:
        where.append(Song.year <= to_year)
    return await _song_entries(
        session,
        user,
        folder_ids,
        *where,
        order_by=[func.random()],
        limit=max(0, min(size, MAX_SONG_LIST)),
    )


def _has_genre(genre: str) -> ColumnElement[bool]:
    return (
        select(SongGenre.song_id)
        .join(Genre, Genre.id == SongGenre.genre_id)
        .where(SongGenre.song_id == Song.id, func.lower(Genre.name) == genre.strip().lower())
        .exists()
    )


async def songs_by_genre(
    session: AsyncSession,
    user: AppUser,
    genre: str,
    *,
    count: int = 10,
    offset: int = 0,
    music_folder_id: int | None = None,
) -> list[SongEntry]:
    folder_ids = await visible_folder_ids(session, user, music_folder_id)
    return await _song_entries(
        session,
        user,
        folder_ids,
        _has_genre(genre),
        order_by=[
            func.lower(Album.sort_name),
            Album.id,
            func.coalesce(Song.disc_number, 0),
            func.coalesce(Song.track_number, 0),
            Song.id,
        ],
        limit=max(0, min(count, MAX_SONG_LIST)),
        offset=max(0, offset),
    )


@dataclass(frozen=True)
class GenreCount:
    name: str
    songs: int
    albums: int


async def genres(session: AsyncSession, user: AppUser) -> list[GenreCount]:
    """Genres of the visible songs, with their song and album counts, by name."""
    folder_ids = await visible_folder_ids(session, user)
    rows = await session.execute(
        select(Genre.name, func.count(distinct(Song.id)), func.count(distinct(Song.album_id)))
        .join(SongGenre, SongGenre.genre_id == Genre.id)
        .join(Song, Song.id == SongGenre.song_id)
        .where(_visible_song(folder_ids))
        .group_by(Genre.name)
        .order_by(func.lower(Genre.name))
    )
    return [GenreCount(name, songs, albums) for name, songs, albums in rows]
