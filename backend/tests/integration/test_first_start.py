from pathlib import Path

import pytest
from sqlalchemy import delete, text

from app.core.db import Database
from app.models import ServerSetting
from app.services import music_folders, server_settings
from app.services.first_start import apply_initial_folders
from tests.integration.conftest import LIBRARY_TABLES

pytestmark = pytest.mark.integration


async def test_initial_folders_fill_only_empty_settings(db: Database, tmp_path: Path) -> None:
    music, imports, other = tmp_path / "music", tmp_path / "import", tmp_path / "other"
    for folder in (music, imports, other):
        folder.mkdir()
    async with db.session() as session:
        await session.execute(text(f"TRUNCATE {LIBRARY_TABLES} CASCADE"))
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.IMPORT_SETTINGS_KEY)
        )
        await apply_initial_folders(session, library_dir=music, import_dir=imports)
        await session.commit()

        library = await music_folders.get_library(session)
        assert library is not None and library.path == str(music)
        assert (await server_settings.get_import_settings(session)).root == str(imports)

        # Next starts: what is configured (e.g. changed in the web UI) is kept.
        await apply_initial_folders(session, library_dir=other, import_dir=other)
        await session.commit()
        library = await music_folders.get_library(session)
        assert library is not None and library.path == str(music)
        assert (await server_settings.get_import_settings(session)).root == str(imports)


async def test_missing_initial_folders_are_ignored(db: Database, tmp_path: Path) -> None:
    async with db.session() as session:
        await session.execute(text(f"TRUNCATE {LIBRARY_TABLES} CASCADE"))
        await session.execute(
            delete(ServerSetting).where(ServerSetting.key == server_settings.IMPORT_SETTINGS_KEY)
        )
        missing = tmp_path / "missing"
        await apply_initial_folders(session, library_dir=missing, import_dir=missing)
        await session.commit()
        assert await music_folders.get_library(session) is None
        assert (await server_settings.get_import_settings(session)).root is None
