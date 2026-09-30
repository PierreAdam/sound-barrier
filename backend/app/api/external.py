"""External services: settings (admins) and artist information for the artist page."""

import re
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import AdminCaller, ApiModel, CurrentCaller, DbSession, cipher
from app.core.config import Settings
from app.external import ExternalServiceError, books, fanart
from app.external.lastfm import InvalidApiKeyError, LastFm
from app.external.pictures import PROVIDERS
from app.services import artist_info, media, server_settings
from app.subsonic import mappers

router = APIRouter(tags=["external"])


def _http(request: Request) -> httpx.AsyncClient:
    return request.app.state.http


def _pictures_dir(request: Request) -> Path:
    settings: Settings = request.app.state.settings
    return settings.data_dir / "artist-pictures"


# --- settings -------------------------------------------------------------------------


class PictureSource(ApiModel):
    id: str
    label: str
    needs_key: str | None = None  # e.g. "fanart": usable once that key is set


class ExternalSettingsOut(ApiModel):
    lastfm_key_set: bool  # the keys themselves are never sent back
    fanart_key_set: bool
    picture_source: str  # "none" or a provider id
    picture_sources: list[PictureSource]
    musicbrainz: bool  # discographies ("Missing albums"), audiobook editions (import review)
    lrclib: bool  # song lyrics
    # Audiobook / podcast import review lookups.
    audible: bool
    audible_region: str
    audible_regions: list[str]
    open_library: bool
    itunes: bool
    cast_receiver_app_id: str | None  # the "Now playing" screen on Chromecasts
    dashcast: bool  # without it: that screen through DashCast (a third party's receiver)


class ExternalSettingsIn(ApiModel):
    # None: keep the stored key; "": remove it; else the new key (checked with Last.fm).
    lastfm_key: str | None = None
    fanart_key: str | None = None  # same: None keeps it, "" removes it
    picture_source: str = "deezer"
    musicbrainz: bool | None = None  # None keeps the current choice
    lrclib: bool | None = None  # same
    audible: bool | None = None  # same
    audible_region: str | None = None
    open_library: bool | None = None
    itunes: bool | None = None
    cast_receiver_app_id: str | None = None  # None keeps it, "" removes it
    dashcast: bool | None = None  # None keeps the current choice


def _settings_out(settings: server_settings.ExternalServices) -> ExternalSettingsOut:
    return ExternalSettingsOut(
        lastfm_key_set=settings.lastfm_key_enc is not None,
        fanart_key_set=settings.fanart_key_enc is not None,
        picture_source=settings.picture_source,
        musicbrainz=settings.musicbrainz,
        lrclib=settings.lrclib,
        audible=settings.audible,
        audible_region=settings.audible_region,
        audible_regions=list(books.AUDIBLE_REGIONS),
        open_library=settings.open_library,
        itunes=settings.itunes,
        cast_receiver_app_id=settings.cast_receiver_app_id,
        dashcast=settings.dashcast,
        picture_sources=[PictureSource(id="none", label="None")]
        + [
            PictureSource(id=p.id, label=p.label, needs_key=p.needs_key) for p in PROVIDERS.values()
        ],
    )


@router.get("/external/settings")
async def get_external_settings(_: AdminCaller, session: DbSession) -> ExternalSettingsOut:
    return _settings_out(await server_settings.get_external_services(session))


