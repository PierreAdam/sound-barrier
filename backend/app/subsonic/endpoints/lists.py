"""Lists and search (ID3): getAlbumList2, search3, getRandomSongs, getSongsByGenre,
getGenres."""

from app.services import browsing
from app.services.browsing import FolderNotAccessibleError, InvalidAlbumListError
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.router import SubsonicContext, registry


@registry.endpoint("getAlbumList2")
async def get_album_list2(ctx: SubsonicContext) -> Payload:
    params = ctx.params
    try:
        entries = await browsing.album_list(
            ctx.session,
            ctx.user,
            params.require("type"),
            size=params.get_int("size", 10) or 0,
            offset=params.get_int("offset", 0) or 0,
            music_folder_id=params.get_int("musicFolderId"),
            from_year=params.get_int("fromYear"),
            to_year=params.get_int("toYear"),
            genre=params.get("genre"),
        )
    except InvalidAlbumListError as error:
        raise SubsonicError(ErrorCode.GENERIC, str(error)) from None
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None
    return {"albumList2": schemas.AlbumList2(album=[mappers.album(e) for e in entries])}


@registry.endpoint("search3")
async def search3(ctx: SubsonicContext) -> Payload:
    params = ctx.params
    try:
        result = await browsing.search(
            ctx.session,
            ctx.user,
            params.get("query") or "",
            artist_count=params.get_int("artistCount", 20) or 0,
            artist_offset=params.get_int("artistOffset", 0) or 0,
            album_count=params.get_int("albumCount", 20) or 0,
            album_offset=params.get_int("albumOffset", 0) or 0,
            song_count=params.get_int("songCount", 20) or 0,
            song_offset=params.get_int("songOffset", 0) or 0,
            music_folder_id=params.get_int("musicFolderId"),
        )
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None
    return {
        "searchResult3": schemas.SearchResult3(
            artist=[mappers.artist(e) for e in result.artists],
            album=[mappers.album(e) for e in result.albums],
            song=[mappers.song(e) for e in result.songs],
        )
    }


@registry.endpoint("getRandomSongs")
async def get_random_songs(ctx: SubsonicContext) -> Payload:
    params = ctx.params
    try:
        songs = await browsing.random_songs(
            ctx.session,
            ctx.user,
            size=params.get_int("size", 10) or 0,
            genre=params.get("genre"),
            from_year=params.get_int("fromYear"),
            to_year=params.get_int("toYear"),
            music_folder_id=params.get_int("musicFolderId"),
        )
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None
    return {"randomSongs": schemas.Songs(song=[mappers.song(s) for s in songs])}


@registry.endpoint("getSongsByGenre")
async def get_songs_by_genre(ctx: SubsonicContext) -> Payload:
    params = ctx.params
    try:
        songs = await browsing.songs_by_genre(
            ctx.session,
            ctx.user,
            params.require("genre"),
            count=params.get_int("count", 10) or 0,
            offset=params.get_int("offset", 0) or 0,
            music_folder_id=params.get_int("musicFolderId"),
        )
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None
    return {"songsByGenre": schemas.Songs(song=[mappers.song(s) for s in songs])}


@registry.endpoint("getGenres")
async def get_genres(ctx: SubsonicContext) -> Payload:
    found = await browsing.genres(ctx.session, ctx.user)
    return {
        "genres": schemas.Genres(
            genre=[
                schemas.Genre(value=g.name, song_count=g.songs, album_count=g.albums) for g in found
            ]
        )
    }
