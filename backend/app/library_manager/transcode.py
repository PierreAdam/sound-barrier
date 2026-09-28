"""Import step: convert lossless files to MP3 with ffmpeg before they are imported.

Files are converted into a staging folder (the sources are only read: a download folder
that is still seeding stays intact). Tags and the embedded cover are carried over, and
the folder images are copied next to the converted files so the cover follows too.
"""

import asyncio
import shutil
from dataclasses import replace
from pathlib import Path

from app.library_manager.tagger import ItemInfo, TaggerError
from app.scanner.formats import IMAGE_CONTENT_TYPES, suffix_of

LOSSLESS_SUFFIXES = frozenset({"flac", "wav", "aif", "aiff", "ape", "wv"})
MP3_BITRATE = "320k"
MAX_PARALLEL = 4  # ffmpeg processes at once


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def is_lossless(item: ItemInfo) -> bool:
    return suffix_of(item.path) in LOSSLESS_SUFFIXES


def _command(ffmpeg: str, source: Path, target: Path) -> list[str]:
    return [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-map",
        "0:v?",  # embedded cover, if any
        "-c:a",
        "libmp3lame",
        "-b:a",
        MP3_BITRATE,
        "-c:v",
        "copy",
        "-disposition:v",
        "attached_pic",
        "-map_metadata",
        "0",
        "-id3v2_version",
        "3",
        str(target),
    ]


async def _convert(ffmpeg: str, source: Path, target: Path, limit: asyncio.Semaphore) -> None:
    async with limit:
        process = await asyncio.create_subprocess_exec(
            *_command(ffmpeg, source, target),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip()[-300:]
        raise TaggerError(f"ffmpeg could not convert {source.name}: {detail}")


def _copy_folder_images(sources: set[Path], staging: Path) -> None:
    for folder in sources:
        for image in folder.iterdir():
            target = staging / image.name
            if (
                image.is_file()
                and suffix_of(image.name) in IMAGE_CONTENT_TYPES
                and not target.exists()
            ):
                shutil.copy2(image, target)


async def convert_lossless(items: list[ItemInfo], staging: Path) -> tuple[list[ItemInfo], int]:
    """Converts the lossless items to MP3 in `staging`. Returns the items to import (the
    converted ones point to their MP3 in `staging`) and how many were converted."""
    lossless = [item for item in items if is_lossless(item)]
    if not lossless:
        return items, 0
    ffmpeg = ffmpeg_path()
    if ffmpeg is None:
        raise TaggerError("ffmpeg is not installed: cannot convert lossless files to MP3")
    await asyncio.to_thread(staging.mkdir, parents=True, exist_ok=True)

    targets: dict[str, Path] = {}
    for item in lossless:
        source = Path(item.path)
        target = staging / f"{source.stem}.mp3"
        if target in targets.values():
            raise TaggerError(f"Two files would be converted to the same name: {target.name}")
        targets[item.path] = target

    limit = asyncio.Semaphore(MAX_PARALLEL)
    await asyncio.gather(
        *(_convert(ffmpeg, Path(path), target, limit) for path, target in targets.items())
    )
    await asyncio.to_thread(_copy_folder_images, {Path(i.path).parent for i in lossless}, staging)
    converted = [
        replace(item, path=str(targets[item.path])) if item.path in targets else item
        for item in items
    ]
    return converted, len(targets)


async def clean_staging(staging: Path) -> None:
    await asyncio.to_thread(shutil.rmtree, staging, ignore_errors=True)
