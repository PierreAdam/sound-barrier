"""The web UI's play queue (one per user, shared by all their browsers).

Subsonic clients keep their own queue (getPlayQueue / savePlayQueue): the two never mix.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import Field

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.services import web_queue
from app.subsonic import mappers

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


@router.get("")
async def get_queue(caller: CurrentCaller, session: DbSession) -> QueueOut:
    queue = await web_queue.get(session, caller.user)
    return QueueOut(
        revision=queue.revision,
        songs=[
            mappers.song(entry).model_dump(mode="json", by_alias=True, exclude_none=True)
            for entry in queue.songs
        ],
        original_order=queue.original_order,
        current_index=queue.current_index,
        position_ms=queue.position_ms,
        updated_at=queue.updated_at,
    )


@router.put("")
async def save_queue(body: QueueIn, caller: CurrentCaller, session: DbSession) -> RevisionOut:
    try:
        revision = await web_queue.save(
            session,
            caller.user,
            body.song_ids,
            body.original_order,
            body.current_index,
            body.position_ms,
        )
    except web_queue.InvalidQueueError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    await session.commit()
    return RevisionOut(revision=revision)


@router.get("/revision")
async def get_revision(caller: CurrentCaller, session: DbSession) -> RevisionOut:
    """Cheap check: has another browser changed the queue?"""
    return RevisionOut(revision=await web_queue.revision(session, caller.user))
