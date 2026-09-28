"""An artist's discography from MusicBrainz, compared with the library ("Missing albums"
on the artist page), cached in `artist_info`.

The MusicBrainz artist id is, in order: the one an admin chose (override), the one in the
file tags, or the result of a search by name when it is unambiguous. Release groups are
matched to the library's albums on every request (so a new album shows as owned right
away): by release group id, by release id (resolved once to its release group), then by
title.

Covers of release groups we do not own come from the cover sources (Cover Art Archive,
fanart.tv, Deezer), fetched once and kept in the data folder.
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher
from app.core.text import normalize, title_key
from app.external import ExternalServiceError, musicbrainz
from app.external import covers as sources
from app.external.musicbrainz import ArtistCandidate, ReleaseGroup
from app.models import Album, AppUser, Artist, ArtistInfo
from app.plugins.base import WantedAlbum
from app.services import artist_info, browsing, server_settings

logger = logging.getLogger(__name__)

REFRESH_AFTER = timedelta(days=1)  # new releases (Manage Library) are checked daily
RETRY_AFTER = timedelta(days=1)  # after a failure
RELEASE_LOOKUPS = 10  # release ids resolved per request at most (one second each)
COVER_RETRY_AFTER = timedelta(days=30)  # when no source had a cover
_COVER_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_NO_COVER = ".none"
_cover_fetches = asyncio.Semaphore(4)  # a page asks for many covers at once
_cover_locks: dict[str, asyncio.Lock] = {}


class UnknownMusicBrainzArtistError(Exception):
    pass


@dataclass
class OwnedAlbum:
    album_id: uuid.UUID
    name: str
    cover_art: str | None


@dataclass
class DiscographyEntry:
    group: ReleaseGroup
    category: str  # musicbrainz.category
    upcoming: bool  # first released after today
    owned: OwnedAlbum | None


@dataclass
class Category:
    key: str  # "album+live"
    label: str  # "Album + Live"
    total: int
    missing: int


@dataclass
class Discography:
    enabled: bool  # MusicBrainz lookups allowed in Settings
    artist_mbid: str | None = None
    mbid_source: str | None = None  # "manual", "tags", "search"; None: not linked
    fetched_at: datetime | None = None
    error: str | None = None  # last fetching problem (for admins)
    categories: list[Category] = field(default_factory=list[Category])
    entries: list[DiscographyEntry] = field(default_factory=list[DiscographyEntry])


def _wanted_mbid(row: ArtistInfo, artist: Artist) -> tuple[str | None, str | None]:
    """(MusicBrainz artist id, source) known without searching."""
    if row.mbz_artist_id_override:
        return row.mbz_artist_id_override, "manual"
    if artist.mbz_artist_id:
        return artist.mbz_artist_id, "tags"
    return None, None


async def _search(http: httpx.AsyncClient, name: str) -> str | None:
    """The artist's id if the search is unambiguous: one result with this exact name and
    the best score, and no other result as good."""
    candidates = await musicbrainz.search_artists(http, name)
    best = [c for c in candidates if c.score == 100]
    wanted = normalize(name)
    exact = [c for c in best if normalize(c.name) == wanted]
    return exact[0].mbid if len(exact) == 1 and len(best) == 1 else None


async def _refresh(row: ArtistInfo, artist: Artist, http: httpx.AsyncClient, now: datetime) -> None:
    mbid, _ = _wanted_mbid(row, artist)
    error: str | None = None
    try:
        if mbid is None:
            mbid = await _search(http, artist.name)
        groups = await musicbrainz.release_groups(http, mbid) if mbid else []
    except ExternalServiceError as failure:
        row.discography_error = str(failure)
        row.discography_fetched_at = now
        logger.warning("MusicBrainz, artist %s: %s", artist.name, failure)
        return
    if groups is None:
        error = f"MusicBrainz does not know the artist id {mbid}"
        groups = []
    row.discography_mbid = mbid
    row.discography = [asdict(g) for g in groups]
    row.discography_error = error
    row.discography_fetched_at = now


async def _resolve_releases(
    row: ArtistInfo, albums: Sequence[Album], http: httpx.AsyncClient
) -> None:
    """Finds the release group of albums tagged only with a release id (a few per
    request: MusicBrainz allows one call per second)."""
    todo = [
        a.mbz_album_id
        for a in albums
        if a.mbz_album_id
        and not a.mbz_release_group_id
        and a.mbz_album_id not in row.release_groups
    ][:RELEASE_LOOKUPS]
    if not todo:
        return
    found = dict(row.release_groups)
    for release in todo:
        try:
            found[release] = await musicbrainz.release_group_of(http, release)
        except ExternalServiceError as error:
            logger.warning("MusicBrainz, release %s: %s", release, error)
            break
    row.release_groups = found  # a new dict: JSONB changes are not tracked in place


def rank(group: ReleaseGroup) -> tuple[int, int, str]:
    """Category order: primary types as on MusicBrainz, the plain type first."""
    primary = (group.primary_type or "other").casefold()
    index = musicbrainz.PRIMARY_TYPES.index(primary) if primary in musicbrainz.PRIMARY_TYPES else 99
    return (
        index,
        len(group.secondary_types),
        musicbrainz.category(group.primary_type, group.secondary_types),
    )


def label(group: ReleaseGroup) -> str:
    return " + ".join([group.primary_type or "Other", *sorted(group.secondary_types)])


def _upcoming(first_release_date: str | None, today: date) -> bool:
    if not first_release_date:
        return False
    return first_release_date > today.isoformat()[: len(first_release_date)]


def match(
    groups: list[ReleaseGroup],
    albums: Sequence[Album],
    release_groups: dict[str, str | None],
    today: date,
) -> tuple[list[Category], list[DiscographyEntry]]:
    """The release groups in display order (category, then date) with the library album
    each one is, if any, and the categories with their counts."""
    ordered = sorted(groups, key=lambda g: (rank(g), g.first_release_date or "9999", g.title))
    known = {g.mbid for g in groups}
    by_group: dict[str, OwnedAlbum] = {}
    by_title: dict[str, list[OwnedAlbum]] = {}
    for album in albums:
        owned = OwnedAlbum(
            album.id, album.name, str(album.artwork_id) if album.artwork_id else None
        )
        group = album.mbz_release_group_id or release_groups.get(album.mbz_album_id or "")
        if group and group in known:
            by_group.setdefault(group, owned)
        else:  # no usable id: the title decides
            by_title.setdefault(title_key(album.name), []).append(owned)

    entries: list[DiscographyEntry] = []
    for group in ordered:  # plain albums first: they take the title matches
        owned = by_group.get(group.mbid)
        if owned is None:
            same_title = by_title.get(title_key(group.title))
            owned = same_title.pop(0) if same_title else None
        entries.append(
            DiscographyEntry(
                group=group,
                category=musicbrainz.category(group.primary_type, group.secondary_types),
                upcoming=_upcoming(group.first_release_date, today),
                owned=owned,
            )
        )

    categories: dict[str, Category] = {}
    for entry in entries:
        category = categories.setdefault(
            entry.category, Category(entry.category, label(entry.group), 0, 0)
        )
        category.total += 1
        category.missing += entry.owned is None
    return list(categories.values()), entries


def groups_of(row: ArtistInfo) -> list[ReleaseGroup]:
    return [ReleaseGroup(**g) for g in row.discography]


def is_stale(row: ArtistInfo | None, now: datetime) -> bool:
    """Whether the artist's discography must be fetched again."""
    if row is None:
        return True
    failed = row.discography_error is not None
    return artist_info.stale(row.discography_fetched_at, failed, now, REFRESH_AFTER)


