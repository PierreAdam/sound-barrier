"""New releases (Manage Library): the recent and upcoming release groups of every album
artist of the library that the library does not have.

The discographies come from the per-artist cache of `discography.py`. A background job
(`DiscographySync`) refreshes the old ones (MusicBrainz: one request per second, so a few
minutes for a library of a hundred artists); it runs on the server and keeps going when
the admin leaves the page. The page shows its progress, then the releases.
"""

import asyncio
import calendar
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Database
from app.core.text import normalize
from app.external.musicbrainz import ReleaseGroup
from app.models import Album, Artist, ArtistInfo
from app.services import discography, server_settings
from app.services.discography import Category, DiscographyEntry

logger = logging.getLogger(__name__)

MIN_MONTHS, MAX_MONTHS = 1, 12
VARIOUS_ARTISTS_MBID = "89ad4ac3-39f7-470e-963a-56509c546377"  # MusicBrainz' special artist
_VARIOUS = {"various artists", "various", "va"}


def months_before(today: date, months: int) -> date:
    """The same day `months` earlier (the month's last day when it is shorter)."""
    month_index = today.year * 12 + today.month - 1 - months
    year, month = divmod(month_index, 12)
    last_day = calendar.monthrange(year, month + 1)[1]
    return date(year, month + 1, min(today.day, last_day))


def in_period(first_release_date: str | None, start: date, today: date) -> tuple[bool, bool]:
    """(released in [start, today], only the year is known). The date is compared at its
    own precision: "2026-05" is in the period if May 2026 is, "2026" if 2026 is."""
    if not first_release_date:
        return False, False
    if len(first_release_date) == 4:
        return start.year <= int(first_release_date) <= today.year, True
    size = len(first_release_date)
    return start.isoformat()[:size] <= first_release_date <= today.isoformat()[:size], False


def _is_various(artist: Artist) -> bool:
    return artist.mbz_artist_id == VARIOUS_ARTISTS_MBID or normalize(artist.name) in _VARIOUS


@dataclass
class NewRelease:
    artist_id: uuid.UUID
    artist_name: str
    entry: DiscographyEntry
    month_unknown: bool = False  # only the year is known


@dataclass
class UnlinkedArtist:
    id: uuid.UUID
    name: str


@dataclass
class NewReleases:
    enabled: bool  # MusicBrainz lookups allowed in Settings
    artists: int = 0  # album artists considered
    stale: int = 0  # of them whose discography must be fetched (again)
    upcoming: list[NewRelease] = field(default_factory=list[NewRelease])  # soonest first
    recent: list[NewRelease] = field(default_factory=list[NewRelease])  # newest first
    categories: list[Category] = field(default_factory=list[Category])  # of those releases
    unlinked: list[UnlinkedArtist] = field(default_factory=list[UnlinkedArtist])


async def _album_artists(session: AsyncSession) -> list[Artist]:
    artists = (
        await session.scalars(
            select(Artist)
            .where(
                Artist.missing_since.is_(None),
                Artist.id.in_(select(Album.artist_id).where(Album.missing_since.is_(None))),
            )
            .order_by(Artist.sort_name)
        )
    ).all()
    return [a for a in artists if not _is_various(a)]


async def stale_artists(session: AsyncSession) -> list[uuid.UUID]:
    """Album artists whose discography is missing or older than a day."""
    artists = await _album_artists(session)
    rows = {
        row.artist_id: row
        for row in await session.scalars(
            select(ArtistInfo).where(ArtistInfo.artist_id.in_([a.id for a in artists]))
        )
    }
    now = datetime.now(UTC)
    return [a.id for a in artists if discography.is_stale(rows.get(a.id), now)]


