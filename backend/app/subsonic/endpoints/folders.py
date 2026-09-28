"""Folder browsing: getIndexes, getMusicDirectory, getAlbumList, search2."""

from app.core.text import IGNORED_ARTICLES, index_letter
from app.services import browsing, folders
from app.services.browsing import FolderNotAccessibleError, InvalidAlbumListError
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import ErrorCode, SubsonicError
from app.subsonic.router import SubsonicContext, registry


@registry.endpoint("getIndexes")
async def get_indexes(ctx: SubsonicContext) -> Payload:
    changed = await folders.last_modified(ctx.session)
    last_modified = int(changed.timestamp() * 1000) if changed else 0
    articles = " ".join(IGNORED_ARTICLES)
    since = ctx.params.get_int("ifModifiedSince")
    if since is not None and last_modified <= since:  # the client's copy is current
        return {"indexes": schemas.Indexes(last_modified=last_modified, ignored_articles=articles)}
    try:
        top, songs = await folders.top_folders(
            ctx.session, ctx.user, ctx.params.get_int("musicFolderId")
        )
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None
    groups: dict[str, list[schemas.Artist]] = {}
    for directory in top:
        groups.setdefault(index_letter(directory.name), []).append(mappers.index_artist(directory))
    index = [
        schemas.Index(name=letter, artist=groups[letter])
        for letter in sorted(groups, key=lambda name: (name != "#", name))
    ]
    return {
        "indexes": schemas.Indexes(
            last_modified=last_modified,
            ignored_articles=articles,
            index=index,
            child=[mappers.song(s) for s in songs],
        )
    }


@registry.endpoint("getMusicDirectory")
async def get_music_directory(ctx: SubsonicContext) -> Payload:
    directory_id = browsing.parse_id(ctx.params.require("id"))
    found = await folders.listing(ctx.session, ctx.user, directory_id) if directory_id else None
    if found is None:
        raise SubsonicError.not_found("Directory")
    return {
        "directory": schemas.Directory(
            id=str(found.directory.id),
            parent=str(found.parent_id) if found.parent_id else None,
            name=found.directory.name,
            child=[mappers.folder(d) for d in found.folders]
            + [mappers.song(s) for s in found.songs],
        )
    }


@registry.endpoint("getAlbumList")
async def get_album_list(ctx: SubsonicContext) -> Payload:
    """getAlbumList2's lists, each album given as its folder."""
    params = ctx.params
    try:
        albums = await browsing.album_list(
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
    entries = await folders.album_folders(ctx.session, albums)
    return {
        "albumList": schemas.AlbumList(
            album=[mappers.folder(e.directory, e.album) for e in entries]
        )
    }


@registry.endpoint("search2")
async def search2(ctx: SubsonicContext) -> Payload:
    params = ctx.params
    query = params.get("query") or ""
    try:
        result = await browsing.search(
            ctx.session,
            ctx.user,
            query,
            artist_count=0,
            album_count=params.get_int("albumCount", 20) or 0,
            album_offset=params.get_int("albumOffset", 0) or 0,
            song_count=params.get_int("songCount", 20) or 0,
            song_offset=params.get_int("songOffset", 0) or 0,
            music_folder_id=params.get_int("musicFolderId"),
        )
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None
    artists = await folders.search_top_folders(
        ctx.session,
        ctx.user,
        query,
        min(params.get_int("artistCount", 20) or 0, browsing.MAX_SEARCH_COUNT),
        params.get_int("artistOffset", 0) or 0,
    )
    albums = await folders.album_folders(ctx.session, result.albums)
    return {
        "searchResult2": schemas.SearchResult2(
            artist=[mappers.index_artist(d) for d in artists],
            album=[mappers.folder(e.directory, e.album) for e in albums],
            song=[mappers.song(s) for s in result.songs],
        )
    }
