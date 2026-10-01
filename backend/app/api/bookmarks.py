"""The web player's bookmarks (audiobooks and podcasts), followed across devices: see
services/bookmarks.py. Subsonic apps use getBookmarks / createBookmark / deleteBookmark.

`seen` is the `changedAt` of the latest bookmark the browser knew, sent back as it was
given: compared here, at the database's precision (JavaScript dates would lose it).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import Field

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.models import Bookmark
from app.services import bookmarks

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


class BookmarkOut(ApiModel):
    song_id: uuid.UUID
    position_ms: int
    changed_at: datetime
    source: str | None


def _bookmark(found: Bookmark | None) -> BookmarkOut | None:
    if found is None:
        return None
    return BookmarkOut(
        song_id=found.song_id,
        position_ms=found.position_ms,
        changed_at=found.changed_at,
        source=found.source,
    )


class LatestOut(ApiModel):
    bookmark: BookmarkOut | None  # of the book (any of its files) or of the episode
    moved: bool  # saved by someone after `seen`


@router.get("/latest")
async def latest(
    song: uuid.UUID, caller: CurrentCaller, session: DbSession, seen: datetime | None = None
) -> LatestOut:
    found = await bookmarks.latest(session, caller.user, song)
    return LatestOut(bookmark=_bookmark(found), moved=bookmarks.moved_since(found, seen))


class SaveIn(ApiModel):
    position_ms: int = Field(ge=0)
    seen: datetime | None = None
    source: str | None = Field(default=None, max_length=bookmarks.MAX_SOURCE)


class CheckedOut(ApiModel):
    saved: bool  # False: refused, someone saved after `seen` (`bookmark` is theirs)
    bookmark: BookmarkOut | None  # the latest, after the change when saved


def _checked(result: bookmarks.Checked) -> CheckedOut:
    return CheckedOut(saved=result.done, bookmark=_bookmark(result.latest))


@router.put("/{song_id}")
async def save(
    song_id: uuid.UUID, body: SaveIn, caller: CurrentCaller, session: DbSession
) -> CheckedOut:
    result = await bookmarks.save_checked(
        session, caller.user, song_id, body.position_ms, body.seen, body.source
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown song")
    await session.commit()
    return _checked(result)


@router.delete("/{song_id}")
async def remove(
    song_id: uuid.UUID, caller: CurrentCaller, session: DbSession, seen: datetime | None = None
) -> CheckedOut:
    """Listened to the end: the bookmark goes (unless someone saved after `seen`)."""
    result = await bookmarks.remove_checked(session, caller.user, song_id, seen)
    await session.commit()
    return _checked(result)
