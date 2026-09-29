"""Song lyrics, synced when possible, for the web UI's "Now playing" and getLyrics /
getLyricsBySongId.

Sources, best first: a `.lrc` file next to the song, lyrics in the file's tags (plain, or
LRC text), then LRCLIB (online, when allowed in Settings). Synced lyrics win over plain
ones. LRCLIB's answers (also "none") are kept in the data folder (`lyrics/<song id>.json`):
the files of the library are never written.
"""

import asyncio
import json
import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.external import ExternalServiceError, lrclib
from app.models import Album, MusicFolder, Song
from app.scanner.tags import read_audio_file
from app.services import server_settings

logger = logging.getLogger(__name__)

RETRY_AFTER = timedelta(days=30)  # LRCLIB had nothing, or failed: asked again after that
_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_STAMP = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")  # enhanced LRC
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\]\s*$", re.IGNORECASE | re.MULTILINE)
_TAG_LINE = re.compile(r"^\[[a-z]+:.*\]\s*$", re.IGNORECASE)  # [ar:...], [ti:...]


@dataclass
class Word:
    start_ms: int
    text: str  # with its trailing space, if any


@dataclass
class Line:
    start_ms: int | None  # None: not synced
    text: str
    words: list[Word] | None = None  # word by word timing ("enhanced LRC"), when known


@dataclass
class SongLyrics:
    source: str  # "lrc", "embedded", "lrclib"
    synced: bool
    lines: list[Line] = field(default_factory=list[Line])
    instrumental: bool = False


class LyricsUnavailableError(Exception):
    """No lyrics with the file, and LRCLIB could not be asked (try again later)."""


def _millis(minutes: str, seconds: str, fraction: str | None) -> int:
    return (int(minutes) * 60 + int(seconds)) * 1000 + int((fraction or "0").ljust(3, "0")[:3])


def _words(text: str, offset: int) -> tuple[str, list[Word] | None]:
    """The line's text, and its words when they carry their own times
    ("<00:12.00>Word <00:12.48>by <00:12.90>word")."""
    stamps = list(_WORD_STAMP.finditer(text))
    plain = " ".join(_WORD_STAMP.sub("", text).split())
    if not stamps:
        return plain, None
    words: list[Word] = []
    for index, stamp in enumerate(stamps):
        end = stamps[index + 1].start() if index + 1 < len(stamps) else len(text)
        word = text[stamp.end() : end]
        if word.strip():
            spaced = " ".join(word.split()) + (" " if word[-1].isspace() else "")
            words.append(Word(max(_millis(*stamp.groups()) - offset, 0), spaced))
    return plain, words or None


def parse(text: str) -> tuple[bool, list[Line]]:
    """(synced, lines) of plain or LRC text. An LRC line may carry several timestamps
    ("[00:12.00][01:30.50]Chorus"), and its words their own ("enhanced LRC");
    `[offset:+250]` shifts them all (positive: earlier)."""
    offset_match = _OFFSET.search(text)
    offset = int(offset_match.group(1)) if offset_match else 0
    timed: list[Line] = []
    plain: list[Line] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        stamps = list(_TIMESTAMP.finditer(raw))
        if stamps:
            words, timings = _words(_TIMESTAMP.sub("", raw).strip(), offset)
            first = max(_millis(*stamps[0].groups()) - offset, 0)
            for stamp in stamps:
                start = max(_millis(*stamp.groups()) - offset, 0)
                # A repeated line ("[00:12.00][01:30.50]"): its words move with it.
                shifted = (
                    [Word(w.start_ms + start - first, w.text) for w in timings] if timings else None
                )
                timed.append(Line(start, words, shifted))
        elif not _TAG_LINE.match(raw.strip()):
            plain.append(Line(None, raw.rstrip()))
    if timed:
        return True, sorted(timed, key=lambda line: line.start_ms or 0)
    while plain and not plain[0].text:
        plain.pop(0)
    while plain and not plain[-1].text:
        plain.pop()
    return False, plain


