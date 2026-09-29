"""Information from external services: getArtistInfo(2), getAlbumInfo(2), getTopSongs,
getSimilarSongs(2) (Last.fm; similar songs are songs of the library).

The v1 endpoints are for folder-browsing clients (getIndexes, getMusicDirectory): their
ids may be folders, mapped here to the artist or album they hold.
"""

import uuid
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.text import normalize
from app.models import Album, Artist, Directory, Song
from app.services import album_info, artist_info, browsing, folders, similar_songs
from app.services.artist_info import ArtistDetails
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import SubsonicError
from app.subsonic.router import SubsonicContext, registry

MAX_COUNT = 100
# Similar artists that are not in the library (includeNotPresent) have no id of ours.
NOT_PRESENT_ID = "-1"


def _pictures_dir(ctx: SubsonicContext) -> Path:
    settings: Settings = ctx.request.app.state.settings
    return Path(settings.data_dir) / "artist-pictures"


async def _details(ctx: SubsonicContext, artist: Artist, top_songs: int) -> ArtistDetails:
    state = ctx.request.app.state
    details = await artist_info.get(
        ctx.session,
        ctx.user,
        artist.id,
        http=state.http,
        cipher=state.cipher,
        pictures_dir=_pictures_dir(ctx),
        top_songs=top_songs,
    )
    if details is None:
        raise SubsonicError.not_found("Artist")
    return details


def _count(ctx: SubsonicContext, default: int) -> int:
    return min(max(ctx.params.get_int("count", default) or 0, 0), MAX_COUNT)


def _include_not_present(ctx: SubsonicContext) -> bool:
    return (ctx.params.get("includeNotPresent") or "").lower() == "true"


async def _artist(ctx: SubsonicContext, *, folders_too: bool) -> Artist:
    """The artist of the `id` parameter: an artist id, or (v1) a folder id."""
    item_id = browsing.parse_id(ctx.params.require("id"))
    artist = await ctx.session.get(Artist, item_id) if item_id else None
    if artist is None and item_id and folders_too:
        directory = await ctx.session.get(Directory, item_id)
        artist_id = await folders.artist_of_directory(ctx.session, directory) if directory else None
        artist = await ctx.session.get(Artist, artist_id) if artist_id else None
    if artist is None or artist.missing_since is not None:
        raise SubsonicError.not_found("Artist")
    return artist


@registry.endpoint("getArtistInfo2")
async def get_artist_info2(ctx: SubsonicContext) -> Payload:
    artist = await _artist(ctx, folders_too=False)
    count = _count(ctx, 20)
    details = await _details(ctx, artist, top_songs=0)
    similar: list[schemas.ArtistID3] = []
    for entry in details.similar:
        if len(similar) >= count:
            break
        if entry.artist_id is None:
            if _include_not_present(ctx):
                similar.append(schemas.ArtistID3(id=NOT_PRESENT_ID, name=entry.name, album_count=0))
            continue
        found = await browsing.get_artist(ctx.session, ctx.user, entry.artist_id)
        if found is not None:
            similar.append(mappers.artist(found[0]))
    return {
        "artistInfo2": schemas.ArtistInfo2(
            biography=details.biography or details.summary,
            music_brainz_id=artist.mbz_artist_id,
            last_fm_url=details.lastfm_url,
            similar_artist=similar,
        )
    }


@registry.endpoint("getArtistInfo")
async def get_artist_info(ctx: SubsonicContext) -> Payload:
    """Folder browsing: `id` is an artist folder (or an artist); similar artists are given
    as their folders."""
    artist = await _artist(ctx, folders_too=True)
    count = _count(ctx, 20)
    details = await _details(ctx, artist, top_songs=0)
    similar: list[schemas.Artist] = []
    for entry in details.similar:
        if len(similar) >= count:
            break
        directory = (
            await folders.directory_of_artist(ctx.session, entry.artist_id)
            if entry.artist_id
            else None
        )
        if directory is not None:
            similar.append(schemas.Artist(id=str(directory.id), name=entry.name))
        elif _include_not_present(ctx):
            similar.append(schemas.Artist(id=NOT_PRESENT_ID, name=entry.name))
    return {
        "artistInfo": schemas.ArtistInfo(
            biography=details.biography or details.summary,
            music_brainz_id=artist.mbz_artist_id,
            last_fm_url=details.lastfm_url,
            similar_artist=similar,
        )
    }