async def ensure_fresh(
    session: AsyncSession,
    artist: Artist,
    albums: Sequence[Album],
    http: httpx.AsyncClient,
    *,
    refresh: bool = False,
) -> ArtistInfo:
    """The artist's cache row, its discography fetched first if it is old (`refresh`:
    whatever its age), and its albums' release groups found. The caller commits."""
    row = await artist_info.info_row(session, artist.id)
    now = datetime.now(UTC)
    wanted, _ = _wanted_mbid(row, artist)
    changed = wanted is not None and wanted != row.discography_mbid
    if refresh or changed or is_stale(row, now):
        await _refresh(row, artist, http, now)
    if row.discography:
        await _resolve_releases(row, albums, http)
    await session.flush()
    return row


async def get(
    session: AsyncSession,
    user: AppUser,
    artist_id: uuid.UUID,
    *,
    http: httpx.AsyncClient,
    refresh: bool = False,
) -> Discography | None:
    """The artist's discography, fetched first if needed (`refresh`: now, whatever the
    cache says). None for an unknown artist. The caller commits."""
    found = await browsing.get_artist(session, user, artist_id)
    if found is None:
        return None
    artist, albums = found[0].artist, [entry.album for entry in found[1]]
    settings = await server_settings.get_external_services(session)
    if not settings.musicbrainz:
        return Discography(enabled=False)

    row = await ensure_fresh(session, artist, albums, http, refresh=refresh)
    _, source = _wanted_mbid(row, artist)
    if source is None and row.discography_mbid:
        source = "search"
    today = datetime.now(UTC).date()
    categories, entries = match(groups_of(row), albums, row.release_groups, today)
    return Discography(
        enabled=True,
        artist_mbid=row.discography_mbid,
        mbid_source=source if row.discography_mbid else None,
        fetched_at=row.discography_fetched_at,
        error=row.discography_error,
        categories=categories,
        entries=entries,
    )


