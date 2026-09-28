"""Stars and ratings (Subsonic star, unstar, setRating, getStarred / getStarred2), per user.

Items are songs, albums or artists. Folder clients star directories: a directory holding
an album stands for that album, a top-level directory for the artist of the same name.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import ColumnElement, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize
from app.models import (
    Album,
    AlbumAnnotation,
    AppUser,
    Artist,
    ArtistAnnotation,
    Directory,
    Song,
    SongAnnotation,
)
from app.services import browsing
from app.services.browsing import AlbumEntry, ArtistEntry, SongEntry

type Kind = Literal["song", "album", "artist"]
_MODELS = {"song": SongAnnotation, "album": AlbumAnnotation, "artist": ArtistAnnotation}


class UnknownItemError(LookupError):
    pass


async def resolve(session: AsyncSession, item_id: uuid.UUID) -> tuple[Kind, uuid.UUID] | None:
    """What an id sent by a client designates."""
    if await session.get(Song, item_id) is not None:
        return "song", item_id
    if await session.get(Album, item_id) is not None:
        return "album", item_id
    if await session.get(Artist, item_id) is not None:
        return "artist", item_id
    directory = await session.get(Directory, item_id)
    if directory is None:
        return None
    album_id = await session.scalar(
        select(Song.album_id)
        .where(Song.directory_id == directory.id, Song.missing_since.is_(None))
        .limit(1)
    )
    if album_id is not None:
        return "album", album_id
    artist_id = await session.scalar(
        select(Artist.id)
        .where(Artist.name_search == normalize(directory.name), Artist.missing_since.is_(None))
        .limit(1)
    )
    return ("artist", artist_id) if artist_id is not None else None


async def _upsert(
    session: AsyncSession, kind: Kind, user: AppUser, item_id: uuid.UUID, **values: object
) -> None:
    model = _MODELS[kind]
    statement = insert(model).values(user_id=user.id, item_id=item_id, **values)
    await session.execute(
        statement.on_conflict_do_update(index_elements=[model.user_id, model.item_id], set_=values)
    )


async def star(
    session: AsyncSession, user: AppUser, items: list[tuple[Kind | None, uuid.UUID]], starred: bool
) -> None:
    """Stars (or unstars) items; kind None: find out from the id. UnknownItemError for an
    id that designates nothing."""
    now = datetime.now(UTC) if starred else None
    for kind, item_id in items:
        target = (kind, item_id) if kind is not None else await resolve(session, item_id)
        if target is None:
            raise UnknownItemError(str(item_id))
        await _upsert(session, target[0], user, target[1], starred_at=now)
    await session.flush()


async def set_rating(session: AsyncSession, user: AppUser, item_id: uuid.UUID, rating: int) -> None:
    """1 to 5 stars; 0 removes the rating."""
    target = await resolve(session, item_id)
    if target is None:
        raise UnknownItemError(str(item_id))
    await _upsert(session, target[0], user, target[1], rating=rating or None)
    await session.flush()


@dataclass
class Starred:
    artists: list[ArtistEntry]
    albums: list[AlbumEntry]
    songs: list[SongEntry]


async def starred(
    session: AsyncSession, user: AppUser, music_folder_id: int | None = None
) -> Starred:
    """The user's starred artists, albums and songs, most recently starred first."""
    folder_ids = await browsing.visible_folder_ids(session, user, music_folder_id)
    is_starred: dict[str, ColumnElement[bool]] = {
        "artist": ArtistAnnotation.starred_at.is_not(None),
        "album": AlbumAnnotation.starred_at.is_not(None),
        "song": SongAnnotation.starred_at.is_not(None),
    }
    return Starred(
        await browsing.artist_entries(
            session,
            user,
            folder_ids,
            is_starred["artist"],
            order_by=[ArtistAnnotation.starred_at.desc()],
        ),
        await browsing.album_entries(
            session,
            user,
            folder_ids,
            is_starred["album"],
            order_by=[AlbumAnnotation.starred_at.desc()],
        ),
        await browsing.song_entries(
            session,
            user,
            folder_ids,
            is_starred["song"],
            order_by=[SongAnnotation.starred_at.desc()],
        ),
    )
