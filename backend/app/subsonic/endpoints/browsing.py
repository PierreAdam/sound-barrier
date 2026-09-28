from app.core.text import IGNORED_ARTICLES, index_letter
from app.services import browsing, music_folders
from app.services.browsing import FolderNotAccessibleError
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import SubsonicError
from app.subsonic.router import SubsonicContext, registry


@registry.endpoint("getMusicFolders")
async def get_music_folders(ctx: SubsonicContext) -> Payload:
    folders = await music_folders.list_for_user(ctx.session, ctx.user)
    return {
        "musicFolders": schemas.MusicFolders(
            music_folder=[schemas.MusicFolder(id=f.id, name=f.name) for f in folders]
        )
    }


@registry.endpoint("getArtists")
async def get_artists(ctx: SubsonicContext) -> Payload:
    try:
        entries = await browsing.list_album_artists(
            ctx.session, ctx.user, ctx.params.get_int("musicFolderId")
        )
    except FolderNotAccessibleError:
        raise SubsonicError.not_found("Music folder") from None
    groups: dict[str, list[schemas.ArtistID3]] = {}
    for entry in entries:
        groups.setdefault(index_letter(entry.artist.sort_name), []).append(mappers.artist(entry))
    # "#" (digits, symbols) comes first, as in other Subsonic servers.
    index = [
        schemas.IndexID3(name=letter, artist=groups[letter])
        for letter in sorted(groups, key=lambda name: (name != "#", name))
    ]
    return {"artists": schemas.ArtistsID3(ignored_articles=" ".join(IGNORED_ARTICLES), index=index)}


@registry.endpoint("getArtist")
async def get_artist(ctx: SubsonicContext) -> Payload:
    artist_id = browsing.parse_id(ctx.params.require("id"))
    found = await browsing.get_artist(ctx.session, ctx.user, artist_id) if artist_id else None
    if found is None:
        raise SubsonicError.not_found("Artist")
    entry, albums = found
    return {
        "artist": schemas.ArtistWithAlbumsID3(
            **mappers.artist(entry).model_dump(), album=[mappers.album(a) for a in albums]
        )
    }


@registry.endpoint("getAlbum")
async def get_album(ctx: SubsonicContext) -> Payload:
    album_id = browsing.parse_id(ctx.params.require("id"))
    found = await browsing.get_album(ctx.session, ctx.user, album_id) if album_id else None
    if found is None:
        raise SubsonicError.not_found("Album")
    entry, songs = found
    return {
        "album": schemas.AlbumWithSongsID3(
            **mappers.album(entry).model_dump(), song=[mappers.song(s) for s in songs]
        )
    }


@registry.endpoint("getSong")
async def get_song(ctx: SubsonicContext) -> Payload:
    song_id = browsing.parse_id(ctx.params.require("id"))
    entry = await browsing.get_song(ctx.session, ctx.user, song_id) if song_id else None
    if entry is None:
        raise SubsonicError.not_found("Song")
    return {"song": mappers.song(entry)}