async def wanted(session: AsyncSession, artist_id: uuid.UUID, group: str) -> WantedAlbum | None:
    """One release group of the artist's discography, as plugins get it."""
    artist = await session.get(Artist, artist_id)
    row = await session.get(ArtistInfo, artist_id)
    if artist is None or row is None:
        return None
    entry = next((g for g in groups_of(row) if g.mbid == group), None)
    if entry is None:
        return None
    return WantedAlbum(
        artist=artist.name,
        title=entry.title,
        year=(entry.first_release_date or "")[:4] or None,
        release_group_mbid=entry.mbid,
        artist_mbid=row.discography_mbid,
    )


async def candidates(
    session: AsyncSession, artist_id: uuid.UUID, http: httpx.AsyncClient, query: str | None
) -> list[ArtistCandidate] | None:
    """MusicBrainz artists that may be this one (search by name, or `query`)."""
    artist = await session.get(Artist, artist_id)
    if artist is None or artist.missing_since is not None:
        return None
    return await musicbrainz.search_artists(http, (query or "").strip() or artist.name)


async def link(
    session: AsyncSession, artist_id: uuid.UUID, mbid: str | None, http: httpx.AsyncClient
) -> bool:
    """Makes `mbid` the artist's MusicBrainz id (None: back to the tags or the search).
    False for an unknown artist; UnknownMusicBrainzArtistError if MusicBrainz does not
    know this id. The caller commits."""
    artist = await session.get(Artist, artist_id)
    if artist is None or artist.missing_since is not None:
        return False
    if mbid is not None and await musicbrainz.lookup_artist(http, mbid) is None:
        raise UnknownMusicBrainzArtistError(mbid)
    row = await artist_info.info_row(session, artist_id)
    row.mbz_artist_id_override = mbid
    row.discography_fetched_at = None  # fetched again for the new id
    await session.flush()
    return True


# --- covers ---------------------------------------------------------------------------


@dataclass
class _CachedCover:
    path: Path | None  # None: no source had a cover (recently)
    content_type: str = ""


def _cached_cover(covers_dir: Path, group: str) -> _CachedCover | None:
    """What is on disk for this release group; None: the cover must be looked for."""
    for content_type, suffix in _COVER_TYPES.items():
        path = covers_dir / f"{group}{suffix}"
        if path.is_file():
            return _CachedCover(path, content_type)
    marker = covers_dir / f"{group}{_NO_COVER}"
    if marker.is_file():
        age = datetime.now(UTC) - datetime.fromtimestamp(marker.stat().st_mtime, UTC)
        if age < COVER_RETRY_AFTER:
            return _CachedCover(None)
    return None


def _store_cover(covers_dir: Path, group: str, image: tuple[bytes, str] | None) -> _CachedCover:
    """Writes the cover, or a marker saying that there is none."""
    covers_dir.mkdir(parents=True, exist_ok=True)
    suffix = _COVER_TYPES.get(image[1]) if image else None
    path = covers_dir / f"{group}{suffix or _NO_COVER}"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(image[0] if image and suffix else b"")
    temporary.replace(path)
    return _CachedCover(path, image[1]) if image and suffix else _CachedCover(None)


async def _fetch_cover(
    http: httpx.AsyncClient,
    artist: str,
    title: str,
    context: sources.CoverContext,
    covers_dir: Path,
) -> _CachedCover | None:
    """Finds and stores the cover (None: a source failed, tried again next time)."""
    group = context.release_group_id or ""
    lock = _cover_locks.setdefault(group, asyncio.Lock())
    try:
        async with lock, _cover_fetches:
            cached = await asyncio.to_thread(_cached_cover, covers_dir, group)
            if cached is not None:  # found by another request meanwhile
                return cached
            found = await sources.find_cover(http, artist, title, context)
            image = await sources.download(http, found.thumbnail_url) if found else None
            return await asyncio.to_thread(_store_cover, covers_dir, group, image)
    except ExternalServiceError as error:
        logger.warning("Cover of release group %s: %s", group, error)
        return None
    finally:
        _cover_locks.pop(group, None)


async def cover(
    session: AsyncSession,
    artist_id: uuid.UUID,
    group: str,
    *,
    http: httpx.AsyncClient,
    cipher: PasswordCipher,
    covers_dir: Path,
) -> tuple[Path, str] | None:
    """(file, content type) of a release group's cover, found and downloaded the first
    time. Only for release groups of this artist's discography."""
    row = await session.get(ArtistInfo, artist_id)
    entry: dict[str, Any] | None = next(
        (g for g in (row.discography if row else []) if g.get("mbid") == group), None
    )
    if entry is None:
        return None
    cached = await asyncio.to_thread(_cached_cover, covers_dir, group)
    if cached is None:
        artist = await session.get(Artist, artist_id)
        settings = await server_settings.get_external_services(session)
        context = sources.CoverContext(
            release_group_id=group, keys=artist_info.api_keys(settings, cipher)
        )
        title = str(entry.get("title") or "")
        cached = await _fetch_cover(http, artist.name if artist else "", title, context, covers_dir)
    if cached is None or cached.path is None:
        return None
    return cached.path, cached.content_type
