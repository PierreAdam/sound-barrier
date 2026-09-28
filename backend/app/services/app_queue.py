"""The Subsonic apps' play queue (getPlayQueue / savePlayQueue and the index-based
variants): one per user, shared by the apps (resume on another device). The web UI keeps
its own queue (services/web_queue.py)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, PlayQueue, PlayQueueEntry
from app.services import browsing
from app.services.browsing import SongEntry

MAX_SONGS = 5000


class InvalidQueueError(ValueError):
    pass


@dataclass
class AppQueue:
    songs: list[SongEntry]
    current_index: int | None  # in `songs`
    position_ms: int
    changed_at: datetime
    changed_by: str


async def save(
    session: AsyncSession,
    user: AppUser,
    song_ids: list[uuid.UUID],
    *,
    current_index: int | None,
    position_ms: int,
    client: str,
) -> None:
    """Replaces the user's queue; no songs clears it."""
    if len(song_ids) > MAX_SONGS:
        raise InvalidQueueError(f"A queue holds at most {MAX_SONGS} songs")
    if current_index is not None and not 0 <= current_index < len(song_ids):
        raise InvalidQueueError("The current song is not in the queue")
    await session.execute(delete(PlayQueueEntry).where(PlayQueueEntry.user_id == user.id))
    if not song_ids:
        await session.execute(delete(PlayQueue).where(PlayQueue.user_id == user.id))
        await session.flush()
        return
    values = {
        "current_song_id": song_ids[current_index] if current_index is not None else None,
        "current_index": current_index,
        "position_ms": max(0, position_ms),
        "changed_at": datetime.now(UTC),
        "changed_by": client,
    }
    statement = insert(PlayQueue).values(user_id=user.id, **values)
    await session.execute(
        statement.on_conflict_do_update(index_elements=[PlayQueue.user_id], set_=values)
    )
    session.add_all(
        PlayQueueEntry(user_id=user.id, position=position, song_id=song_id)
        for position, song_id in enumerate(song_ids)
    )
    await session.flush()


async def get(session: AsyncSession, user: AppUser) -> AppQueue | None:
    queue = await session.get(PlayQueue, user.id)
    if queue is None:
        return None
    ids = list(
        (
            await session.scalars(
                select(PlayQueueEntry.song_id)
                .where(PlayQueueEntry.user_id == user.id)
                .order_by(PlayQueueEntry.position)
            )
        ).all()
    )
    entries = await browsing.get_songs(session, user, ids)
    # Songs gone since (deleted, or no longer visible) are left out.
    kept = [
        (position, entries[song_id]) for position, song_id in enumerate(ids) if song_id in entries
    ]
    current = None
    if queue.current_index is not None:
        current = next((i for i, (p, _) in enumerate(kept) if p == queue.current_index), None)
    elif queue.current_song_id is not None:
        current = next(
            (i for i, (_, s) in enumerate(kept) if s.song.id == queue.current_song_id), None
        )
    position_ms = queue.position_ms if current is not None else 0
    return AppQueue(
        [entry for _, entry in kept], current, position_ms, queue.changed_at, queue.changed_by
    )
