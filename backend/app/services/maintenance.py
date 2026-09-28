"""Regular cleanups: run 10 minutes after start, then once a day (and from Manage Library).

- beets' database backups left by its migrations (`library.db-before-*.bak`);
- beets entries whose file no longer exists;
- import staging folders left behind (e.g. an interrupted conversion);
- resized covers not regenerated for a long time (they are made again when needed);
- downloaded artist pictures no artist uses any more.
"""

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from app.core.db import Database
from app.library_manager.imports import ImportManager
from app.models import ArtistInfo

logger = logging.getLogger(__name__)

FIRST_RUN_DELAY = 10 * 60
EVERY = 24 * 60 * 60
OLD_STAGING = 24 * 60 * 60
OLD_CACHED_COVER = 60 * 24 * 60 * 60


@dataclass
class CleanupReport:
    beets_backups: int = 0
    beets_missing: int = 0
    staging_folders: int = 0
    cached_covers: int = 0
    artist_pictures: int = 0

    def __str__(self) -> str:
        return ", ".join(f"{name.replace('_', ' ')}: {value}" for name, value in vars(self).items())


def _old(path: Path, seconds: float) -> bool:
    try:
        return time.time() - path.stat().st_mtime > seconds
    except OSError:
        return False


def _files(
    beets_dir: Path, staging: Path, covers: Path, pictures: Path, used: set[str], busy: bool
) -> tuple[int, int, int, int]:
    backups = 0
    for backup in beets_dir.glob("library.db-before-*.bak"):
        backup.unlink(missing_ok=True)
        backups += 1
    folders = 0
    if staging.is_dir() and not busy:  # nothing may be converting right now
        for folder in staging.iterdir():
            if folder.is_dir() and _old(folder, OLD_STAGING):
                shutil.rmtree(folder, ignore_errors=True)
                folders += 1
    cached = 0
    if covers.is_dir():
        for cover in covers.iterdir():
            if cover.is_file() and _old(cover, OLD_CACHED_COVER):
                cover.unlink(missing_ok=True)
                cached += 1
    pictures_removed = 0
    if pictures.is_dir():
        for picture in pictures.iterdir():
            if picture.is_file() and (picture.name not in used or picture.suffix == ".tmp"):
                picture.unlink(missing_ok=True)
                pictures_removed += 1
    return backups, folders, cached, pictures_removed


class Maintenance:
    def __init__(
        self, db: Database, imports: ImportManager, data_dir: Path, beets_dir: Path
    ) -> None:
        self._db = db
        self._imports = imports
        self._data_dir = data_dir
        self._beets_dir = beets_dir
        self._lock = asyncio.Lock()
        self.last_report: CleanupReport | None = None

    async def run(self, library_root: Path | None) -> CleanupReport:
        async with self._lock:
            report = CleanupReport()
            async with self._db.session() as session:
                used = {
                    str(artist_id)
                    for artist_id in await session.scalars(
                        select(ArtistInfo.artist_id).where(ArtistInfo.picture_source.is_not(None))
                    )
                }
            (
                report.beets_backups,
                report.staging_folders,
                report.cached_covers,
                report.artist_pictures,
            ) = await asyncio.to_thread(
                _files,
                self._beets_dir,
                self._data_dir / "import-staging",
                self._data_dir / "cache" / "covers",
                self._data_dir / "artist-pictures",
                used,
                self._imports.busy,
            )
            if library_root is not None:
                tagger = self._imports.tagger
                report.beets_missing = await self._imports.call_tagger(
                    tagger.forget_missing, library_root
                )
            self.last_report = report
            logger.info("Cleanup done: %s", report)
            return report

    async def run_forever(self, library_root: "LibraryRoot") -> None:
        await asyncio.sleep(FIRST_RUN_DELAY)
        while True:
            try:
                await self.run(await library_root())
            except Exception:
                logger.exception("Cleanup failed")
            await asyncio.sleep(EVERY)


class LibraryRoot:
    """The current library folder (it can change in Settings)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def __call__(self) -> Path | None:
        from app.services import music_folders

        async with self._db.session() as session:
            folder = await music_folders.get_library(session)
        return Path(folder.path) if folder else None
