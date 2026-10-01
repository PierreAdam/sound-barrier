"""Songs as the web UI's player takes them."""

from typing import Any

from app.services.browsing import SongEntry
from app.services.spoken import BookPlace
from app.subsonic import mappers


def web_song(entry: SongEntry, book: BookPlace | None = None) -> dict[str, Any]:
    """The Subsonic JSON format ("Child"), plus what the Subsonic API has no field for: the
    chapters inside the file (audiobooks), `chapters: [{startMs, title}]`, and where the file
    is in its audiobook, `book: {startMs, durationMs, chapter, chapters}`."""
    song = mappers.song(entry).model_dump(mode="json", by_alias=True, exclude_none=True)
    if entry.song.chapters:
        song["chapters"] = entry.song.chapters
    if book:
        song["book"] = {
            "startMs": book.start_ms,
            "durationMs": book.duration_ms,
            "chapter": book.chapter,
            "chapters": book.chapters,
        }
    return song
