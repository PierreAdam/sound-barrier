"""Library scans in the server process: on demand, at startup and on a daily schedule."""

import asyncio
import contextlib
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Database
from app.models import Scan, Song
from app.scanner.scanner import DEFAULT_WORKERS, ScanAlreadyRunningError, run_scan
from app.services import server_settings

logger = logging.getLogger(__name__)

# The scheduler re-checks at least this often (clock changes, missed wake-ups).
_MAX_SLEEP_SECONDS = 3600
_RETRY_SECONDS = 60


def local_timezone() -> tzinfo:
    """The server's time zone: `TZ` (e.g. Europe/Paris, as set in Docker), else the OS one."""
    name = os.environ.get("TZ")
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("Unknown time zone TZ=%r, using the system time zone", name)
    local = datetime.now().astimezone().tzinfo
    assert local is not None
    return local


def next_run(now: datetime, hour: int, minute: int, tz: tzinfo) -> datetime:
    """The next HH:MM (in `tz`) strictly after `now`."""
    local_now = now.astimezone(tz)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        # Aware arithmetic keeps the wall-clock time, so DST changes are handled by tz.
        candidate = (candidate.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=tz)
    return candidate


class ScanManager:
    def __init__(self, db: Database, *, workers: int = DEFAULT_WORKERS) -> None:
        self._db = db
        self._workers = workers
        self._task: asyncio.Task[bool] | None = None
        self._rescan_requested = False
        self._targeted = asyncio.Lock()  # one targeted scan at a time
        self._schedule_changed = asyncio.Event()
        self.next_run_at: datetime | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, *, full: bool = False) -> bool:
        """Starts a scan unless one is already running in this process."""
        if self.running:
            return False
        self._task = asyncio.create_task(self._run(full), name="library-scan")
        return True

    def request(self) -> None:
        """A quick scan now, or right after the running one (e.g. after an import: the
        running scan may have listed the folders before the new files arrived)."""
        if not self.start():
            self._rescan_requested = True

    async def scan_paths(self, folder_id: int, paths: list[str]) -> bool:
        """Scans only `paths` (relative to the music folder) and waits for the result:
        the library shows an import / deletion as soon as this returns. Waits for a scan
        already running first. Returns False if the scan could not run (a quick scan is
        then requested instead)."""
        async with self._targeted:
            while self._task is not None and not self._task.done():
                with contextlib.suppress(Exception):
                    await asyncio.shield(self._task)
            self._task = asyncio.create_task(
                self._run(False, {folder_id: paths}), name="library-scan"
            )
            return await asyncio.shield(self._task)

    async def _run(self, full: bool, targets: dict[int, list[str]] | None = None) -> bool:
        """Runs a scan, then the one requested meanwhile. True if this scan succeeded."""
        ok = False
        try:
            await run_scan(self._db, full=full, workers=self._workers, targets=targets)
            ok = True
        except ScanAlreadyRunningError:
            logger.info("A scan is already running in another process")
            self._rescan_requested = self._rescan_requested or targets is not None
        except Exception:
            logger.exception("Library scan failed")
            self._rescan_requested = self._rescan_requested or targets is not None
        if self._rescan_requested:
            self._rescan_requested = False
            self._task = asyncio.create_task(self._run(False), name="library-scan")
        return ok

    def schedule_changed(self) -> None:
        """Called after the schedule is saved: the scheduler recomputes the next run."""
        self._schedule_changed.set()

    async def run_scheduler(self) -> None:
        """Startup scan (if enabled), then one quick scan a day at the configured time."""
        schedule = await self._load_schedule()
        if schedule is not None and schedule.scan_on_startup:
            self.start()
        while True:
            schedule = await self._load_schedule()
            if schedule is None:  # database unavailable: retry later
                await asyncio.sleep(_RETRY_SECONDS)
                continue
            self._schedule_changed.clear()
            if not schedule.enabled:
                self.next_run_at = None
                await self._schedule_changed.wait()
                continue
            self.next_run_at = next_run(datetime.now(UTC), *schedule.hour_minute, local_timezone())
            delay = (self.next_run_at - datetime.now(UTC)).total_seconds()
            try:
                await asyncio.wait_for(
                    self._schedule_changed.wait(), timeout=max(0, min(delay, _MAX_SLEEP_SECONDS))
                )
            except TimeoutError:
                if datetime.now(UTC) >= self.next_run_at:
                    logger.info("Scheduled library scan")
                    self.start()

    async def _load_schedule(self) -> server_settings.ScanSchedule | None:
        try:
            async with self._db.session() as session:
                return await server_settings.get_scan_schedule(session)
        except Exception:
            logger.exception("Cannot read the scan schedule")
            return None

    async def stop(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


@dataclass(frozen=True)
class ScanStatus:
    running: bool
    latest: Scan | None
    song_count: int
    next_run_at: datetime | None


async def latest_scan(session: AsyncSession) -> Scan | None:
    return await session.scalar(select(Scan).order_by(Scan.id.desc()).limit(1))


async def count_present_songs(session: AsyncSession) -> int:
    statement = select(func.count()).select_from(Song).where(Song.missing_since.is_(None))
    return await session.scalar(statement) or 0


async def status(session: AsyncSession, manager: ScanManager) -> ScanStatus:
    latest = await latest_scan(session)
    # The scan task may not have created its row yet, hence `manager.running`.
    running = manager.running or (latest is not None and latest.status == "running")
    return ScanStatus(running, latest, await count_present_songs(session), manager.next_run_at)
