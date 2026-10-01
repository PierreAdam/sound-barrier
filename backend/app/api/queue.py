"""The web UI's play queues: the Shared one (every browser not assigned to a player), or
a player's (`?player=`, see api/players.py). A player that is not the caller's (or no
longer exists) is a 404: the browser goes back to Shared.

Subsonic clients keep their own queue (getPlayQueue / savePlayQueue): the two never mix.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import Field

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.api.songs import web_song
from app.services import spoken, web_queue

router = APIRouter(prefix="/queue", tags=["queue"])


class QueueOut(ApiModel):
    revision: int  # 0: never saved
    # Songs in the Subsonic JSON format ("Child"), as the web UI gets them from /rest.
    songs: list[dict[str, Any]]
    original_order: list[int] | None
    current_index: int
    position_ms: int
    updated_at: datetime | None


class QueueIn(ApiModel):
    song_ids: list[uuid.UUID] = Field(max_length=web_queue.MAX_SONGS)
    original_order: list[int] | None = None
    current_index: int = -1
    position_ms: int = 0


class RevisionOut(ApiModel):
    revision: int


def _not_found(error: web_queue.PlayerNotFoundError) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, str(error))


@router.get("")
async def get_queue(
    caller: CurrentCaller, session: DbSession, player: uuid.UUID | None = None
) -> QueueOut:
    try:
        queue = await web_queue.get(session, caller.user, player)
    except web_queue.PlayerNotFoundError as error:
        raise _not_found(error) from None
    places = await spoken.book_places_of(session, caller.user, queue.songs)
    return QueueOut(
        revision=queue.revision,
        songs=[web_song(entry, places.get(entry.song.id)) for entry in queue.songs],
        original_order=queue.original_order,
        current_index=queue.current_index,
        position_ms=queue.position_ms,
        updated_at=queue.updated_at,
    )


@router.put("")
async def save_queue(
    body: QueueIn, caller: CurrentCaller, session: DbSession, player: uuid.UUID | None = None
) -> RevisionOut:
    try:
        revision = await web_queue.save(
            session,
            caller.user,
            body.song_ids,
            body.original_order,
            body.current_index,
            body.position_ms,
            player,
        )
    except web_queue.InvalidQueueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    except web_queue.PlayerNotFoundError as error:
        raise _not_found(error) from None
    await session.commit()
    return RevisionOut(revision=revision)


@router.get("/revision")
async def get_revision(
    caller: CurrentCaller, session: DbSession, player: uuid.UUID | None = None
) -> RevisionOut:
    """Cheap check: has another browser changed the queue?"""
    try:
        return RevisionOut(revision=await web_queue.revision(session, caller.user, player))
    except web_queue.PlayerNotFoundError as error:
        raise _not_found(error) from None
