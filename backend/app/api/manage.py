"""Manage Library (admins): import settings, browsing, imports and review, deletion."""

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import Field

from app.api.deps import AdminCaller, ApiModel, DbSession
from app.library_manager import deletion, files, imports, transcode
from app.library_manager import status as library_state
from app.library_manager.imports import ImportManager, ImportRequestError
from app.models import ImportJob, ImportTask, MusicFolder
from app.services import music_folders, server_settings
from app.services.maintenance import Maintenance
from app.services.scans import ScanManager

router = APIRouter(prefix="/manage", tags=["manage"])


def _imports(request: Request) -> ImportManager:
    return request.app.state.imports


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, message)


# --- settings -------------------------------------------------------------------------


class ManageSettings(ApiModel):
    root: str | None  # import root folder
    root_reachable: bool
    mode: str
    auto_apply_strong: bool
    transcode_lossless: bool
    ffmpeg_available: bool
    tagger: str  # name of the tagging engine
    matching: bool  # False: only "import as-is"


class ManageSettingsUpdate(ApiModel):
    root: str | None
    auto_apply_strong: bool = True
    transcode_lossless: bool = False


async def _settings_out(
    request: Request, settings: server_settings.ImportSettings
) -> ManageSettings:
    reachable = bool(settings.root) and await asyncio.to_thread(Path(settings.root or "").is_dir)
    tagger = _imports(request).tagger
    return ManageSettings(
        root=settings.root,
        root_reachable=reachable,
        mode=settings.mode,
        auto_apply_strong=settings.auto_apply_strong,
        transcode_lossless=settings.transcode_lossless,
        ffmpeg_available=transcode.ffmpeg_path() is not None,
        tagger=tagger.name,
        matching=tagger.supports_matching,
    )


@router.get("/settings")
async def get_settings(request: Request, _: AdminCaller, session: DbSession) -> ManageSettings:
    return await _settings_out(request, await server_settings.get_import_settings(session))


def _absolute(raw: str) -> Path:
    return Path(os.path.normpath(Path(raw.strip()).expanduser().absolute()))


@router.put("/settings")
async def set_settings(
    body: ManageSettingsUpdate, request: Request, _: AdminCaller, session: DbSession
) -> ManageSettings:
    root = None
    if body.root and body.root.strip():
        path = await asyncio.to_thread(_absolute, body.root)
        if not await asyncio.to_thread(path.is_dir):
            raise _bad_request(f"Not a directory (or not reachable): {path}")
        root = str(path)
    if body.transcode_lossless and transcode.ffmpeg_path() is None:
        raise _bad_request("ffmpeg is not installed on the server: conversion is not possible")
    settings = await server_settings.get_import_settings(session)
    settings.root = root
    settings.auto_apply_strong = body.auto_apply_strong
    settings.transcode_lossless = body.transcode_lossless
    await server_settings.set_import_settings(session, settings)
    await session.commit()
    return await _settings_out(request, settings)


async def _import_root(session: DbSession) -> Path:
    root = (await server_settings.get_import_settings(session)).root
    if not root:
        raise _bad_request("No import root folder configured (Settings)")
    return Path(root)


# --- browsing -------------------------------------------------------------------------


class Entry(ApiModel):
    name: str
    path: str
    is_dir: bool
    audio_files: int
    size: int


class BrowseResponse(ApiModel):
    root: str
    path: str
    parent: str | None  # None at the import root
    entries: list[Entry]


@router.get("/browse")
async def browse(_: AdminCaller, session: DbSession, path: str | None = None) -> BrowseResponse:
    """Lists a folder inside the import root (no path: the root itself)."""
    root = await _import_root(session)
    try:
        target = await asyncio.to_thread(files.ensure_within, path or root, [root])
        listing = await asyncio.to_thread(files.list_folder, target)
    except files.OutsideAllowedFolderError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Outside the import root folder") from None
    except OSError as error:
        raise _bad_request(f"Cannot read {path or root}: {error.strerror or error}") from None
    at_root = files.real(target) == files.real(root)
    return BrowseResponse(
        root=str(root),
        path=str(target),
        parent=None if at_root else str(target.parent),
        entries=[Entry(**vars(e)) for e in listing],
    )


# --- imports --------------------------------------------------------------------------


class ImportRequest(ApiModel):
    paths: list[str]


class TaskOut(ApiModel):
    id: int
    job_id: int
    source_dir: str
    status: str
    items: list[dict[str, Any]]
    candidates: list[dict[str, Any]]
    recommendation: str | None
    decision: dict[str, Any] | None
    result: dict[str, Any] | None
    error: str | None
    updated_at: datetime


