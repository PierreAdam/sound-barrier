"""Writing tags and pictures into audio files (tag editor, embedded covers), with
mediafile (beets' tag library: the same field names for every format). Blocking."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Fields the tag editor may change (mediafile names).
EDITABLE_FIELDS = frozenset(
    {"title", "artist", "album", "albumartist", "year", "genre", "track", "disc", "comp"}
)


class TagWriteError(OSError):
    pass


@dataclass
class TagChange:
    path: Path
    fields: dict[str, Any]  # mediafile field -> value (None clears it)


def write(change: TagChange) -> None:
    import mediafile

    unknown = set(change.fields) - EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"Not editable: {', '.join(sorted(unknown))}")
    try:
        media: Any = mediafile.MediaFile(str(change.path))
        for name, value in change.fields.items():
            setattr(media, name, value)
        if "year" in change.fields:  # a new year: the old month and day no longer apply
            media.month = None
            media.day = None
        media.save()
    except (mediafile.UnreadableFileError, OSError) as error:
        raise TagWriteError(f"Cannot write the tags of {change.path.name}: {error}") from error


def embed_picture(path: Path, jpeg: bytes) -> None:
    """Replaces the pictures inside the file with this front cover."""
    import mediafile

    try:
        media: Any = mediafile.MediaFile(str(path))
        media.images = [mediafile.Image(data=jpeg, type=mediafile.ImageType.front)]
        media.save()
    except (mediafile.UnreadableFileError, OSError) as error:
        raise TagWriteError(f"Cannot embed the cover in {path.name}: {error}") from error
