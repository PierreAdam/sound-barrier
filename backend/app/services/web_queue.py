"""The web UI's play queues, kept on the server: the Shared one (one per user, see
models.WebPlayQueue) and those of the players the user created (models.WebPlayer)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, WebPlayer, WebPlayQueue
from app.models.userdata import WebQueueMixin
from app.services import browsing
from app.services.browsing import SongEntry

MAX_SONGS = 5000
MAX_PLAYERS = 20  # per user
MAX_PLAYER_NAME = 40
SHARED_NAME = "Shared"  # the player of every browser not assigned to another


class InvalidQueueError(ValueError):
    pass


class InvalidPlayerError(ValueError):
    pass


class PlayerNameTakenError(ValueError):
    pass


class PlayerNotFoundError(LookupError):
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


async def _player(
    session: AsyncSession, user: AppUser, player_id: uuid.UUID, *, lock: bool = False
) -> WebPlayer:
    """One of the user's players (never another user's)."""
    statement = select(WebPlayer).where(WebPlayer.id == player_id, WebPlayer.user_id == user.id)
    if lock:
        statement = statement.with_for_update()
    player = await session.scalar(statement.execution_options(populate_existing=True))
    if player is None:
        raise PlayerNotFoundError("This player does not exist (deleted?)")
    return player


async def _row(
    session: AsyncSession, user: AppUser, player_id: uuid.UUID | None
) -> WebQueueMixin | None:
    if player_id is None:
        return await session.get(WebPlayQueue, user.id)
    return await _player(session, user, player_id)


async def get(session: AsyncSession, user: AppUser, player_id: uuid.UUID | None = None) -> Queue:
    """The queue of one of the user's players (None: the Shared one)."""
    row = await _row(session, user, player_id)
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
    player_id: uuid.UUID | None = None,
) -> int:
    """Replaces the queue of one of the user's players (None: the Shared one). Returns
    its new revision."""
    count = len(song_ids)
    if count > MAX_SONGS:
        raise InvalidQueueError(f"A queue holds at most {MAX_SONGS} songs")
    if not -1 <= current_index < count:
        raise InvalidQueueError("currentIndex is outside the queue")
    if original_order is not None and sorted(original_order) != list(range(count)):
        raise InvalidQueueError("originalOrder must list every queue position once")
    # Locked: concurrent saves (two browsers) are serialized.
    row: WebQueueMixin
    if player_id is None:
        # The Shared queue is created at its first save.
        await session.execute(
            insert(WebPlayQueue)
            .values(user_id=user.id, song_ids=[], current_index=-1, position_ms=0, revision=0)
            .on_conflict_do_nothing()
        )
        shared = await session.get(
            WebPlayQueue, user.id, with_for_update=True, populate_existing=True
        )
        assert shared is not None
        row = shared
    else:
        row = await _player(session, user, player_id, lock=True)
    row.song_ids = song_ids
    row.original_order = original_order
    row.current_index = current_index
    row.position_ms = max(0, position_ms)
    row.revision += 1
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row.revision


async def revision(session: AsyncSession, user: AppUser, player_id: uuid.UUID | None = None) -> int:
    row = await _row(session, user, player_id)
    return row.revision if row else 0


# --- players ----------------------------------------------------------------------


@dataclass
class Player:
    id: uuid.UUID
    name: str
    song_count: int
    created_at: datetime
    updated_at: datetime


def _out(player: WebPlayer) -> Player:
    return Player(
        player.id, player.name, len(player.song_ids), player.created_at, player.updated_at
    )


async def players(session: AsyncSession, user: AppUser) -> list[Player]:
    """The players the user created, by name (the Shared one is not listed)."""
    rows = await session.scalars(
        select(WebPlayer).where(WebPlayer.user_id == user.id).order_by(func.lower(WebPlayer.name))
    )
    return [_out(player) for player in rows]


async def shared(session: AsyncSession, user: AppUser) -> tuple[int, datetime | None]:
    """The Shared queue's song count and last save (None: never saved)."""
    row = await session.get(WebPlayQueue, user.id)
    return (len(row.song_ids), row.updated_at) if row else (0, None)


async def _check_name(
    session: AsyncSession, user: AppUser, name: str, player_id: uuid.UUID | None = None
) -> str:
    name = " ".join(name.split())
    if not name:
        raise InvalidPlayerError("A player needs a name")
    if len(name) > MAX_PLAYER_NAME:
        raise InvalidPlayerError(f"A player's name is at most {MAX_PLAYER_NAME} characters")
    if name.casefold() == SHARED_NAME.casefold():
        raise InvalidPlayerError(f"“{SHARED_NAME}” is the name of the player every browser uses")
    taken = await session.scalar(
        select(WebPlayer.id).where(
            WebPlayer.user_id == user.id,
            func.lower(WebPlayer.name) == name.lower(),
            WebPlayer.id != player_id if player_id else true(),
        )
    )
    if taken is not None:
        raise PlayerNameTakenError(f"You already have a player named “{name}”")
    return name


async def create_player(session: AsyncSession, user: AppUser, name: str) -> Player:
    """A new player, with an empty queue."""
    count = await session.scalar(
        select(func.count()).select_from(WebPlayer).where(WebPlayer.user_id == user.id)
    )
    if (count or 0) >= MAX_PLAYERS:
        raise InvalidPlayerError(f"You can have at most {MAX_PLAYERS} players")
    player = WebPlayer(
        user_id=user.id,
        name=await _check_name(session, user, name),
        song_ids=[],
        current_index=-1,
        position_ms=0,
        revision=0,
    )
    session.add(player)
    await session.flush()
    await session.refresh(player)
    return _out(player)


async def rename_player(
    session: AsyncSession, user: AppUser, player_id: uuid.UUID, name: str
) -> Player:
    player = await _player(session, user, player_id)
    player.name = await _check_name(session, user, name, player_id)
    await session.flush()
    return _out(player)


async def delete_player(session: AsyncSession, user: AppUser, player_id: uuid.UUID) -> None:
    """Deletes the player and its queue. Browsers assigned to it go back to Shared."""
    await session.delete(await _player(session, user, player_id))
    await session.flush()
