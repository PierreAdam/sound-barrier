"""Chapters inside an audio file ("soft" chapters of an audiobook), written back into it.

- MP3: ID3 CHAP frames (one per chapter, its title in a TIT2 sub-frame) and a CTOC
  listing them.
- M4A / M4B: mutagen cannot write MP4 chapters: ffmpeg rewrites the file with the new
  chapter list (Nero `chpl` atom and QuickTime chapter track, both read by the scanner),
  the audio and cover copied as they are (no re-encoding), the tags kept.

The scanner reads them back (scanner/tags.py, `_chapters`).
"""

# mutagen has no type information.
# pyright: basic

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

MP4_SUFFIXES = (".m4a", ".m4b", ".mp4")
FFMPEG_TIMEOUT_S = 600  # a large M4B is copied, not re-encoded: seconds, not minutes


class ChapterWriteError(Exception):
    pass


@dataclass(frozen=True)
class Chapter:
    start_ms: int
    title: str


def can_write(path: Path) -> bool:
    return path.suffix.lower() in (".mp3", *MP4_SUFFIXES)


def _clean(chapters: list[Chapter], duration_ms: int) -> list[Chapter]:
    """By start, inside the file, no two at the same time, the first at 0."""
    found: dict[int, str] = {}
    for chapter in sorted(chapters, key=lambda c: c.start_ms):
        if 0 <= chapter.start_ms < max(duration_ms, 1):
            found.setdefault(chapter.start_ms, " ".join(chapter.title.split()) or "Chapter")
    cleaned = [Chapter(start, title) for start, title in found.items()]
    if cleaned and cleaned[0].start_ms != 0:
        cleaned[0] = Chapter(0, cleaned[0].title)
    return cleaned


def _write_id3(path: Path, chapters: list[Chapter], duration_ms: int) -> None:
    from mutagen.id3 import CHAP, CTOC, ID3, TIT2, CTOCFlags, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("CHAP")
    tags.delall("CTOC")
    ids: list[str] = []
    for index, chapter in enumerate(chapters):
        end = chapters[index + 1].start_ms if index + 1 < len(chapters) else duration_ms
        element = f"chp{index}"
        tags.add(
            CHAP(
                element_id=element,
                start_time=chapter.start_ms,
                end_time=max(end, chapter.start_ms),
                start_offset=0xFFFFFFFF,  # "not used": the times are what counts
                end_offset=0xFFFFFFFF,
                sub_frames=[TIT2(encoding=3, text=[chapter.title])],
            )
        )
        ids.append(element)
    tags.add(
        CTOC(
            element_id="toc",
            flags=CTOCFlags.TOP_LEVEL | CTOCFlags.ORDERED,
            child_element_ids=ids,
            sub_frames=[TIT2(encoding=3, text=["Chapters"])],
        )
    )
    tags.save(str(path))


def _ffmetadata_escape(value: str) -> str:
    for char in ("\\", "=", ";", "#", "\n"):
        value = value.replace(char, "\\" + char)
    return value


def _write_mp4(path: Path, chapters: list[Chapter], duration_ms: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise ChapterWriteError("ffmpeg is needed to write the chapters of M4A / M4B files")
    lines = [";FFMETADATA1"]
    for index, chapter in enumerate(chapters):
        end = chapters[index + 1].start_ms if index + 1 < len(chapters) else duration_ms
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={chapter.start_ms}",
            f"END={max(end, chapter.start_ms + 1)}",
            f"title={_ffmetadata_escape(chapter.title)}",
        ]
    metadata = path.with_name(f".{path.stem}.chapters.txt")
    output = path.with_name(f".{path.stem}.chapters{path.suffix}")
    metadata.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(path),
                "-f",
                "ffmetadata",
                "-i",
                str(metadata),
                # The audio and the cover (not the old chapter track: the new list replaces it).
                "-map",
                "0:a",
                "-map",
                "0:v?",
                "-map_metadata",
                "0",
                "-map_chapters",
                "1",
                "-c",
                "copy",
                "-disposition:v",
                "attached_pic",
                "-f",
                "mp4",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_S,
            check=False,
        )
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise ChapterWriteError(
                f"ffmpeg could not write the chapters: {result.stderr.strip()[-500:]}"
            )
        output.replace(path)
    except subprocess.TimeoutExpired as error:
        raise ChapterWriteError("ffmpeg took too long to write the chapters") from error
    finally:
        metadata.unlink(missing_ok=True)
        output.unlink(missing_ok=True)


def write(path: Path, chapters: list[Chapter], duration_ms: int) -> None:
    """Replaces the chapters inside `path` (at least two: one chapter is the file itself)."""
    cleaned = _clean(chapters, duration_ms)
    if len(cleaned) < 2:
        raise ChapterWriteError("A file needs at least two chapters")
    suffix = path.suffix.lower()
    try:
        if suffix == ".mp3":
            _write_id3(path, cleaned, duration_ms)
        elif suffix in MP4_SUFFIXES:
            _write_mp4(path, cleaned, duration_ms)
        else:
            raise ChapterWriteError(
                f"Chapters can be written into MP3 and M4A / M4B files, not {suffix} files"
            )
    except OSError as error:
        raise ChapterWriteError(f"Cannot write the chapters of {path.name}: {error}") from error
