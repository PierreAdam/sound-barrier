"""Bookmarks: where a user stopped in a song (audiobooks and podcasts, see spoken.py).
One per user and song; the web player and Subsonic apps share them.

The web player follows them across devices: it checks the latest bookmark of what it has
(of the whole book, for an audiobook: the listener may be in another file of it) and moves
there, and its saves say which bookmark they follow (`seen`): one made from an outdated
position is refused, so a device left open on an old position cannot erase newer progress.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, Bookmark, Song
from app.services import browsing, music_folders
from app.services.browsing import SongEntry

MAX_SOURCE = 100


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
    session: AsyncSession,
    user: AppUser,
    song_id: uuid.UUID,
    position_ms: int,
    comment: str | None,
    source: str | None = None,
) -> bool:
    """Creates or moves the bookmark; False if the user cannot see the song. The caller
    commits."""
    if await browsing.get_song(session, user, song_id) is None:
        return False
    values = {
        "position_ms": max(position_ms, 0),
        "comment": comment,
        "changed_at": func.now(),
        "source": source[:MAX_SOURCE] if source else None,
    }
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


async def latest(session: AsyncSession, user: AppUser, song_id: uuid.UUID) -> Bookmark | None:
    """The user's latest bookmark of what this song belongs to: any file of its audiobook,
    else (a podcast episode) the song's own. None: none, or a song they cannot see."""
    entry = await browsing.get_song(session, user, song_id)
    if entry is None:
        return None
    where = (
        Bookmark.song_id.in_(select(Song.id).where(Song.album_id == entry.album.id))
        if entry.folder_kind == music_folders.AUDIOBOOKS
        else Bookmark.song_id == song_id
    )
    return await session.scalar(
        select(Bookmark)
        .where(Bookmark.user_id == user.id, where)
        .order_by(Bookmark.changed_at.desc())
        .limit(1)
        # Fresh: `save` moves the row with an upsert, not through an object already loaded.
        .execution_options(populate_existing=True)
    )


def moved_since(found: Bookmark | None, seen: datetime | None) -> bool:
    """Someone saved after `seen`, the latest bookmark the caller knew (None: none)."""
    return found is not None and (seen is None or found.changed_at > seen)


@dataclass
class Checked:
    done: bool  # False: refused, `latest` is newer than what the caller knew
    latest: Bookmark | None  # after the change when done


async def save_checked(
    session: AsyncSession,
    user: AppUser,
    song_id: uuid.UUID,
    position_ms: int,
    seen: datetime | None,
    source: str | None,
) -> Checked | None:
    """Saves the bookmark unless someone saved after `seen` (see the module's docstring).
    None: a song the user cannot see. The caller commits."""
    found = await latest(session, user, song_id)
    if moved_since(found, seen):
        return Checked(False, found)
    if not await save(session, user, song_id, position_ms, None, source):
        return None
    await session.flush()
    return Checked(True, await latest(session, user, song_id))


async def remove_checked(
    session: AsyncSession, user: AppUser, song_id: uuid.UUID, seen: datetime | None
) -> Checked:
    """Removes the bookmark (listened to the end) unless someone saved after `seen`. The
    caller commits."""
    found = await latest(session, user, song_id)
    if moved_since(found, seen):
        return Checked(False, found)
    await remove(session, user, song_id)
    await session.flush()
    return Checked(True, await latest(session, user, song_id))
