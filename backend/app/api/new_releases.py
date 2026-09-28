"""New releases (Manage Library, admins): recent and upcoming releases of the library's
artists that the library does not have, and the background refresh of their
discographies."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Request

from app.api.deps import AdminCaller, ApiModel, DbSession
from app.api.discography import OwnedAlbumOut, ReleaseGroupOut
from app.services import new_releases
from app.services.discography import DiscographyEntry
from app.services.new_releases import DiscographySync

router = APIRouter(prefix="/manage/new-releases", tags=["new releases"])


def _sync(request: Request) -> DiscographySync:
    return request.app.state.discography_sync


class SyncOut(ApiModel):
    running: bool
    total: int
    done: int
    current: str | None
    errors: int
    started_at: datetime | None
    finished_at: datetime | None


class NewReleaseOut(ReleaseGroupOut):
    artist_id: uuid.UUID
    artist_name: str
    month_unknown: bool  # only the year is known


class CategoryOut(ApiModel):
    key: str
    label: str
    count: int


class ArtistOut(ApiModel):
    id: uuid.UUID
    name: str


class NewReleasesOut(ApiModel):
    enabled: bool  # MusicBrainz lookups allowed (Settings → External services)
    sync: SyncOut
    artists: int
    stale: int  # artists whose discography must be fetched (again)
    upcoming: list[NewReleaseOut]
    recent: list[NewReleaseOut]
    categories: list[CategoryOut]
    unlinked: list[ArtistOut]  # not linked to MusicBrainz


def _release(release: new_releases.NewRelease) -> NewReleaseOut:
    entry: DiscographyEntry = release.entry
    group = entry.group
    return NewReleaseOut(
        artist_id=release.artist_id,
        artist_name=release.artist_name,
        month_unknown=release.month_unknown,
        mbid=group.mbid,
        title=group.title,
        category=entry.category,
        primary_type=group.primary_type,
        secondary_types=group.secondary_types,
        first_release_date=group.first_release_date,
        upcoming=entry.upcoming,
        owned=OwnedAlbumOut(
            album_id=entry.owned.album_id, name=entry.owned.name, cover_art=entry.owned.cover_art
        )
        if entry.owned
        else None,
    )


@router.get("")
async def get_new_releases(
    request: Request, _: AdminCaller, session: DbSession, months: int = 6
) -> NewReleasesOut:
    """From the cache: nothing is fetched here (see POST /sync)."""
    found = await new_releases.new_releases(session, months)
    progress = _sync(request).progress
    return NewReleasesOut(
        enabled=found.enabled,
        sync=SyncOut(**vars(progress)),
        artists=found.artists,
        stale=found.stale,
        upcoming=[_release(r) for r in found.upcoming],
        recent=[_release(r) for r in found.recent],
        categories=[CategoryOut(key=c.key, label=c.label, count=c.total) for c in found.categories],
        unlinked=[ArtistOut(id=a.id, name=a.name) for a in found.unlinked],
    )


@router.post("/sync")
async def sync_discographies(request: Request, _: AdminCaller) -> SyncOut:
    """Starts fetching the old discographies in the background (nothing if it already
    runs); poll GET for the progress."""
    sync = _sync(request)
    sync.start(request.app.state.http)
    return SyncOut(**vars(sync.progress))