async def new_releases(session: AsyncSession, months: int) -> NewReleases:
    """The releases of the last `months` months and the upcoming ones that the library
    does not have, from the cache (nothing is fetched here)."""
    settings = await server_settings.get_external_services(session)
    if not settings.musicbrainz:
        return NewReleases(enabled=False)
    months = min(max(months, MIN_MONTHS), MAX_MONTHS)
    artists = await _album_artists(session)
    ids = [a.id for a in artists]
    rows = {
        row.artist_id: row
        for row in await session.scalars(select(ArtistInfo).where(ArtistInfo.artist_id.in_(ids)))
    }
    albums: dict[uuid.UUID, list[Album]] = defaultdict(list)
    for album in await session.scalars(
        select(Album).where(Album.artist_id.in_(ids), Album.missing_since.is_(None))
    ):
        albums[album.artist_id].append(album)

    now = datetime.now(UTC)
    today = now.date()
    start = months_before(today, months)
    result = NewReleases(enabled=True, artists=len(artists))
    categories: dict[str, tuple[Category, ReleaseGroup]] = {}
    for artist in artists:
        row = rows.get(artist.id)
        if discography.is_stale(row, now):
            result.stale += 1
        if row is None or row.discography_fetched_at is None:
            continue
        if not row.discography_mbid:
            result.unlinked.append(UnlinkedArtist(artist.id, artist.name))
            continue
        groups = discography.groups_of(row)
        _, entries = discography.match(groups, albums[artist.id], row.release_groups, today)
        for entry in entries:
            if entry.owned is not None:
                continue
            if entry.upcoming:
                release = NewRelease(artist.id, artist.name, entry)
                result.upcoming.append(release)
            else:
                recent, month_unknown = in_period(entry.group.first_release_date, start, today)
                if not recent:
                    continue
                release = NewRelease(artist.id, artist.name, entry, month_unknown)
                result.recent.append(release)
            category, _ = categories.setdefault(
                entry.category,
                (Category(entry.category, discography.label(entry.group), 0, 0), entry.group),
            )
            category.total += 1
            category.missing += 1
    result.upcoming.sort(key=lambda r: (r.entry.group.first_release_date or "", r.artist_name))
    result.recent.sort(key=lambda r: r.entry.group.first_release_date or "", reverse=True)
    ranked = sorted(categories.values(), key=lambda found: discography.rank(found[1]))
    result.categories = [category for category, _ in ranked]
    return result


# --- the background job ---------------------------------------------------------------


@dataclass
class SyncProgress:
    running: bool = False
    total: int = 0  # artists to fetch in this run
    done: int = 0
    current: str | None = None  # the artist being fetched
    errors: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DiscographySync:
    """Refreshes the old discographies of all album artists, one artist after another,
    in the background (not tied to a request: leaving the page does not stop it)."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._task: asyncio.Task[None] | None = None
        self.progress = SyncProgress()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, http: httpx.AsyncClient) -> bool:
        """Starts a run unless one is going on."""
        if self.running:
            return False
        self.progress = SyncProgress(running=True, started_at=datetime.now(UTC))
        self._task = asyncio.create_task(self._run(http), name="discography-sync")
        return True

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def wait(self) -> None:
        """Until the current run is over (tests)."""
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, http: httpx.AsyncClient) -> None:
        progress = self.progress
        try:
            async with self._db.session() as session:
                settings = await server_settings.get_external_services(session)
                todo = await stale_artists(session) if settings.musicbrainz else []
            progress.total = len(todo)
            for artist_id in todo:
                await self._refresh(artist_id, http, progress)
                progress.done += 1
            logger.info("Discographies refreshed: %d artists", progress.done)
        finally:
            progress.running = False
            progress.current = None
            progress.finished_at = datetime.now(UTC)

    async def _refresh(
        self, artist_id: uuid.UUID, http: httpx.AsyncClient, progress: SyncProgress
    ) -> None:
        try:
            async with self._db.session() as session:
                artist = await session.get(Artist, artist_id)
                if artist is None or artist.missing_since is not None:
                    return
                progress.current = artist.name
                albums = (
                    await session.scalars(
                        select(Album).where(
                            Album.artist_id == artist_id, Album.missing_since.is_(None)
                        )
                    )
                ).all()
                row = await discography.ensure_fresh(session, artist, albums, http)
                if row.discography_error:
                    progress.errors += 1
                await session.commit()
        except asyncio.CancelledError:
            raise
        except Exception:
            progress.errors += 1
            logger.exception("Discography of artist %s", artist_id)
