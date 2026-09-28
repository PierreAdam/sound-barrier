"""Library folder, scans and scan schedule (admins), library revision (signed-in users)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.deps import AdminCaller, ApiModel, CurrentCaller, DbSession, scan_manager
from app.models import MusicFolder, Scan
from app.services import music_folders, scans, server_settings

router = APIRouter(tags=["library"])


# --- revision ---------------------------------------------------------------


class LibraryRevision(ApiModel):
    revision: int  # changes whenever the library may have changed


@router.get("/library/revision")
async def get_revision(_: CurrentCaller, session: DbSession) -> LibraryRevision:
    """Polled by the web UI: when it changes, cached lists (artists, albums) are reloaded.

    Every change of the library tables goes with a scan (imports and deletions run a
    targeted one), so the last finished scan identifies the library state.
    """
    latest = await session.scalar(select(func.max(Scan.id)).where(Scan.finished_at.is_not(None)))
    return LibraryRevision(revision=latest or 0)


# --- library folder ---------------------------------------------------------


class LibraryFolder(ApiModel):
    id: int
    name: str
    path: str
    reachable: bool


class LibraryFolderUpdate(ApiModel):
    path: str
    name: str = "Music"


class LibraryResponse(ApiModel):
    folder: LibraryFolder | None


async def _folder_out(folder: MusicFolder) -> LibraryFolder:
    reachable = await asyncio.to_thread(Path(folder.path).is_dir)
    return LibraryFolder(id=folder.id, name=folder.name, path=folder.path, reachable=reachable)


@router.get("/library")
async def get_library(_: AdminCaller, session: DbSession) -> LibraryResponse:
    folder = await music_folders.get_library(session)
    return LibraryResponse(folder=await _folder_out(folder) if folder else None)


@router.put("/library")
async def set_library(
    body: LibraryFolderUpdate, request: Request, _: AdminCaller, session: DbSession
) -> LibraryResponse:
    """Sets the library path. A quick scan starts when the path changes."""
    try:
        folder, changed = await music_folders.set_library(session, body.path, body.name)
    except music_folders.InvalidMusicFolderError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    await session.commit()
    if changed:
        scan_manager(request).start()
    return LibraryResponse(folder=await _folder_out(folder))


# --- scans --------------------------------------------------------------------


class ScanInfo(ApiModel):
    id: int
    kind: str  # quick, full, targeted
    status: str  # running, done, failed
    phase: str  # starting, walking, reading, finishing, done, failed
    started_at: datetime
    finished_at: datetime | None
    files_seen: int
    files_to_read: int
    files_read: int
    added: int
    updated: int
    removed: int
    error: str | None


class ScanStatusResponse(ApiModel):
    running: bool
    song_count: int
    latest: ScanInfo | None
    next_run_at: datetime | None


class ScanRequest(ApiModel):
    full: bool = False


async def _status(request: Request, session: DbSession) -> ScanStatusResponse:
    result = await scans.status(session, scan_manager(request))
    latest = result.latest
    return ScanStatusResponse(
        running=result.running,
        song_count=result.song_count,
        latest=ScanInfo.model_validate(latest, from_attributes=True) if latest else None,
        next_run_at=result.next_run_at,
    )


@router.get("/scan")
async def get_scan(request: Request, _: AdminCaller, session: DbSession) -> ScanStatusResponse:
    return await _status(request, session)


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
async def start_scan(
    body: ScanRequest, request: Request, _: AdminCaller, session: DbSession
) -> ScanStatusResponse:
    scan_manager(request).start(full=body.full)
    return await _status(request, session)


# --- schedule -----------------------------------------------------------------


class ScheduleBody(ApiModel):
    enabled: bool
    time: str  # HH:MM, server local time
    scan_on_startup: bool


class ScheduleResponse(ScheduleBody):
    next_run_at: datetime | None
    time_zone: str


def _schedule_out(schedule: server_settings.ScanSchedule) -> ScheduleResponse:
    tz = scans.local_timezone()
    next_run_at = None
    if schedule.enabled:
        next_run_at = scans.next_run(datetime.now(UTC), *schedule.hour_minute, tz)
    return ScheduleResponse(**schedule.model_dump(), next_run_at=next_run_at, time_zone=str(tz))


@router.get("/scan/schedule")
async def get_schedule(_: AdminCaller, session: DbSession) -> ScheduleResponse:
    return _schedule_out(await server_settings.get_scan_schedule(session))


@router.put("/scan/schedule")
async def set_schedule(
    body: ScheduleBody, request: Request, _: AdminCaller, session: DbSession
) -> ScheduleResponse:
    try:
        schedule = server_settings.ScanSchedule(**body.model_dump())
    except ValidationError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, error.errors()[0]["msg"]) from None
    await server_settings.set_scan_schedule(session, schedule)
    await session.commit()
    scan_manager(request).schedule_changed()  # the scheduler recomputes its next run
    return _schedule_out(schedule)
