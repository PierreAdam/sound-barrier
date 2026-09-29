"""Bookmarks: where a user stopped in a song (audiobooks and podcasts, see spoken.py).
One per user and song; the web player and Subsonic apps share them."""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, Bookmark, Song
from app.services import browsing
from app.services.browsing import SongEntry


@dataclass
class BookmarkEntry:
    bookmark: Bookmark
    song: SongEntry


async def list_for(session: AsyncSession, user: AppUser) -> list[BookmarkEntry]:
    """The user's bookmarks of songs they can still see, the latest first."""
    marks = (
        await session.scalars(
            select(Bookmark).where(Bookmark.user_id == user.id).order_by(Bookmark.changed_at.desc())
        )
    ).all()
    songs = await browsing.get_songs(session, user, [m.song_id for m in marks])
    return [BookmarkEntry(m, songs[m.song_id]) for m in marks if m.song_id in songs]


async def save(
    session: AsyncSession, user: AppUser, song_id: uuid.UUID, position_ms: int, comment: str | None
) -> bool:
    """Creates or moves the bookmark; False if the user cannot see the song. The caller
    commits."""
    if await browsing.get_song(session, user, song_id) is None:
        return False
    values = {"position_ms": max(position_ms, 0), "comment": comment, "changed_at": func.now()}
    statement = insert(Bookmark).values(user_id=user.id, song_id=song_id, **values)
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[Bookmark.user_id, Bookmark.song_id], set_=values
        )
    )
    return True


async def remove(session: AsyncSession, user: AppUser, song_id: uuid.UUID) -> None:
    await session.execute(
        delete(Bookmark).where(Bookmark.user_id == user.id, Bookmark.song_id == song_id)
    )


async def remove_for_album(session: AsyncSession, user: AppUser, album_id: uuid.UUID) -> None:
    """Every bookmark of the user in a show / book (dismissed, or started over)."""
    await session.execute(
        delete(Bookmark).where(
            Bookmark.user_id == user.id,
            Bookmark.song_id.in_(select(Song.id).where(Song.album_id == album_id)),
        )
    )
