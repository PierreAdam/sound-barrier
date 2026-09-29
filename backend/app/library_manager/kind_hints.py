"""Whether a folder of the import browser looks like audiobooks or podcasts rather than
music: a hint for the admin (the import buttons), never a decision.

Strong signals only, cheapest first: words in the folder names ("Audiobook", "Unabridged",
"Narrated by", "Podcast"...), M4B files, then the genre tag of a few files ("Audiobook",
"Spoken Word", "Podcast"). Blocking: call it in a thread. Results are kept until the
folder changes (its modification time).
"""

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from app.library_manager.files import is_audio
from app.scanner.tags import read_audio_file

AUDIOBOOK, PODCAST = "audiobook", "podcast"
MAX_FOLDERS = 200  # walked under one listed folder
GENRE_FOLDERS = 2  # album folders whose first file's genre is read
_AUDIOBOOK_WORDS = re.compile(
    r"\b(audio ?books?|unabridged|abridged|narrated by|read by|livres? audio|h[öo]rb[üu]ch(er)?|"
    r"audiolibros?|audiolibri|lu par)\b",
    re.I,
)
_PODCAST_WORDS = re.compile(r"\bpodcasts?\b", re.I)
_AUDIOBOOK_GENRES = re.compile(r"audio ?book|spoken ?word|h[öo]rbuch|livre audio|audiolibro", re.I)
_PODCAST_GENRES = re.compile(r"podcast", re.I)


@dataclass(frozen=True)
class KindHint:
    path: str
    kind: str  # audiobook, podcast
    reason: str  # for people: 'name ("Unabridged")', "M4B files", 'genre "Audiobook"'


_cache: dict[str, tuple[int, KindHint | None]] = {}
_lock = threading.Lock()


def hint(folder: Path) -> KindHint | None:
    """The hint for a listed folder, read again only when it changed."""
    key = os.path.normcase(str(folder))
    try:
        mtime = folder.stat().st_mtime_ns
    except OSError:
        return None
    with _lock:
        cached = _cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    found = _hint(folder)
    with _lock:
        _cache[key] = (mtime, found)
    return found


def _hint(folder: Path) -> KindHint | None:
    album_folders: list[Path] = []
    for count, (current, dirs, names) in enumerate(os.walk(folder)):
        if count >= MAX_FOLDERS:
            break
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        name = Path(current).name
        for words, kind in ((_AUDIOBOOK_WORDS, AUDIOBOOK), (_PODCAST_WORDS, PODCAST)):
            match = words.search(name)
            if match:
                return KindHint(str(folder), kind, f'name ("{match.group(0)}")')
        audio = sorted(n for n in names if is_audio(Path(n)))
        if any(n.casefold().endswith(".m4b") for n in audio):
            return KindHint(str(folder), AUDIOBOOK, "M4B files")
        if audio:
            album_folders.append(Path(current) / audio[0])
    for path in album_folders[:GENRE_FOLDERS]:
        audio = read_audio_file(path)
        if audio is None:
            continue
        for genre in audio.tags.genres:
            if _AUDIOBOOK_GENRES.search(genre):
                return KindHint(str(folder), AUDIOBOOK, f'genre "{genre}"')
            if _PODCAST_GENRES.search(genre):
                return KindHint(str(folder), PODCAST, f'genre "{genre}"')
    return None
