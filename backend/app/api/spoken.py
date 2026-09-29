"""Podcasts and audiobooks pages of the web UI (services/spoken.py)."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.api.songs import web_song
from app.services import bookmarks, browsing, music_folders, spoken

router = APIRouter(prefix="/spoken", tags=["podcasts and audiobooks"])


class ShowOut(ApiModel):
    id: uuid.UUID
    kind: str  # podcasts, audiobooks
    title: str
    author: str
    cover_art: str | None
    episodes: int
    duration_ms: int
    latest: datetime | None  # the newest episode's file date
    started: int  # episodes / chapters with a bookmark
    played: int  # listened to (played, no bookmark left)


class ResumeOut(ApiModel):
    show: ShowOut
    episode: dict[str, Any]  # Child, with bookmarkPosition
    changed_at: datetime


class SpokenPageOut(ApiModel):
    continue_listening: list[ResumeOut]
    shows: list[ShowOut]


class ShowPageOut(ApiModel):
    show: ShowOut
    episodes: list[dict[str, Any]]  # Child, in listening order


def _show(show: spoken.Show) -> ShowOut:
    album = show.album
    return ShowOut(
        id=album.id,
        kind=show.kind,
        title=album.name,
        author=album.display_artist,
        cover_art=str(album.artwork_id) if album.artwork_id else None,
        episodes=len(show.episodes),
        duration_ms=show.duration_ms,
        latest=show.latest,
        started=sum(1 for e in show.episodes if e.bookmark_ms is not None),
        played=sum(1 for e in show.episodes if e.play_count and e.bookmark_ms is None),
    )


@router.get("/{kind}")
async def spoken_page(kind: str, caller: CurrentCaller, session: DbSession) -> SpokenPageOut:
    """Continue listening, then every show / book of a kind (podcasts, audiobooks)."""
    if kind not in music_folders.SPOKEN_KINDS or not await browsing.spoken_folder_ids(
        session, caller.user, kind
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not available")
    resumes = await spoken.continue_listening(session, caller.user, (kind,))
    found = await spoken.shows(session, caller.user, (kind,))
    return SpokenPageOut(
        continue_listening=[
            ResumeOut(show=_show(r.show), episode=web_song(r.episode), changed_at=r.changed_at)
            for r in resumes
        ],
        shows=[_show(s) for s in found],
    )


@router.get("/shows/{album_id}")
async def show_page(album_id: uuid.UUID, caller: CurrentCaller, session: DbSession) -> ShowPageOut:
    found = await spoken.show(session, caller.user, album_id)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown show or book")
    return ShowPageOut(show=_show(found), episodes=[web_song(e) for e in found.episodes])


@router.delete("/shows/{album_id}/bookmarks", status_code=status.HTTP_204_NO_CONTENT)
async def forget_show(album_id: uuid.UUID, caller: CurrentCaller, session: DbSession) -> None:
    """Removes the user's bookmarks of a show / book: out of "Continue listening"
    (dismissed), or started over."""
    if await spoken.show(session, caller.user, album_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown show or book")
    await bookmarks.remove_for_album(session, caller.user, album_id)
    await session.commit()