@router.put("/external/settings")
async def set_external_settings(
    body: ExternalSettingsIn, request: Request, _: AdminCaller, session: DbSession
) -> ExternalSettingsOut:
    if body.picture_source != "none" and body.picture_source not in PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown picture source")
    settings = await server_settings.get_external_services(session)
    if body.lastfm_key is not None:
        key = body.lastfm_key.strip()
        if key:
            try:
                await LastFm(_http(request), key).check_key()
            except InvalidApiKeyError:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Last.fm refused this API key"
                ) from None
            except ExternalServiceError as error:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
            settings.lastfm_key_enc = cipher(request).encrypt(key).decode()
        else:
            settings.lastfm_key_enc = None
    if body.fanart_key is not None:
        key = body.fanart_key.strip()
        if key:
            try:
                await fanart.check_key(_http(request), key)
            except fanart.InvalidFanartKeyError:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "fanart.tv refused this API key"
                ) from None
            except ExternalServiceError as error:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from None
            settings.fanart_key_enc = cipher(request).encrypt(key).decode()
        else:
            settings.fanart_key_enc = None
    provider = PROVIDERS.get(body.picture_source)
    if (
        provider is not None
        and provider.needs_key == fanart.KEY_NAME
        and not settings.fanart_key_enc
    ):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"{provider.label} needs its API key first"
        )
    settings.picture_source = body.picture_source
    if body.musicbrainz is not None:
        settings.musicbrainz = body.musicbrainz
    if body.lrclib is not None:
        settings.lrclib = body.lrclib
    if body.audible_region is not None:
        if body.audible_region not in books.AUDIBLE_REGIONS:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown Audible region")
        settings.audible_region = body.audible_region
    for name in ("audible", "open_library", "itunes", "dashcast"):
        value = getattr(body, name)
        if value is not None:
            setattr(settings, name, value)
    if body.cast_receiver_app_id is not None:
        app_id = body.cast_receiver_app_id.strip().upper()
        if app_id and not re.fullmatch(r"[0-9A-F]{8}", app_id):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "A Cast application id is 8 hexadecimal characters (e.g. 1A2B3C4D)",
            )
        settings.cast_receiver_app_id = app_id or None
    await server_settings.set_external_services(session, settings)
    await session.commit()
    return _settings_out(settings)


# --- artist information ---------------------------------------------------------------


class SimilarArtistOut(ApiModel):
    name: str
    id: uuid.UUID | None  # in the library


class PictureOut(ApiModel):
    source: str  # e.g. "Deezer"
    page_url: str | None
    cover_art: str  # for getCoverArt, changes with the picture


class ArtistInfoOut(ApiModel):
    lastfm_configured: bool
    lastfm_url: str | None
    summary: str | None
    biography: str | None
    similar: list[SimilarArtistOut]
    # Songs of the library, in the Subsonic JSON format ("Child"), most popular first.
    top_songs: list[dict[str, Any]]
    picture: PictureOut | None
    error: str | None  # admins only: why information is missing


async def _info(
    request: Request,
    caller: CurrentCaller,
    session: DbSession,
    artist_id: uuid.UUID,
    refresh: bool,
) -> ArtistInfoOut:
    details = await artist_info.get(
        session,
        caller.user,
        artist_id,
        http=_http(request),
        cipher=cipher(request),
        pictures_dir=_pictures_dir(request),
        refresh=refresh,
    )
    if details is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown artist")
    await session.commit()
    picture = details.picture
    return ArtistInfoOut(
        lastfm_configured=details.lastfm_configured,
        lastfm_url=details.lastfm_url,
        summary=details.summary,
        biography=details.biography,
        similar=[SimilarArtistOut(name=s.name, id=s.artist_id) for s in details.similar],
        top_songs=[
            mappers.song(entry).model_dump(mode="json", by_alias=True, exclude_none=True)
            for entry in details.top_songs
        ],
        picture=PictureOut(
            source=picture.source,
            page_url=picture.page_url,
            cover_art=media.artist_picture_id(artist_id, picture.version),
        )
        if picture
        else None,
        error=details.error if caller.user.is_admin else None,
    )


@router.get("/artists/{artist_id}/info")
async def get_artist_info(
    artist_id: uuid.UUID, request: Request, caller: CurrentCaller, session: DbSession
) -> ArtistInfoOut:
    """Biography, similar artists, top songs and picture (fetched first if needed)."""
    return await _info(request, caller, session, artist_id, refresh=False)


@router.post("/artists/{artist_id}/info/refresh")
async def refresh_artist_info(
    artist_id: uuid.UUID, request: Request, caller: AdminCaller, session: DbSession
) -> ArtistInfoOut:
    """Fetches the information again now (admins)."""
    return await _info(request, caller, session, artist_id, refresh=True)
