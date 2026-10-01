"""The server player (services/server_player.py). It is driven like any other player,
through remote control (the web UI's remote mode); these routes start and stop it, and
serve its stream, `/api/stream/<key>`, which needs no sign-in (a Chromecast has no
session): the key is the permission.

Under the stream, for the Cast receiver (a "Now playing" screen on the TV, a page of
another origin: CORS): what plays (`now`), the covers and lyrics of what is queued. The
same key, and only what that player plays.
"""

import hashlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import ApiModel, CurrentCaller, DbSession
from app.api.lyrics import LyricsOut, lyrics_out
from app.core.config import Settings
from app.services import lyrics, media, server_settings
from app.services.server_player import ServerPlayer, ServerPlayers, ffmpeg_path, library_files

# Readable by the receiver's page, wherever it is hosted: the key is the permission.
_CORS = {"Access-Control-Allow-Origin": "*"}

router = APIRouter(tags=["server-player"])


class SettingsIn(ApiModel):
    always_on: bool  # plays even when nobody listens (a radio)


def _players(request: Request) -> ServerPlayers:
    return request.app.state.server_players


def _stream_url(request: Request, key: str) -> str:
    settings: Settings = request.app.state.settings
    base = settings.public_url or str(request.base_url)
    return f"{base.rstrip('/')}/api/stream/{key}"


async def _out(request: Request, session: DbSession, player: ServerPlayer) -> dict[str, Any]:
    info = player.info()
    external = await server_settings.get_external_services(session)
    return {
        **info,
        "streamUrl": _stream_url(request, info["key"]),
        # The "Now playing" screen on Chromecasts, through DashCast (if allowed).
        "dashcast": external.dashcast,
    }


@router.post("/server-player")
async def start(request: Request, caller: CurrentCaller, session: DbSession) -> dict[str, Any]:
    """Starts the caller's server player (the running one if there is one): it appears in
    their Remote menu (its `target`), with an empty queue."""
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ffmpeg is not installed")
    resolve = library_files(request.app.state.db, caller.user.id)
    player = await _players(request).ensure(caller.user.id, ffmpeg, resolve)
    return await _out(request, session, player)


@router.get("/server-player")
async def get_player(
    request: Request, caller: CurrentCaller, session: DbSession
) -> dict[str, Any] | None:
    """The caller's server player, None when not started."""
    player = _players(request).of(caller.user.id)
    return None if player is None else await _out(request, session, player)


@router.put("/server-player")
async def update(
    body: SettingsIn, request: Request, caller: CurrentCaller, session: DbSession
) -> dict[str, Any]:
    player = _players(request).of(caller.user.id)
    if player is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No server player")
    player.set_always_on(body.always_on)
    return await _out(request, session, player)


@router.delete("/server-player", status_code=status.HTTP_204_NO_CONTENT)
async def stop(request: Request, caller: CurrentCaller) -> None:
    await _players(request).remove(caller.user.id)


def _by_key(request: Request, key: str) -> ServerPlayer:
    player = _players(request).by_key(key)
    if player is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such stream", headers=_CORS)
    return player


def _queued(player: ServerPlayer, item: str) -> None:
    """Only what this player plays, or played a moment ago."""
    if item not in player.queued_ids():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not queued here", headers=_CORS)


# A listener's name (the Cast receiver's): short, random.
_LISTENER = Query(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


@router.get("/stream/{key}/now")
async def stream_now(
    key: str, request: Request, response: Response, listener: str | None = _LISTENER
) -> dict[str, Any]:
    response.headers.update({**_CORS, "Cache-Control": "no-store"})
    return _by_key(request, key).now(listener)


@router.get("/stream/{key}/cover")
async def stream_cover(
    key: str, id: str, request: Request, session: DbSession, size: int | None = None
) -> Response:
    player = _by_key(request, key)
    _queued(player, id)
    settings: Settings = request.app.state.settings
    image = await media.cover_image(
        session,
        id,
        size,
        settings.data_dir / "cache" / "covers",
        settings.data_dir / "artist-pictures",
    )
    if image is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cover", headers=_CORS)
    etag = f'"{hashlib.sha1(image.data).hexdigest()[:20]}"'
    return Response(
        image.data,
        media_type=image.content_type,
        headers={**_CORS, "Cache-Control": "private, max-age=3600", "ETag": etag},
    )


@router.get("/stream/{key}/lyrics")
async def stream_lyrics(
    key: str, song: uuid.UUID, request: Request, response: Response, session: DbSession
) -> LyricsOut:
    player = _by_key(request, key)
    _queued(player, str(song))
    response.headers.update(_CORS)
    settings: Settings = request.app.state.settings
    try:
        found = await lyrics.get(
            session, song, http=request.app.state.http, data_dir=Path(settings.data_dir)
        )
    except lyrics.LyricsUnavailableError:
        return LyricsOut(
            found=False, unavailable=True, source=None, synced=False, instrumental=False, lines=[]
        )
    return lyrics_out(found)


@router.get("/stream/{key}")
async def stream(key: str, request: Request, listener: str | None = _LISTENER) -> StreamingResponse:
    player = _by_key(request, key)

    async def body() -> AsyncIterator[bytes]:
        async for chunk in player.listen(listener):
            if await request.is_disconnected():
                return
            yield chunk

    return StreamingResponse(
        body(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache, no-store",
            # Receivers (Chromecast) are pages of another origin; the key is the permission.
            "Access-Control-Allow-Origin": "*",
        },
    )
