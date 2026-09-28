"""Folders given by the deployment (Docker mounts), applied while nothing is configured."""

import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import music_folders, server_settings

logger = logging.getLogger(__name__)


async def apply_initial_folders(
    session: AsyncSession, *, library_dir: Path | None, import_dir: Path | None
) -> None:
    """Sets the library folder and the import root folder if they are not set yet.

    Settings changed later in the web UI always win: this only fills empty values.
    """
    if library_dir is not None and await music_folders.get_library(session) is None:
        try:
            folder, _ = await music_folders.set_library(session, str(library_dir), "Music")
            logger.info("Library folder set to %s", folder.path)
        except music_folders.InvalidMusicFolderError as error:
            logger.warning("Initial library folder ignored: %s", error)
    if import_dir is not None:
        settings = await server_settings.get_import_settings(session)
        if settings.root is None:
            if import_dir.is_dir():  # noqa: ASYNC240 - one check at startup
                settings.root = str(import_dir)
                await server_settings.set_import_settings(session, settings)
                logger.info("Import root folder set to %s", import_dir)
            else:
                logger.warning("Initial import folder ignored, not a directory: %s", import_dir)
