"""Artist information from external services: biography, similar artists and top songs
(Last.fm) and a picture (the provider chosen in Settings), cached in `artist_info`.

Fetched when an artist page asks for it and the cache is missing or old; failures are
retried later. Top tracks and similar artists are matched to the library, so the web UI
only offers what can be played.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from cryptography.fernet import InvalidToken
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher
from app.core.text import normalize, title_key
from app.external import ExternalServiceError
from app.external.lastfm import LastFm
from app.external.pictures import PROVIDERS
from app.models import Album, AppUser, Artist, ArtistInfo
from app.services import browsing, server_settings
from app.services.browsing import SongEntry

logger = logging.getLogger(__name__)

REFRESH_AFTER = timedelta(days=30)
RETRY_AFTER = timedelta(days=1)  # after a failure
TOP_TRACKS_FETCHED = 50


@dataclass
class SimilarArtist:
    name: str
    artist_id: uuid.UUID | None  # in the library


@dataclass
class PictureCredit:
    source: str  # provider label, e.g. "Deezer"
    page_url: str | None
    version: str  # changes when the picture does (cache busting)


@dataclass
class ArtistDetails:
    lastfm_configured: bool
    lastfm_url: str | None = None
    summary: str | None = None
    biography: str | None = None
    similar: list[SimilarArtist] = field(default_factory=list[SimilarArtist])
    top_songs: list[SongEntry] = field(default_factory=list[SongEntry])
    picture: PictureCredit | None = None
    error: str | None = None  # last fetching problem (for admins)


def _decrypt(value: str | None, cipher: PasswordCipher, label: str) -> str | None:
    if not value:
        return None
    try:
        return cipher.decrypt(value.encode())
    except InvalidToken:  # the server's secret key changed
        logger.warning("The %s API key cannot be decrypted: enter it again in Settings", label)
        return None


def lastfm_key(settings: server_settings.ExternalServices, cipher: PasswordCipher) -> str | None:
    return _decrypt(settings.lastfm_key_enc, cipher, "Last.fm")


def api_keys(settings: server_settings.ExternalServices, cipher: PasswordCipher) -> dict[str, str]:
    """The keys of the picture / cover sources, by name (see their `needs_key`)."""
    keys: dict[str, str] = {}
    fanart_key = _decrypt(settings.fanart_key_enc, cipher, "fanart.tv")
    if fanart_key:
        keys["fanart"] = fanart_key
    return keys


def stale(
    fetched_at: datetime | None,
    failed: bool,
    now: datetime,
    refresh_after: timedelta = REFRESH_AFTER,
) -> bool:
    """Whether cached data must be fetched again (sooner after a failure)."""
    if fetched_at is None:
        return True
    return now - fetched_at > (RETRY_AFTER if failed else refresh_after)


async def info_row(session: AsyncSession, artist_id: uuid.UUID) -> ArtistInfo:
    """The artist's cache row, created if needed. The artist page asks for its
    information and its discography at the same time: both may create it."""
    await session.execute(
        insert(ArtistInfo)
        .values(artist_id=artist_id, similar=[], top_tracks=[])
        .on_conflict_do_nothing(index_elements=[ArtistInfo.artist_id])
    )
    row = await session.get(ArtistInfo, artist_id)
    assert row is not None
    return row


def picture_path(pictures_dir: Path, artist_id: uuid.UUID) -> Path:
    return pictures_dir / str(artist_id)


async def _refresh_lastfm(
    row: ArtistInfo, artist: Artist, http: httpx.AsyncClient, key: str, now: datetime
) -> None:
    client = LastFm(http, key)
    try:
        found = await client.artist(artist.name, artist.mbz_artist_id)
        tracks = await client.top_tracks(artist.name, artist.mbz_artist_id, TOP_TRACKS_FETCHED)
    except ExternalServiceError as error:
        row.info_error = str(error)
        row.info_fetched_at = now
        logger.warning("Last.fm, artist %s: %s", artist.name, error)
        return
    row.lastfm_url = found.url if found else None
    row.summary = (found.summary or None) if found else None
    row.biography = (found.biography or None) if found else None
    row.similar = [{"name": s.name, "mbid": s.mbid} for s in found.similar] if found else []
    row.top_tracks = [{"title": t.title, "mbid": t.mbid, "playcount": t.playcount} for t in tracks]
    row.info_error = None
    row.info_fetched_at = now


async def _refresh_picture(
    row: ArtistInfo,
    artist: Artist,
    http: httpx.AsyncClient,
    source: str,
    pictures_dir: Path,
    now: datetime,
    keys: dict[str, str],
    album_titles: list[str],
) -> None:
    provider = PROVIDERS[source]
    try:
        picture = await provider.find(
            http, artist.name, artist.mbz_artist_id, keys, album_titles=album_titles
        )
    except ExternalServiceError as error:
        row.picture_error = str(error)
        row.picture_fetched_at = now
        logger.warning("%s picture, artist %s: %s", provider.label, artist.name, error)
        return
    path = picture_path(pictures_dir, artist.id)
    if picture is None:
        row.picture_source = row.picture_page_url = row.picture_content_type = None
        await asyncio.to_thread(path.unlink, missing_ok=True)
    else:

        def write() -> None:
            pictures_dir.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(picture.data)
            temporary.replace(path)

        await asyncio.to_thread(write)
        row.picture_source = provider.id
        row.picture_page_url = picture.page_url
        row.picture_content_type = picture.content_type
    row.picture_error = None
    row.picture_fetched_at = now


async def _similar_in_library(
    session: AsyncSession, similar: list[dict[str, str | None]]
) -> list[SimilarArtist]:
    names = [normalize(str(s["name"])) for s in similar]
    mbids = [str(s["mbid"]) for s in similar if s.get("mbid")]
    rows = (
        await session.execute(
            select(Artist.id, Artist.name_search, Artist.mbz_artist_id).where(
                Artist.missing_since.is_(None),
                Artist.album_count > 0,
                or_(Artist.name_search.in_(names), Artist.mbz_artist_id.in_(mbids)),
            )
        )
    ).all()
    by_name = {name: artist_id for artist_id, name, _ in rows}
    by_mbid = {mbid: artist_id for artist_id, _, mbid in rows if mbid}
    return [
        SimilarArtist(
            str(s["name"]),
            by_mbid.get(str(s.get("mbid"))) or by_name.get(normalize(str(s["name"]))),
        )
        for s in similar
    ]


def _match_top_songs(
    tracks: list[dict[str, str | int | None]], songs: list[SongEntry], limit: int
) -> list[SongEntry]:
    by_recording = {s.song.mbz_recording_id: s for s in songs if s.song.mbz_recording_id}
    by_title: dict[str, SongEntry] = {}
    for song in songs:  # the first one wins (oldest album)
        by_title.setdefault(title_key(song.song.title), song)
    result: list[SongEntry] = []
    used: set[uuid.UUID] = set()
    for track in tracks:
        mbid = track.get("mbid")
        found = by_recording.get(str(mbid)) if mbid else None
        found = found or by_title.get(title_key(str(track["title"])))
        if found is not None and found.song.id not in used:
            used.add(found.song.id)
            result.append(found)
            if len(result) >= limit:
                break
    return result


async def get(
    session: AsyncSession,
    user: AppUser,
    artist_id: uuid.UUID,
    *,
    http: httpx.AsyncClient,
    cipher: PasswordCipher,
    pictures_dir: Path,
    top_songs: int = 10,
    refresh: bool = False,
) -> ArtistDetails | None:
    """The artist's details, fetched first if needed (`refresh`: now, whatever the cache
    says). None for an unknown artist. The caller commits."""
    artist = await session.get(Artist, artist_id)
    if artist is None or artist.missing_since is not None:
        return None
    settings = await server_settings.get_external_services(session)
    key = lastfm_key(settings, cipher)
    source = settings.picture_source if settings.picture_source in PROVIDERS else None

    row = await info_row(session, artist_id)
    now = datetime.now(UTC)
    if key and (refresh or stale(row.info_fetched_at, row.info_error is not None, now)):
        await _refresh_lastfm(row, artist, http, key, now)
    picture_stale = stale(row.picture_fetched_at, row.picture_error is not None, now)
    if source and (refresh or picture_stale or row.picture_source not in (None, source)):
        keys = api_keys(settings, cipher)
        # Its albums tell same-name artists apart at the source.
        album_titles = list(
            await session.scalars(
                select(Album.name).where(
                    Album.artist_id == artist_id, Album.missing_since.is_(None)
                )
            )
        )
        await _refresh_picture(row, artist, http, source, pictures_dir, now, keys, album_titles)
    await session.flush()

    details = ArtistDetails(lastfm_configured=key is not None)
    if key:
        details.lastfm_url = row.lastfm_url
        details.summary = row.summary
        details.biography = row.biography
        details.similar = await _similar_in_library(session, row.similar)
        songs = await browsing.artist_songs(session, user, artist_id)
        details.top_songs = _match_top_songs(row.top_tracks, songs, top_songs)
    if source and row.picture_source == source and row.picture_fetched_at is not None:
        details.picture = PictureCredit(
            PROVIDERS[source].label,
            row.picture_page_url,
            str(int(row.picture_fetched_at.timestamp())),
        )
    details.error = row.info_error or row.picture_error
    return details


async def picture(session: AsyncSession, artist_id: uuid.UUID) -> tuple[str, str] | None:
    """(picture version, content type) if the artist has a picture from the current
    source (see media.cover_image)."""
    row = await session.get(ArtistInfo, artist_id)
    if row is None or row.picture_source is None or row.picture_fetched_at is None:
        return None
    settings = await server_settings.get_external_services(session)
    if settings.picture_source != row.picture_source:
        return None
    return str(int(row.picture_fetched_at.timestamp())), row.picture_content_type or "image/jpeg"