class JobOut(ApiModel):
    id: int
    kind: str  # import (new music) or adopt (library albums added to beets)
    sources: list[str]
    status: str
    error: str | None
    created_at: datetime
    finished_at: datetime | None
    tasks: list[TaskOut]


def _task_out(task: ImportTask) -> TaskOut:
    return TaskOut.model_validate(task, from_attributes=True)


def _job_out(job: ImportJob, tasks: list[ImportTask]) -> JobOut:
    return JobOut(
        id=job.id,
        kind=job.kind,
        sources=job.sources,
        status=job.status,
        error=job.error,
        created_at=job.created_at,
        finished_at=job.finished_at,
        tasks=[_task_out(t) for t in tasks],
    )


@router.post("/imports", status_code=status.HTTP_202_ACCEPTED)
async def start_import(
    body: ImportRequest, request: Request, caller: AdminCaller, session: DbSession
) -> JobOut:
    root = await _import_root(session)
    if not body.paths:
        raise _bad_request("Select at least one folder")
    try:
        sources = [await asyncio.to_thread(files.ensure_within, p, [root]) for p in body.paths]
    except files.OutsideAllowedFolderError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Outside the import root folder") from None
    job_id = await _imports(request).create_job(caller.user.id, sources)
    job = await session.get(ImportJob, job_id)
    assert job is not None
    return _job_out(job, [])


@router.get("/imports")
async def list_imports(request: Request, _: AdminCaller) -> list[JobOut]:
    return [_job_out(job, tasks) for job, tasks in await imports.list_jobs(request.app.state.db)]


class Decision(ApiModel):
    action: str  # apply, as_is, skip, retry
    candidate_id: str | None = None


class SearchRequest(ApiModel):
    artist: str | None = None
    album: str | None = None
    release_id: str | None = None


