"""Setting an album's cover chosen by an admin: written as `cover.jpg` in the album's
folders (the standard file that beets and other players use too).

A previous cover file is kept as `cover.previous.<ext>` (one level of backup), which the
scanner does not take as a cover. Blocking: run in a thread.
"""

import io
from pathlib import Path

from PIL import Image

from app.library_manager import files
from app.scanner.formats import IMAGE_CONTENT_TYPES, suffix_of

COVER_NAME = "cover.jpg"
MAX_SIDE = 3000


class InvalidImageError(ValueError):
    pass


def as_jpeg(data: bytes) -> bytes:
    """The image as JPEG (kept as is when it already is one and not huge)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.format == "JPEG" and max(image.size) <= MAX_SIDE:
                return data
            image.thumbnail((MAX_SIDE, MAX_SIDE))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92)
            return output.getvalue()
    except (OSError, Image.DecompressionBombError) as error:
        raise InvalidImageError("This file is not a readable image") from error


EMBEDDED_SIDE = 600


def embedded_jpeg(data: bytes) -> bytes:
    """A version of the cover to put inside audio files: at most 600 px, JPEG."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.thumbnail((EMBEDDED_SIDE, EMBEDDED_SIDE))
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88)
            return output.getvalue()
    except (OSError, Image.DecompressionBombError) as error:
        raise InvalidImageError("This file is not a readable image") from error


def write_cover(folders: list[Path], library_root: Path, data: bytes) -> list[Path]:
    """Writes `data` (an image) as the cover of each folder. Returns the folders."""
    jpeg = as_jpeg(data)
    written: list[Path] = []
    for folder in folders:
        folder = files.ensure_within(folder, [library_root])
        for existing in folder.iterdir():
            stem, _, suffix = existing.name.rpartition(".")
            if (
                existing.is_file()
                and stem.casefold() == "cover"
                and suffix_of(existing.name) in IMAGE_CONTENT_TYPES
            ):
                existing.replace(folder / f"cover.previous.{suffix.lower()}")
        temporary = folder / f".{COVER_NAME}.tmp"
        temporary.write_bytes(jpeg)
        temporary.replace(folder / COVER_NAME)
        written.append(folder)
    return written
