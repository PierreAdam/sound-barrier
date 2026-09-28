import os
import time
from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.config import Settings
from tests.integration.conftest import SubsonicUser, signed_in

pytestmark = pytest.mark.integration

DAYS = 24 * 3600


def _touch(path: Path, age_days: float = 0, *, folder: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if folder:
        path.mkdir(exist_ok=True)
    else:
        path.write_bytes(b"x")
    when = time.time() - age_days * DAYS
    os.utime(path, (when, when))
    return path


async def test_cleanup(
    app: FastAPI, admin: SubsonicUser, settings: Settings, library: Path
) -> None:
    data = settings.data_dir
    backup = _touch(data / "beets" / "library.db-before-items-relative_path.bak")
    beets_db = _touch(data / "beets" / "library-keep.db")
    old_staging = _touch(data / "import-staging" / "task-1", age_days=2, folder=True)
    new_staging = _touch(data / "import-staging" / "task-2", folder=True)
    old_cover = _touch(data / "cache" / "covers" / "old.jpg", age_days=90)
    new_cover = _touch(data / "cache" / "covers" / "new.jpg")
    orphan = _touch(data / "artist-pictures" / "00000000-0000-0000-0000-000000000001")

    async with signed_in(app, admin) as web:
        report = (await web.post("/api/manage/cleanup")).json()
    assert (report["beetsBackups"], report["stagingFolders"], report["cachedCovers"]) == (1, 1, 1)
    assert report["artistPictures"] >= 1  # (other tests may leave unused pictures too)
    assert (
        not backup.exists()
        and not old_staging.exists()
        and not old_cover.exists()
        and not orphan.exists()
    )
    assert beets_db.exists() and new_staging.exists() and new_cover.exists()


async def test_cleanup_is_for_admins(app: FastAPI, user: SubsonicUser) -> None:
    async with signed_in(app, user) as web:
        assert (await web.post("/api/manage/cleanup")).status_code == 403