async def _task(session: DbSession, task_id: int) -> TaskOut:
    task = await session.get(ImportTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown import task")
    return _task_out(task)


@router.post("/tasks/{task_id}/decision")
async def decide(
    task_id: int, body: Decision, request: Request, _: AdminCaller, session: DbSession
) -> TaskOut:
    try:
        await _imports(request).decide(task_id, body.action, body.candidate_id)
    except ImportRequestError as error:
        raise _bad_request(str(error)) from None
    return await _task(session, task_id)


class ReviewCounts(ApiModel):
    pending: int  # waiting for a decision
    failed: int


class BulkDecision(ApiModel):
    action: str  # skip or retry
    status: str  # pending or failed: the albums it applies to


class BulkResult(ApiModel):
    changed: int


@router.get("/tasks/counts")
async def review_counts(request: Request, _: AdminCaller) -> ReviewCounts:
    return ReviewCounts(**await _imports(request).review_counts())


@router.post("/tasks/bulk")
async def decide_all(body: BulkDecision, request: Request, _: AdminCaller) -> BulkResult:
    """Skip or retry every pending / failed album at once (e.g. after an interrupted run)."""
    try:
        changed = await _imports(request).decide_all(body.action, body.status)
    except ImportRequestError as error:
        raise _bad_request(str(error)) from None
    return BulkResult(changed=changed)


@router.post("/tasks/{task_id}/search")
async def search(
    task_id: int, body: SearchRequest, request: Request, _: AdminCaller, session: DbSession
) -> TaskOut:
    try:
        await _imports(request).search(
            task_id, artist=body.artist, album=body.album, release_id=body.release_id
        )
    except ImportRequestError as error:
        raise _bad_request(str(error)) from None
    return await _task(session, task_id)


# --- library status and maintenance ---------------------------------------------------

MAX_LISTED_FOLDERS = 2000


class UnknownFolderOut(ApiModel):
    path: str
    artist: str
    album: str
    songs: int
    unknown_songs: int


class LibraryStatusOut(ApiModel):
    library_path: str
    albums: int
    songs: int
    size_bytes: int  # the songs' files on the disk
    tagger: str
    has_tagger_database: bool  # False: the tagger keeps no database (no beets)
    tagger_albums: int
    tagger_songs: int
    tagger_missing: int
    unknown_folder_count: int
    unknown_folders: list[UnknownFolderOut]  # at most MAX_LISTED_FOLDERS


async def _library_folder(session: DbSession) -> MusicFolder:
    folder = await music_folders.get_library(session)
    if folder is None:
        raise _bad_request("No library folder configured (Settings)")
    return folder


@router.get("/library-status")
async def library_status(request: Request, _: AdminCaller, session: DbSession) -> LibraryStatusOut:
    folder = await _library_folder(session)
    result = await library_state.library_status(session, _imports(request), folder)
    return LibraryStatusOut(
        library_path=folder.path,
        albums=result.albums,
        songs=result.songs,
        size_bytes=result.size_bytes,
        tagger=_imports(request).tagger.name,
        has_tagger_database=result.has_tagger_database,
        tagger_albums=result.tagger_albums,
        tagger_songs=result.tagger_songs,
        tagger_missing=result.tagger_missing,
        unknown_folder_count=len(result.unknown_folders),
        unknown_folders=[
            UnknownFolderOut(**vars(f)) for f in result.unknown_folders[:MAX_LISTED_FOLDERS]
        ],
    )


class AdoptRequest(ApiModel):
    paths: list[str]  # album folders, relative to the library folder


@router.post("/adopt", status_code=status.HTTP_202_ACCEPTED)
async def adopt(
    body: AdoptRequest, request: Request, caller: AdminCaller, session: DbSession
) -> JobOut:
    """Adds library album folders to the tagger's database: matched like an import
    (unclear matches wait in Review), tags written, files left where they are."""
    folder = await _library_folder(session)
    root = Path(folder.path)
    if not body.paths:
        raise _bad_request("Select at least one folder")
    try:
        sources = [
            await asyncio.to_thread(files.ensure_within, root / p.strip("/"), [root])
            for p in body.paths
        ]
    except files.OutsideAllowedFolderError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Outside the library folder") from None
    job_id = await _imports(request).create_job(caller.user.id, sources, kind=imports.ADOPT)
    job = await session.get(ImportJob, job_id)
    assert job is not None
    return _job_out(job, [])


class ForgetMissingOut(ApiModel):
    removed: int


@router.post("/forget-missing")
async def forget_missing(request: Request, _: AdminCaller, session: DbSession) -> ForgetMissingOut:
    """Removes from the tagger's database the entries whose file no longer exists."""
    folder = await _library_folder(session)
    manager = _imports(request)
    removed = await manager.call_tagger(manager.tagger.forget_missing, Path(folder.path))
    return ForgetMissingOut(removed=removed)


class CleanupOut(ApiModel):
    beets_backups: int
    beets_missing: int
    staging_folders: int
    cached_covers: int
    artist_pictures: int


@router.post("/cleanup")
async def cleanup(request: Request, _: AdminCaller, session: DbSession) -> CleanupOut:
    """The daily cleanup, now (beets leftovers, staging folders, old cached covers...)."""
    folder = await music_folders.get_library(session)
    maintenance: Maintenance = request.app.state.maintenance
    report = await maintenance.run(Path(folder.path) if folder else None)
    return CleanupOut(**vars(report))


# --- deletion -------------------------------------------------------------------------


class DeleteRequest(ApiModel):
    album_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])
    song_ids: list[uuid.UUID] = Field(default_factory=list[uuid.UUID])


class DeleteResponse(ApiModel):
    songs: int
    files_deleted: int
    files_already_gone: int
    folders_removed: list[str]


@router.post("/delete")
async def delete_music(
    body: DeleteRequest, request: Request, _: AdminCaller, session: DbSession
) -> DeleteResponse:
    """Deletes albums and / or songs permanently: files on disk and library entries."""
    if not body.album_ids and not body.song_ids:
        raise _bad_request("Nothing to delete")
    forget = _imports(request).forget
    total = deletion.DeletionResult()
    for result in (
        await deletion.delete_albums(session, body.album_ids, forget) if body.album_ids else None,
        await deletion.delete_songs(session, body.song_ids, forget) if body.song_ids else None,
    ):
        if result is not None:
            total.songs += result.songs
            total.files_deleted += result.files_deleted
            total.files_already_gone += result.files_already_gone
            total.folders_removed += result.folders_removed
            for folder_id, directories in result.directories.items():
                total.directories.setdefault(folder_id, set()).update(directories)
    await session.commit()
    # Folder browsing forgets the removed folders before the page reloads.
    scans: ScanManager = request.app.state.scans
    for folder_id, directories in total.directories.items():
        await scans.scan_paths(folder_id, sorted(directories))
    return DeleteResponse(
        songs=total.songs,
        files_deleted=total.files_deleted,
        files_already_gone=total.files_already_gone,
        folders_removed=total.folders_removed,
    )
