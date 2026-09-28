"""Playlists: getPlaylists, getPlaylist, createPlaylist, updatePlaylist, deletePlaylist."""

import uuid

from app.services import browsing, playlists
from app.services.playlists import (
    PlaylistNotFoundError,
    PlaylistPermissionError,
    PlaylistSummary,
)
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.router import SubsonicContext, registry


def _playlist(summary: PlaylistSummary) -> schemas.Playlist:
    p = summary.playlist
    return schemas.Playlist(
        id=str(p.id),
        name=p.name,
        comment=p.comment,
        owner=summary.owner,
        public=p.is_public,
        song_count=summary.song_count,
        duration=round(summary.duration_ms / 1000),
        created=p.created_at,
        changed=p.changed_at,
        cover_art=summary.cover_art,
    )


def _song_ids(ctx: SubsonicContext, name: str) -> list[uuid.UUID]:
    return [i for i in map(browsing.parse_id, ctx.params.get_all(name)) if i is not None]


def _playlist_id(ctx: SubsonicContext, name: str) -> uuid.UUID:
    playlist_id = browsing.parse_id(ctx.params.require(name))
    if playlist_id is None:
        raise SubsonicError.not_found("Playlist")
    return playlist_id


async def _with_songs(ctx: SubsonicContext, playlist_id: uuid.UUID) -> Payload:
    summary, songs = await playlists.get(ctx.session, ctx.user, playlist_id)
    return {
        "playlist": schemas.PlaylistWithSongs(
            **dict(_playlist(summary)), entry=[mappers.song(s) for s in songs]
        )
    }


def _errors(error: Exception) -> SubsonicError:
    if isinstance(error, PlaylistNotFoundError):
        return SubsonicError.not_found("Playlist")
    if isinstance(error, PlaylistPermissionError):
        return SubsonicError.not_authorized(str(error))
    return SubsonicError(ErrorCode.GENERIC, str(error))


@registry.endpoint("getPlaylists")
async def get_playlists(ctx: SubsonicContext) -> Payload:
    found = await playlists.visible(ctx.session, ctx.user)
    return {"playlists": schemas.Playlists(playlist=[_playlist(p) for p in found])}


@registry.endpoint("getPlaylist")
async def get_playlist(ctx: SubsonicContext) -> Payload:
    try:
        return await _with_songs(ctx, _playlist_id(ctx, "id"))
    except PlaylistNotFoundError as error:
        raise _errors(error) from None


@registry.endpoint("createPlaylist")
async def create_playlist(ctx: SubsonicContext) -> Payload:
    """With `playlistId`: replaces that playlist's songs. Else a new one named `name`."""
    songs = _song_ids(ctx, "songId")
    try:
        if ctx.params.get("playlistId"):
            playlist_id = _playlist_id(ctx, "playlistId")
            await playlists.replace_songs(ctx.session, ctx.user, playlist_id, songs)
        else:
            playlist_id = await playlists.create(
                ctx.session, ctx.user, ctx.params.require("name"), songs
            )
        return await _with_songs(ctx, playlist_id)
    except (PlaylistNotFoundError, PlaylistPermissionError, ValueError) as error:
        raise _errors(error) from None


@registry.endpoint("updatePlaylist")
async def update_playlist(ctx: SubsonicContext) -> Payload:
    public = ctx.params.get("public")
    try:
        await playlists.update(
            ctx.session,
            ctx.user,
            _playlist_id(ctx, "playlistId"),
            name=ctx.params.get("name"),
            comment=ctx.params.get("comment"),
            public=None if public is None else ctx.params.get_bool("public"),
            add=_song_ids(ctx, "songIdToAdd"),
            remove_indexes=[
                int(i) for i in ctx.params.get_all("songIndexToRemove") if i.strip().isdigit()
            ],
        )
    except (PlaylistNotFoundError, PlaylistPermissionError, ValueError) as error:
        raise _errors(error) from None
    return {}


@registry.endpoint("deletePlaylist")
async def delete_playlist(ctx: SubsonicContext) -> Payload:
    try:
        await playlists.remove(ctx.session, ctx.user, _playlist_id(ctx, "id"))
    except (PlaylistNotFoundError, PlaylistPermissionError) as error:
        raise _errors(error) from None
    return {}
