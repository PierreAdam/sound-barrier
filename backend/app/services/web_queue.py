"""The web UI's play queue, kept on the server (one per user, see models.WebPlayQueue)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, WebPlayQueue
from app.services import browsing
from app.services.browsing import SongEntry

MAX_SONGS = 5000


class InvalidQueueError(ValueError):
    pass


@dataclass
class Queue:
    songs: list[SongEntry]  # play order
    original_order: list[int] | None  # play positions in the original order (shuffled)
    current_index: int
    position_ms: int
    revision: int
    updated_at: datetime | None


@dataclass
class _Kept:
    song_ids: list[uuid.UUID]
    original_order: list[int] | None
    current_index: int
    position_ms: int


def keep_available(
    song_ids: list[uuid.UUID],
    original_order: list[int] | None,
    current_index: int,
    position_ms: int,
    available: set[uuid.UUID],
) -> _Kept:
    """The queue without the songs that are no longer available. If the current song is
    gone, the next remaining one becomes current (else the previous one), from its start."""
    kept = [i for i, song_id in enumerate(song_ids) if song_id in available]
    new_index = {old: new for new, old in enumerate(kept)}
    original = None
    if original_order is not None:
        original = [new_index[i] for i in original_order if i in new_index]
    if current_index in new_index:
        current = new_index[current_index]
    else:
        position_ms = 0
        after = [i for i in kept if i > current_index]
        before = [i for i in kept if i < current_index]
        if current_index < 0 or not kept:
            current = -1
        elif after:
            current = new_index[after[0]]
        else:
            current = new_index[before[-1]]
    return _Kept([song_ids[i] for i in kept], original, current, position_ms)


async def get(session: AsyncSession, user: AppUser) -> Queue:
    row = await session.get(WebPlayQueue, user.id)
    if row is None:
        return Queue([], None, -1, 0, 0, None)
    entries = await browsing.get_songs(session, user, row.song_ids)
    kept = keep_available(
        row.song_ids, row.original_order, row.current_index, row.position_ms, set(entries)
    )
    return Queue(
        [entries[song_id] for song_id in kept.song_ids],
        kept.original_order,
        kept.current_index,
        kept.position_ms,
        row.revision,
        row.updated_at,
    )


async def save(
    session: AsyncSession,
    user: AppUser,
    song_ids: list[uuid.UUID],
    original_order: list[int] | None,
    current_index: int,
    position_ms: int,
) -> int:
    """Replaces the user's web queue. Returns its new revision."""
    count = len(song_ids)
    if count > MAX_SONGS:
        raise InvalidQueueError(f"A queue holds at most {MAX_SONGS} songs")
    if not -1 <= current_index < count:
        raise InvalidQueueError("currentIndex is outside the queue")
    if original_order is not None and sorted(original_order) != list(range(count)):
        raise InvalidQueueError("originalOrder must list every queue position once")
    # Created if needed, then locked: concurrent saves (two browsers) are serialized.
    await session.execute(
        insert(WebPlayQueue)
        .values(user_id=user.id, song_ids=[], current_index=-1, position_ms=0, revision=0)
        .on_conflict_do_nothing()
    )
    row = await session.get(WebPlayQueue, user.id, with_for_update=True, populate_existing=True)
    assert row is not None
    row.song_ids = song_ids
    row.original_order = original_order
    row.current_index = current_index
    row.position_ms = max(0, position_ms)
    row.revision += 1
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row.revision


async def revision(session: AsyncSession, user: AppUser) -> int:
    row = await session.get(WebPlayQueue, user.id)
    return row.revision if row else 0
