"""The artist's discography from MusicBrainz ("Missing albums" on the artist page) and
the link between an artist and MusicBrainz (admins)."""

import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse

from app.api.deps import AdminCaller, ApiModel, CurrentCaller, DbSession, cipher
from app.api.plugins import LinkOut, link_out
from app.core.config import Settings
from app.external import ExternalServiceError, musicbrainz
from app.services import discography, plugins

router = APIRouter(tags=["discography"])


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def _covers_dir(request: Request) -> Path:
    settings: Settings = request.app.state.settings
    return settings.data_dir / "discography-covers"


class OwnedAlbumOut(ApiModel):
    album_id: uuid.UUID
    name: str
    cover_art: str | None  # for getCoverArt


class ReleaseGroupOut(ApiModel):
    mbid: str
    title: str
    category: str  # e.g. "album", "album+live"
    primary_type: str | None
    secondary_types: list[str]
    first_release_date: str | None
    upcoming: bool
    owned: OwnedAlbumOut | None


class CategoryOut(ApiModel):
    key: str
    label: str  # "Album + Live"
    total: int
    missing: int


class DiscographyOut(ApiModel):
    enabled: bool  # MusicBrainz lookups allowed (Settings → External services)
    artist_mbid: str | None
    mbid_source: str | None  # "manual", "tags", "search"; None: not linked to MusicBrainz
    fetched_at: datetime | None
    error: str | None  # admins only
    categories: list[CategoryOut]  # in display order
    release_groups: list[ReleaseGroupOut]  # by category, then date


class CandidateOut(ApiModel):
    mbid: str
    name: str
    disambiguation: str | None
    country: str | None
    type: str | None
    begin: str | None
    end: str | None
    score: int


class LinkIn(ApiModel):
    # A MusicBrainz artist id or its musicbrainz.org URL; None: back to the tags / search.
    mbid: str | None


def _out(found: discography.Discography, is_admin: bool) -> DiscographyOut:
    return DiscographyOut(
        enabled=found.enabled,
        artist_mbid=found.artist_mbid,
        mbid_source=found.mbid_source,
        fetched_at=found.fetched_at,
        error=found.error if is_admin else None,
        categories=[
            CategoryOut(key=c.key, label=c.label, total=c.total, missing=c.missing)
            for c in found.categories
        ],
        release_groups=[
            ReleaseGroupOut(
                mbid=e.group.mbid,
                title=e.group.title,
                category=e.category,
                primary_type=e.group.primary_type,
                secondary_types=e.group.secondary_types,
                first_release_date=e.group.first_release_date,
                upcoming=e.upcoming,
                owned=OwnedAlbumOut(
                    album_id=e.owned.album_id, name=e.owned.name, cover_art=e.owned.cover_art
                )
                if e.owned
                else None,
            )
            for e in found.entries
        ],
    )


async def _discography(
    request: Request, caller: CurrentCaller, session: DbSession, artist_id: uuid.UUID, refresh: bool
) -> DiscographyOut:
    found = await discography.get(
        session, caller.user, artist_id, http=_http(request), refresh=refresh
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown artist")
    await session.commit()
    return _out(found, caller.user.is_admin)


@router.get("/artists/{artist_id}/discography")
async def get_discography(
    artist_id: uuid.UUID, request: Request, caller: CurrentCaller, session: DbSession
) -> DiscographyOut:
    """The artist's release groups on MusicBrainz, with the library album each one is."""
    return await _discography(request, caller, session, artist_id, refresh=False)


@router.post("/artists/{artist_id}/discography/refresh")
async def refresh_discography(
    artist_id: uuid.UUID, request: Request, caller: AdminCaller, session: DbSession
) -> DiscographyOut:
    """Fetches the discography again now (admins)."""
    return await _discography(request, caller, session, artist_id, refresh=True)


@router.get("/artists/{artist_id}/musicbrainz/candidates")
async def musicbrainz_candidates(
    artist_id: uuid.UUID,
    request: Request,
    _: AdminCaller,
    session: DbSession,
    q: str | None = None,
) -> list[CandidateOut]:
    """MusicBrainz artists that may be this one (searched by its name, or `q`)."""
    try:
        found = await discography.candidates(session, artist_id, _http(request), q)
    except ExternalServiceError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown artist")
    return [
        CandidateOut(
            mbid=c.mbid,
            name=c.name,
            disambiguation=c.disambiguation,
            country=c.country,
            type=c.type,
            begin=c.begin,
            end=c.end,
            score=c.score,
        )
        for c in found
    ]


@router.put("/artists/{artist_id}/musicbrainz")
async def link_musicbrainz(
    artist_id: uuid.UUID, body: LinkIn, request: Request, caller: AdminCaller, session: DbSession
) -> DiscographyOut:
    """Links the artist to a MusicBrainz artist (admins), then fetches its discography."""
    mbid = None
    if body.mbid is not None and body.mbid.strip():
        mbid = musicbrainz.parse_mbid(body.mbid)
        if mbid is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a MusicBrainz artist id")
    try:
        linked = await discography.link(session, artist_id, mbid, _http(request))
    except discography.UnknownMusicBrainzArtistError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "MusicBrainz does not know this artist"
        ) from None
    except ExternalServiceError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
    if not linked:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown artist")
    return await _discography(request, caller, session, artist_id, refresh=False)


class PluginLinksOut(ApiModel):
    plugin: str
    name: str
    links: list[LinkOut]


@router.get("/artists/{artist_id}/discography/{group}/links")
async def release_group_links(
    artist_id: uuid.UUID, group: str, _: AdminCaller, session: DbSession
) -> list[PluginLinksOut]:
    """Where to find a release group (admins): the links of the enabled plugins."""
    album = await discography.wanted(session, artist_id, group)
    if album is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown release group")
    return [
        PluginLinksOut(
            plugin=found.plugin.id,
            name=found.plugin.name,
            links=[link_out(found.plugin, link) for link in found.links],
        )
        for found in await plugins.album_links(session, album)
    ]


@router.get("/artists/{artist_id}/discography/covers/{group}")
async def discography_cover(
    artist_id: uuid.UUID, group: str, request: Request, _: CurrentCaller, session: DbSession
) -> FileResponse:
    """The cover of one of the artist's release groups (found automatically, cached)."""
    found = None
    if musicbrainz.parse_mbid(group) == group:  # only ids: they name files
        found = await discography.cover(
            session,
            artist_id,
            group,
            http=_http(request),
            cipher=cipher(request),
            covers_dir=_covers_dir(request),
        )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cover")
    path, content_type = found
    return FileResponse(
        path, media_type=content_type, headers={"Cache-Control": "private, max-age=604800"}
    )
