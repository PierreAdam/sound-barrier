"""Is an album already in the library? Checked on Sound-Barrier's own tables, which know
every album (beets' database only knows what beets imported)."""

from collections import Counter

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.library_manager.tagger import Candidate, ItemInfo
from app.models import Album


def _most_common(values: list[str | None]) -> str | None:
    counted = Counter(v for v in values if v)
    return counted.most_common(1)[0][0] if counted else None


def identity(items: list[ItemInfo], candidate: Candidate | None) -> tuple[str | None, str | None]:
    """(album artist, album) the import will have."""
    if candidate is not None:
        return candidate.artist, candidate.album
    artist = _most_common([i.album_artist for i in items]) or _most_common(
        [i.artist for i in items]
    )
    return artist, _most_common([i.album for i in items])


async def find_existing(
    session: AsyncSession, items: list[ItemInfo], candidate: Candidate | None
) -> str | None:
    """ "Artist - Album" of the library album this import would duplicate, if any: same
    MusicBrainz release, or same album artist and name (ignoring case)."""
    artist, album = identity(items, candidate)
    conditions: list[ColumnElement[bool]] = []
    if candidate is not None and candidate.id:
        conditions.append(Album.mbz_album_id == candidate.id)
    if artist and album:
        conditions.append(
            and_(
                func.lower(Album.display_artist) == artist.lower(),
                func.lower(Album.name) == album.lower(),
            )
        )
    if not conditions:
        return None
    found = await session.scalar(
        select(Album).where(Album.song_count > 0, or_(*conditions)).limit(1)
    )
    return f"{found.display_artist} - {found.name}" if found else None
