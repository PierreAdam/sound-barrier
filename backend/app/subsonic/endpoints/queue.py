"""The apps' play queue: getPlayQueue, savePlayQueue and the OpenSubsonic index-based
variants (a song queued twice is not ambiguous)."""

import uuid

from app.services import app_queue, browsing
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.router import SubsonicContext, registry


async def _known(ctx: SubsonicContext, index: int | None) -> tuple[list[uuid.UUID], int | None]:
    """The queued ids the caller may play (others are dropped), and the current index
    moved accordingly."""
    ids = [song_id for song_id in map(browsing.parse_id, ctx.params.get_all("id")) if song_id]
    songs = await browsing.get_songs(ctx.session, ctx.user, ids)
    kept: list[uuid.UUID] = []
    new_index = None
    for position, song_id in enumerate(ids):
        if song_id in songs:
            if position == index:
                new_index = len(kept)
            kept.append(song_id)
    return kept, new_index


async def _save(ctx: SubsonicContext, ids: list[uuid.UUID], index: int | None) -> Payload:
    try:
        await app_queue.save(
            ctx.session,
            ctx.user,
            ids,
            current_index=index,
            position_ms=ctx.params.get_int("position", 0) or 0,
            client=ctx.client,
        )
    except app_queue.InvalidQueueError as error:
        raise SubsonicError(ErrorCode.GENERIC, str(error)) from None
    return {}


@registry.endpoint("savePlayQueue")
async def save_play_queue(ctx: SubsonicContext) -> Payload:
    raw = [browsing.parse_id(value) for value in ctx.params.get_all("id")]
    current = browsing.parse_id(ctx.params.get("current") or "")
    index = raw.index(current) if current is not None and current in raw else None
    ids, index = await _known(ctx, index)
    return await _save(ctx, ids, index)


@registry.endpoint("savePlayQueueByIndex")
async def save_play_queue_by_index(ctx: SubsonicContext) -> Payload:
    ids, index = await _known(ctx, ctx.params.get_int("currentIndex"))
    return await _save(ctx, ids, index)


@registry.endpoint("getPlayQueue")
async def get_play_queue(ctx: SubsonicContext) -> Payload:
    queue = await app_queue.get(ctx.session, ctx.user)
    if queue is None:
        return {}  # never saved: no playQueue element
    current = queue.songs[queue.current_index] if queue.current_index is not None else None
    return {
        "playQueue": schemas.PlayQueue(
            current=str(current.song.id) if current else None,
            position=queue.position_ms,
            username=ctx.user.username,
            changed=queue.changed_at,
            changed_by=queue.changed_by,
            entry=[mappers.song(s) for s in queue.songs],
        )
    }


@registry.endpoint("getPlayQueueByIndex")
async def get_play_queue_by_index(ctx: SubsonicContext) -> Payload:
    queue = await app_queue.get(ctx.session, ctx.user)
    if queue is None:
        return {}
    return {
        "playQueueByIndex": schemas.PlayQueueByIndex(
            current_index=queue.current_index,
            position=queue.position_ms,
            username=ctx.user.username,
            changed=queue.changed_at,
            changed_by=queue.changed_by,
            entry=[mappers.song(s) for s in queue.songs],
        )
    }
