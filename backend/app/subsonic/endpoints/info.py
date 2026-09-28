"""Artist information from external services: getArtistInfo2, getTopSongs (Last.fm)."""

from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings
from app.core.text import normalize
from app.models import Artist
from app.services import artist_info, browsing
from app.services.artist_info import ArtistDetails
from app.subsonic import mappers, schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import SubsonicError
from app.subsonic.router import SubsonicContext, registry

MAX_COUNT = 100


async def _details(ctx: SubsonicContext, artist: Artist, top_songs: int) -> ArtistDetails:
    state = ctx.request.app.state
    settings: Settings = state.settings
    details = await artist_info.get(
        ctx.session,
        ctx.user,
        artist.id,
        http=state.http,
        cipher=state.cipher,
        pictures_dir=Path(settings.data_dir) / "artist-pictures",
        top_songs=top_songs,
    )
    if details is None:
        raise SubsonicError.not_found("Artist")
    return details


@registry.endpoint("getArtistInfo2")
async def get_artist_info2(ctx: SubsonicContext) -> Payload:
    artist_id = browsing.parse_id(ctx.params.require("id"))
    artist = await ctx.session.get(Artist, artist_id) if artist_id else None
    if artist is None:
        raise SubsonicError.not_found("Artist")
    count = min(max(ctx.params.get_int("count", 20) or 0, 0), MAX_COUNT)
    details = await _details(ctx, artist, top_songs=0)
    similar: list[schemas.ArtistID3] = []
    for entry in details.similar:
        if len(similar) >= count or entry.artist_id is None:
            continue  # only artists of the library (includeNotPresent is not supported)
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


@registry.endpoint("getTopSongs")
async def get_top_songs(ctx: SubsonicContext) -> Payload:
    name = ctx.params.require("artist")
    count = min(max(ctx.params.get_int("count", 50) or 0, 0), MAX_COUNT)
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