def _local(path: Path) -> list[SongLyrics]:
    """The lyrics found with the file: its `.lrc`, its tags."""
    found: list[SongLyrics] = []
    sidecar = path.with_suffix(".lrc")
    if sidecar.is_file():
        try:
            synced, lines = parse(sidecar.read_text("utf-8", errors="replace"))
            if lines:
                found.append(SongLyrics("lrc", synced, lines))
        except OSError as error:
            logger.warning("Cannot read %s: %s", sidecar, error)
    audio = read_audio_file(path) if path.is_file() else None
    if audio is not None and audio.tags.lyrics:
        synced, lines = parse(audio.tags.lyrics)
        if lines:
            found.append(SongLyrics("embedded", synced, lines))
    return found


def _read_cache(path: Path) -> tuple[bool, SongLyrics | None]:
    """(cached and recent, lyrics): LRCLIB's last answer."""
    try:
        data: dict[str, Any] = json.loads(path.read_text("utf-8"))
        at = datetime.fromisoformat(data["at"])
    except (OSError, ValueError, KeyError):
        return False, None
    found: dict[str, Any] | None = data.get("lyrics")
    if found is None:
        return datetime.now(UTC) - at < RETRY_AFTER, None
    lines = [
        Line(
            line.get("start_ms"),
            str(line.get("text", "")),
            [Word(int(w["start_ms"]), str(w["text"])) for w in line["words"]]
            if line.get("words")
            else None,
        )
        for line in found["lines"]
    ]
    lyrics = SongLyrics("lrclib", bool(found["synced"]), lines, bool(found.get("instrumental")))
    return True, lyrics


def _write_cache(path: Path, lyrics: SongLyrics | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    content = {"at": datetime.now(UTC).isoformat(), "lyrics": asdict(lyrics) if lyrics else None}
    temporary.write_text(json.dumps(content), "utf-8")
    temporary.replace(path)


async def _online(
    song: Song, album: Album, http: httpx.AsyncClient, cache: Path
) -> SongLyrics | None:
    """LRCLIB's lyrics (cached); LyricsUnavailableError if it cannot be asked and has
    never answered for this song."""
    fresh, cached = await asyncio.to_thread(_read_cache, cache)
    if fresh:
        return cached
    try:
        found = await lrclib.find(
            http, song.display_artist, song.title, album.name, round(song.duration_ms / 1000)
        )
    except ExternalServiceError as error:
        logger.warning("LRCLIB, %s - %s: %s", song.display_artist, song.title, error)
        if cached is None:
            raise LyricsUnavailableError(str(error)) from error
        return cached  # an older answer; asked again next time
    lyrics: SongLyrics | None = None
    if found is not None:
        text = found.synced or found.plain
        synced, lines = parse(text) if text else (False, [])
        if lines or found.instrumental:
            lyrics = SongLyrics("lrclib", synced, lines, found.instrumental)
    await asyncio.to_thread(_write_cache, cache, lyrics)
    return lyrics


async def get(
    session: AsyncSession, song_id: uuid.UUID, *, http: httpx.AsyncClient, data_dir: Path
) -> SongLyrics | None:
    """The best lyrics of a song (synced first); None if there are none anywhere.
    LyricsUnavailableError when there are none with the file and LRCLIB is unreachable."""
    song = await session.get(Song, song_id)
    if song is None or song.missing_since is not None:
        return None
    folder = await session.get(MusicFolder, song.music_folder_id)
    album = await session.get(Album, song.album_id)
    if folder is None or album is None:
        return None
    local = await asyncio.to_thread(_local, Path(folder.path) / song.path)
    best = next((found for found in local if found.synced), None)
    if best is not None:
        return best
    settings = await server_settings.get_external_services(session)
    if settings.lrclib:
        try:
            online = await _online(song, album, http, data_dir / "lyrics" / f"{song.id}.json")
        except LyricsUnavailableError:
            if not local:
                raise
            online = None
        if online is not None and (online.synced or not local):
            return online
    return local[0] if local else None
