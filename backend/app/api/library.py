"""Library folder, scans and scan schedule (admins), library revision (signed-in users)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.deps import AdminCaller, ApiModel, CurrentCaller, DbSession, scan_manager
from app.models import MusicFolder, Scan
from app.services import browsing, music_folders, scans, server_settings

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


# --- podcasts and audiobooks: their folders and switches ---------------------------------


class SpokenFolder(ApiModel):
    enabled: bool  # turned on by an admin (menu entry, import choice, Subsonic channels)
    folder: LibraryFolder | None


class SpokenFolders(ApiModel):
    podcasts: SpokenFolder
    audiobooks: SpokenFolder


class SpokenFolderUpdate(ApiModel):
    enabled: bool
    # None keeps the folder; "" removes it (its songs leave the library, files stay).
    path: str | None = None


async def _spoken_out(session: DbSession) -> SpokenFolders:
    switches = await server_settings.get_spoken_audio(session)
    found: dict[str, SpokenFolder] = {}
    for kind in music_folders.SPOKEN_KINDS:
        folder = await music_folders.get_folder(session, kind)
        found[kind] = SpokenFolder(
            enabled=switches.enabled(kind), folder=await _folder_out(folder) if folder else None
        )
    return SpokenFolders(podcasts=found["podcasts"], audiobooks=found["audiobooks"])


@router.get("/library/spoken")
async def get_spoken_folders(_: AdminCaller, session: DbSession) -> SpokenFolders:
    return await _spoken_out(session)


@router.put("/library/spoken/{kind}")
async def set_spoken_folder(
    kind: str, body: SpokenFolderUpdate, request: Request, _: AdminCaller, session: DbSession
) -> SpokenFolders:
    """The podcasts or audiobooks folder and switch. A quick scan starts when the path
    changes."""
    if kind not in music_folders.SPOKEN_KINDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown kind")
    changed = False
    if body.path is not None and body.path.strip():
        try:
            __, changed = await music_folders.set_folder(session, kind, body.path)
        except music_folders.InvalidMusicFolderError as error:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    elif body.path is not None:
        folder = await music_folders.get_folder(session, kind)
        if folder is not None:
            await music_folders.remove(session, folder.id)
    switches = await server_settings.get_spoken_audio(session)
    setattr(switches, kind, body.enabled)
    await server_settings.set_spoken_audio(session, switches)
    await session.commit()
    if changed:
        # A scan may be running (e.g. both folders set one after the other): then right after.
        scan_manager(request).request()
    return await _spoken_out(session)


class Sections(ApiModel):
    """The library sections a user has: Podcasts / Audiobooks when on and set up."""

    podcasts: bool
    audiobooks: bool


@router.get("/library/sections")
async def get_sections(caller: CurrentCaller, session: DbSession) -> Sections:
    available = {
        kind: bool(await browsing.spoken_folder_ids(session, caller.user, kind))
        for kind in music_folders.SPOKEN_KINDS
    }
    return Sections(podcasts=available["podcasts"], audiobooks=available["audiobooks"])


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
