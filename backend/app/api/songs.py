"""Songs as the web UI's player takes them."""

from typing import Any

from app.services.browsing import SongEntry
from app.subsonic import mappers


def web_song(entry: SongEntry) -> dict[str, Any]:
    """The Subsonic JSON format ("Child"), plus the chapters inside the file (audiobooks),
    which the Subsonic API has no field for: `chapters: [{startMs, title}]`."""
    song = mappers.song(entry).model_dump(mode="json", by_alias=True, exclude_none=True)
    if entry.song.chapters:
        song["chapters"] = entry.song.chapters
    return song
