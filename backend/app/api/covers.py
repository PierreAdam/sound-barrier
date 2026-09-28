"""Album covers chosen by admins: search the cover sources, preview, apply."""

import asyncio
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from app.api.deps import AdminCaller, ApiModel, DbSession, cipher
from app.external import ExternalServiceError
from app.external import covers as sources
from app.library_manager import covers
from app.library_manager.imports import ImportManager
from app.library_manager.tag_files import TagWriteError
from app.models import Album, MusicFolder, Song
from app.services import artist_info, server_settings
from app.services.scans import ScanManager

router = APIRouter(tags=["covers"])


class CoverResultOut(ApiModel):
    source: str
    source_label: str
    title: str
    artist: str
    image_url: str
    thumbnail_url: str  # through this server (see /covers/thumbnail)
    width: int | None
    height: int | None
    page_url: str | None


class CoverSearchOut(ApiModel):
    query: str
    results: list[CoverResultOut]
    errors: list[str]  # sources that could not be searched


async def _album(session: DbSession, album_id: uuid.UUID) -> Album:
    album = await session.get(Album, album_id)
    if album is None or album.missing_since is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown album")
    return album


@router.get("/albums/{album_id}/cover-search")
async def search_covers(
    album_id: uuid.UUID, request: Request, _: AdminCaller, session: DbSession, q: str | None = None
) -> CoverSearchOut:
    album = await _album(session, album_id)
    query = (q or "").strip() or f"{album.display_artist} {album.name}"
    http = request.app.state.http
    settings = await server_settings.get_external_services(session)
    context = sources.CoverContext(
        release_group_id=album.mbz_release_group_id,
        keys=artist_info.api_keys(settings, cipher(request)),
    )
    results: list[CoverResultOut] = []
    errors: list[str] = []
    found = await asyncio.gather(
        *(provider.search(http, query, context) for provider in sources.COVER_PROVIDERS.values()),
        return_exceptions=True,
    )
    for provider, outcome in zip(sources.COVER_PROVIDERS.values(), found, strict=True):
        if isinstance(outcome, BaseException):
            if not isinstance(outcome, ExternalServiceError):
                raise outcome
            errors.append(f"{provider.label}: {outcome}")
            continue
        results += [
            CoverResultOut(
                source=r.source,
                source_label=provider.label,
                title=r.title,
                artist=r.artist,
                image_url=r.image_url,
                thumbnail_url=f"/api/covers/thumbnail?url={quote(r.thumbnail_url, safe='')}",
                width=r.width,
                height=r.height,
                page_url=r.page_url,
            )
            for r in outcome
        ]
    return CoverSearchOut(query=query, results=results, errors=errors)


@router.get("/covers/thumbnail")
async def thumbnail(url: str, request: Request, _: AdminCaller) -> Response:
    """A search result's image, fetched by the server (the browser never contacts the
    source). Only from the hosts of the cover sources."""
    try:
        data, content_type = await sources.download(request.app.state.http, url)
    except ExternalServiceError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    return Response(
        data, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"}
    )


class SetCoverIn(ApiModel):
    image_url: str  # from a search result
    embed: bool = False  # also inside the audio files (600 px)


class SetCoverOut(ApiModel):
    cover_art: str | None  # the album's new coverArt id
    folders: list[str]  # where cover.jpg was written (relative to the library)
    embedded: int  # audio files the cover was embedded into


@router.post("/albums/{album_id}/cover")
async def set_cover(
    album_id: uuid.UUID, body: SetCoverIn, request: Request, _: AdminCaller, session: DbSession
) -> SetCoverOut:
    """Downloads the image and makes it the album's cover (cover.jpg in its folders)."""
    await _album(session, album_id)
    rows = (
        await session.execute(
            select(Song.path, MusicFolder.id, MusicFolder.path)
            .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
            .where(Song.album_id == album_id, Song.missing_since.is_(None))
        )
    ).all()
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This album has no file")
    folder_id, root = rows[0][1], Path(rows[0][2])
    folders = sorted({(root / path).parent for path, fid, _ in rows if fid == folder_id})
    try:
        data, _content_type = await sources.download(request.app.state.http, body.image_url)
        written = await asyncio.to_thread(covers.write_cover, folders, root, data)
        embedded: list[Path] = []
        if body.embed:
            jpeg = await asyncio.to_thread(covers.embedded_jpeg, data)
            embedded = [root / path for path, fid, _ in rows if fid == folder_id]
            imports: ImportManager = request.app.state.imports
            await imports.call_tagger(imports.tagger.embed_cover, embedded, jpeg, root)
    except (ExternalServiceError, covers.InvalidImageError, TagWriteError) as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    except OSError as error:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Cannot write the cover: {error.strerror}"
        ) from None
    relative = [folder.relative_to(root).as_posix() for folder in written]
    # The library shows the new cover as soon as this returns.
    scans: ScanManager = request.app.state.scans
    await scans.scan_paths(folder_id, relative)
    session.expire_all()
    album = await session.get(Album, album_id)
    return SetCoverOut(
        cover_art=str(album.artwork_id) if album and album.artwork_id else None,
        folders=relative,
        embedded=len(embedded),
    )
