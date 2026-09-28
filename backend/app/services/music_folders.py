import asyncio
import os
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppUser, MusicFolder, UserMusicFolder


class InvalidMusicFolderError(Exception):
    pass


async def list_all(session: AsyncSession) -> Sequence[MusicFolder]:
    return (await session.scalars(select(MusicFolder).order_by(MusicFolder.id))).all()


async def list_for_user(session: AsyncSession, user: AppUser) -> Sequence[MusicFolder]:
    """Folders the user may access. A user with no explicit restriction sees every folder."""
    restricted = (
        await session.scalars(
            select(MusicFolder)
            .join(UserMusicFolder, UserMusicFolder.music_folder_id == MusicFolder.id)
            .where(UserMusicFolder.user_id == user.id)
            .order_by(MusicFolder.id)
        )
    ).all()
    return restricted or await list_all(session)


async def remove(session: AsyncSession, folder_id: int) -> MusicFolder | None:
    """Unregisters a folder. Its directories, songs and artwork rows go with it (FK
    cascades); albums and artists left without songs are marked missing by the next scan.
    Files on disk are never touched."""
    folder = await session.get(MusicFolder, folder_id)
    if folder is not None:
        await session.delete(folder)
        await session.flush()
    return folder


async def _checked_path(path: str | Path) -> Path:
    """Absolute, normalized path of an existing directory."""
    if not str(path).strip():
        raise InvalidMusicFolderError("The folder path cannot be empty")
    # absolute(), not resolve(): on Windows resolve() rewrites mapped network drives
    # (e.g. W:) into UNC paths that are not always reachable.
    resolved = await asyncio.to_thread(
        lambda: Path(os.path.normpath(Path(path).expanduser().absolute()))
    )
    if not await asyncio.to_thread(resolved.is_dir):
        raise InvalidMusicFolderError(f"Not a directory (or not reachable): {resolved}")
    return resolved


async def get_library(session: AsyncSession) -> MusicFolder | None:
    """The library folder. The web UI manages a single folder (the first one)."""
    return await session.scalar(select(MusicFolder).order_by(MusicFolder.id).limit(1))


async def set_library(session: AsyncSession, path: str, name: str) -> tuple[MusicFolder, bool]:
    """Creates the library folder or changes its path / name. Returns (folder, path changed).

    Changing the path keeps the folder id: songs are stored relative to it, so moving the
    same library to a new place (e.g. a Docker mount) keeps every song and user data.
    """
    resolved = await _checked_path(path)
    name = name.strip() or "Music"
    folder = await get_library(session)
    if folder is None:
        return await create(session, name, resolved), True
    changed = folder.path != str(resolved)
    folder.path = str(resolved)
    folder.name = name
    await session.flush()
    return folder, changed


async def create(session: AsyncSession, name: str, path: str | Path) -> MusicFolder:
    resolved = await _checked_path(path)
    existing = await session.scalar(select(MusicFolder).where(MusicFolder.path == str(resolved)))
    if existing is not None:
        raise InvalidMusicFolderError(f"Music folder already exists: {resolved}")
    folder = MusicFolder(name=name, path=str(resolved))
    session.add(folder)
    await session.flush()
    return folder
