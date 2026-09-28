"""Annotations: scrobble (plays), star, unstar, setRating, getStarred(2), getNowPlaying."""

import uuid
from datetime import UTC, datetime

from app.core.text import normalize
from app.services import annotations, browsing, folders, plays
from app.services.annotations import Kind, UnknownItemError
from app.services.browsing import FolderNotAccessibleError
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.router import SubsonicContext, registry


def _time(value: str | None) -> datetime | None:
    """`time`: milliseconds since the epoch."""
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC)
    except (ValueError, OverflowError, OSError):
        raise SubsonicError(ErrorCode.GENERIC, f"Invalid time: {value}") from None


@registry.endpoint("scrobble")
async def scrobble(ctx: SubsonicContext) -> Payload:
    ids = ctx.params.get_all("id")
    if not ids:
        raise SubsonicError.missing("id")
    song_ids = [song_id for song_id in map(browsing.parse_id, ids) if song_id is not None]
    handled = await plays.scrobble(
        ctx.session,
        ctx.user,
        song_ids,
        [_time(t) for t in ctx.params.get_all("time")],
        submission=ctx.params.get_bool("submission", default=True),
        client=ctx.client,
    )
    if not handled:
        raise SubsonicError.not_found("Song")
    return {}


# --- stars and ratings -------------------------------------------------------------


def _ids(ctx: SubsonicContext, name: str) -> list[uuid.UUID]:
    parsed = [browsing.parse_id(value) for value in ctx.params.get_all(name)]
    found = [item for item in parsed if item is not None]
    if len(found) != len(parsed):
        raise SubsonicError.not_found("Item")
    return found


def _pairs(kind: Kind | None, ids: list[uuid.UUID]) -> list[tuple[Kind | None, uuid.UUID]]:
    return [(kind, item_id) for item_id in ids]


async def _star(ctx: SubsonicContext, starred: bool) -> Payload:
    items = _pairs(None, _ids(ctx, "id"))  # kind found from the id
    items += _pairs("album", _ids(ctx, "albumId"))
    items += _pairs("artist", _ids(ctx, "artistId"))
    if not items:
        raise SubsonicError.missing("id")
    try:
        await annotations.star(ctx.session, ctx.user, items, starred)
    except UnknownItemError:
        raise SubsonicError.not_found("Item") from None
    return {}


@registry.endpoint("star")
async def star(ctx: SubsonicContext) -> Payload:
    return await _star(ctx, True)


@registry.endpoint("unstar")
async def unstar(ctx: SubsonicContext) -> Payload:
    return await _star(ctx, False)


@registry.endpoint("setRating")
async def set_rating(ctx: SubsonicContext) -> Payload:
    item_id = browsing.parse_id(ctx.params.require("id"))
    rating = ctx.params.require_int("rating")
    if not 0 <= rating <= 5:
        raise SubsonicError(ErrorCode.GENERIC, "rating must be between 0 and 5")
    if item_id is None:
        raise SubsonicError.not_found("Item")
    try:
        await annotations.set_rating(ctx.session, ctx.user, item_id, rating)
    except UnknownItemError:
        raise SubsonicError.not_found("Item") from None
    return {}


async def _starred(ctx: SubsonicContext) -> annotations.Starred:
    try:
        return await annotations.starred(ctx.session, ctx.user, ctx.params.get_int("musicFolderId"))
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None


@registry.endpoint("getStarred2")
async def get_starred2(ctx: SubsonicContext) -> Payload:
    found = await _starred(ctx)
    return {
        "starred2": schemas.Starred2(
            artist=[mappers.artist(e) for e in found.artists],
            album=[mappers.album(e) for e in found.albums],
            song=[mappers.song(e) for e in found.songs],
        )
    }


@registry.endpoint("getStarred")
async def get_starred(ctx: SubsonicContext) -> Payload:
    """Folder flavour: starred albums as their folders, starred artists as the index
    folder of the same name."""
    found = await _starred(ctx)
    top, _ = await folders.top_folders(ctx.session, ctx.user)
    by_name = {normalize(d.name): d for d in top}
    artist_folders: list[schemas.Artist] = []
    for entry in found.artists:
        directory = by_name.get(normalize(entry.artist.name))
        if directory is not None:
            artist_folders.append(
                schemas.Artist(id=str(directory.id), name=directory.name, starred=entry.starred_at)
            )
    albums = await folders.album_folders(ctx.session, found.albums)
    return {
        "starred": schemas.Starred(
            artist=artist_folders,
            album=[mappers.folder(e.directory, e.album) for e in albums],
            song=[mappers.song(e) for e in found.songs],
        )
    }


# --- now playing ---------------------------------------------------------------------


@registry.endpoint("getNowPlaying")
async def get_now_playing(ctx: SubsonicContext) -> Payload:
    entries = await plays.now_playing(ctx.session, ctx.user)
    return {
        "nowPlaying": schemas.NowPlaying(
            entry=[
                schemas.NowPlayingEntry(
                    **dict(mappers.song(e.song)),
                    username=e.username,
                    minutes_ago=e.minutes_ago,
                    player_id=0,
                    player_name=e.client,
                )
                for e in entries
            ]
        )
    }
