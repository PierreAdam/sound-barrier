"""Album notes (Last.fm's album wiki) for getAlbumInfo, cached in `album_info` like the
artist information (refreshed after 30 days, retried a day after a failure)."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher
from app.external import ExternalServiceError
from app.external.lastfm import LastFm
from app.models import Album, AlbumInfo
from app.services import artist_info, server_settings

logger = logging.getLogger(__name__)


@dataclass
class AlbumDetails:
    album: Album
    notes: str | None
    lastfm_url: str | None


async def get(
    session: AsyncSession, album_id: uuid.UUID, *, http: httpx.AsyncClient, cipher: PasswordCipher
) -> AlbumDetails | None:
    """The album's notes, fetched first if needed; None for an unknown album. The caller
    commits."""
    album = await session.get(Album, album_id)
    if album is None or album.missing_since is not None:
        return None
    settings = await server_settings.get_external_services(session)
    key = artist_info.lastfm_key(settings, cipher)
    if key is None:  # no Last.fm: only what the library knows
        return AlbumDetails(album, None, None)
    await session.execute(
        insert(AlbumInfo)
        .values(album_id=album_id)
        .on_conflict_do_nothing(index_elements=[AlbumInfo.album_id])
    )
    row = await session.get(AlbumInfo, album_id)
    assert row is not None
    now = datetime.now(UTC)
    if artist_info.stale(row.fetched_at, row.error is not None, now):
        try:
            found = await LastFm(http, key).album(
                album.display_artist, album.name, album.mbz_album_id
            )
        except ExternalServiceError as error:
            row.error = str(error)
            logger.warning("Last.fm, album %s: %s", album.name, error)
        else:
            row.notes = (found.notes or found.summary or None) if found else None
            row.lastfm_url = found.url if found else None
            row.error = None
        row.fetched_at = now
        await session.flush()
    return AlbumDetails(album, row.notes, row.lastfm_url)
