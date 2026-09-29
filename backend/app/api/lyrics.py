"""Song lyrics for the web UI's "Now playing" view (synced lines when known)."""

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.core.config import Settings
from app.services import browsing, lyrics

router = APIRouter(tags=["lyrics"])


class WordOut(ApiModel):
    start_ms: int
    text: str  # with its trailing space, if any


class LineOut(ApiModel):
    start_ms: int | None  # None: not synced
    text: str
    words: list[WordOut] | None  # word by word timing, when the lyrics have it


class LyricsOut(ApiModel):
    found: bool
    unavailable: bool = False  # LRCLIB could not be asked: try again later
    source: str | None  # "lrc", "embedded", "lrclib"
    synced: bool
    instrumental: bool
    lines: list[LineOut]


@router.get("/songs/{song_id}/lyrics")
async def song_lyrics(
    song_id: uuid.UUID, request: Request, caller: CurrentCaller, session: DbSession
) -> LyricsOut:
    if await browsing.get_song(session, caller.user, song_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown song")
    settings: Settings = request.app.state.settings
    try:
        found = await lyrics.get(
            session, song_id, http=request.app.state.http, data_dir=Path(settings.data_dir)
        )
    except lyrics.LyricsUnavailableError:
        return LyricsOut(
            found=False, unavailable=True, source=None, synced=False, instrumental=False, lines=[]
        )
    if found is None:
        return LyricsOut(found=False, source=None, synced=False, instrumental=False, lines=[])
    return LyricsOut(
        found=True,
        source=found.source,
        synced=found.synced,
        instrumental=found.instrumental,
        lines=[
            LineOut(
                start_ms=line.start_ms,
                text=line.text,
                words=[WordOut(start_ms=w.start_ms, text=w.text) for w in line.words]
                if line.words
                else None,
            )
            for line in found.lines
        ],
    )
