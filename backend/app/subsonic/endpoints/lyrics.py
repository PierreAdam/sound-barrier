"""Song lyrics: getLyrics (by artist and title) and OpenSubsonic's getLyricsBySongId
(synced lines when known), from services/lyrics.py."""

from pathlib import Path

from sqlalchemy import func, select, true

from app.core.config import Settings
from app.core.text import normalize
from app.models import Song
from app.services import browsing, lyrics
from app.subsonic import schemas
from app.subsonic.envelope import Payload
from app.subsonic.errors import SubsonicError
from app.subsonic.router import SubsonicContext, registry


async def _lyrics(ctx: SubsonicContext, song: Song) -> lyrics.SongLyrics | None:
    """None too when LRCLIB is unreachable (apps simply show no lyrics)."""
    settings: Settings = ctx.request.app.state.settings
    try:
        return await lyrics.get(
            ctx.session, song.id, http=ctx.request.app.state.http, data_dir=Path(settings.data_dir)
        )
    except lyrics.LyricsUnavailableError:
        return None


@registry.endpoint("getLyricsBySongId")
async def get_lyrics_by_song_id(ctx: SubsonicContext) -> Payload:
    song_id = browsing.parse_id(ctx.params.require("id"))
    entry = await browsing.get_song(ctx.session, ctx.user, song_id) if song_id else None
    if entry is None:
        raise SubsonicError.not_found("Song")
    found = await _lyrics(ctx, entry.song)
    structured = (
        [
            schemas.StructuredLyrics(
                display_artist=entry.song.display_artist,
                display_title=entry.song.title,
                synced=found.synced,
                line=[
                    schemas.LyricsLine(
                        start=line.start_ms if found.synced else None, value=line.text
                    )
                    for line in found.lines
                ],
            )
        ]
        if found and found.lines
        else []
    )
    return {"lyricsList": schemas.LyricsList(structured_lyrics=structured)}


@registry.endpoint("getLyrics")
async def get_lyrics(ctx: SubsonicContext) -> Payload:
    """Plain text of the first song of the library with this artist and title."""
    artist = ctx.params.get("artist") or ""
    title = ctx.params.get("title") or ""
    song_id = await ctx.session.scalar(
        select(Song.id)
        .where(Song.title_search == normalize(title), Song.missing_since.is_(None))
        .where(func.lower(Song.display_artist) == artist.lower() if artist else true())
        .limit(1)
    )
    entry = await browsing.get_song(ctx.session, ctx.user, song_id) if song_id else None
    found = await _lyrics(ctx, entry.song) if entry else None
    if entry is None or found is None:
        return {"lyrics": schemas.Lyrics(artist=artist or None, title=title or None)}
    return {
        "lyrics": schemas.Lyrics(
            artist=entry.song.display_artist,
            title=entry.song.title,
            value="\n".join(line.text for line in found.lines),
        )
    }