async def _album_info(ctx: SubsonicContext, *, folders_too: bool) -> schemas.AlbumInfo:
    item_id = browsing.parse_id(ctx.params.require("id"))
    album_id: uuid.UUID | None = (
        item_id if item_id and await ctx.session.get(Album, item_id) else None
    )
    if album_id is None and item_id and folders_too:
        directory = await ctx.session.get(Directory, item_id)
        album_id = await folders.album_of_directory(ctx.session, directory) if directory else None
    state = ctx.request.app.state
    details = (
        await album_info.get(ctx.session, album_id, http=state.http, cipher=state.cipher)
        if album_id
        else None
    )
    if details is None:
        raise SubsonicError.not_found("Album")
    return schemas.AlbumInfo(
        notes=details.notes,
        music_brainz_id=details.album.mbz_album_id,
        last_fm_url=details.lastfm_url,
    )


@registry.endpoint("getAlbumInfo2")
async def get_album_info2(ctx: SubsonicContext) -> Payload:
    return {"albumInfo": await _album_info(ctx, folders_too=False)}


@registry.endpoint("getAlbumInfo")
async def get_album_info(ctx: SubsonicContext) -> Payload:
    """Folder browsing: `id` is an album folder (or an album)."""
    return {"albumInfo": await _album_info(ctx, folders_too=True)}


async def _similar(ctx: SubsonicContext, artist: Artist) -> list[schemas.Child]:
    state = ctx.request.app.state
    songs = await similar_songs.similar_songs(
        ctx.session,
        ctx.user,
        artist.id,
        _count(ctx, 50),
        http=state.http,
        cipher=state.cipher,
        pictures_dir=_pictures_dir(ctx),
    )
    if songs is None:
        raise SubsonicError.not_found("Artist")
    return [mappers.song(entry) for entry in songs]


@registry.endpoint("getSimilarSongs2")
async def get_similar_songs2(ctx: SubsonicContext) -> Payload:
    artist = await _artist(ctx, folders_too=False)
    return {"similarSongs2": schemas.SimilarSongs(song=await _similar(ctx, artist))}


@registry.endpoint("getSimilarSongs")
async def get_similar_songs(ctx: SubsonicContext) -> Payload:
    """`id` is an artist, an album, a song or a folder: the mix starts from its artist."""
    item_id = browsing.parse_id(ctx.params.require("id"))
    artist_id: uuid.UUID | None = None
    if item_id:
        song = await ctx.session.get(Song, item_id)
        album = await ctx.session.get(Album, song.album_id if song else item_id)
        if album is not None:
            artist_id = album.artist_id
        elif await ctx.session.get(Artist, item_id) is not None:
            artist_id = item_id
        else:
            directory = await ctx.session.get(Directory, item_id)
            if directory is not None:
                artist_id = await folders.artist_of_directory(ctx.session, directory)
    artist = await ctx.session.get(Artist, artist_id) if artist_id else None
    if artist is None or artist.missing_since is not None:
        raise SubsonicError.not_found("Artist, album or song")
    return {"similarSongs": schemas.SimilarSongs(song=await _similar(ctx, artist))}


@registry.endpoint("getTopSongs")
async def get_top_songs(ctx: SubsonicContext) -> Payload:
    name = ctx.params.require("artist")
    count = _count(ctx, 50)
    artist = await ctx.session.scalar(
        select(Artist)
        .where(Artist.name_search == normalize(name), Artist.missing_since.is_(None))
        .order_by(Artist.album_count.desc())
        .limit(1)
    )
    if artist is None:
        return {"topSongs": schemas.TopSongs()}
    details = await _details(ctx, artist, top_songs=count)
    return {"topSongs": schemas.TopSongs(song=[mappers.song(e) for e in details.top_songs])}
