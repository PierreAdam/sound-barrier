"""Importing audiobooks and podcasts through the review (docs/specs/spoken-import-review.md).

1. `find_units`: the books / shows in the selected folders (disc-like sub-folders such as
   "CD1" belong to their parent's book).
2. `read_files` + `propose`: the files with their tags, and the metadata the review starts
   from (cleaned titles, author, chapters in order).
3. `plan` + `place`: once reviewed, one folder per book / show (`<Author>/<Title>/` or
   `<Show>/`), files renamed ("03 - The Knight Bus.mp3"), tags rewritten, the cover saved.

Blocking (file system, tags): call it in a thread.
"""

import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.core.text import consistent_numbers, natural_key
from app.library_manager import files
from app.library_manager.tagger import TaggerError
from app.scanner.formats import IMAGE_CONTENT_TYPES, suffix_of
from app.scanner.tags import extract_picture, read_audio_file

AUDIOBOOK, PODCAST = "audiobook", "podcast"
VARIOUS = {"various artists", "various", "va"}

# A folder that is only a part of a book: "CD1", "CD 02", "Disc 3", "Part 2", "Vol. 2"...
_DISC_FOLDER = re.compile(
    r"^\s*(cd|disc|disk|disque|part|partie|teil|vol\.?|volume)\s*[-_#.]?\s*\d+\s*$", re.I
)
# Noise in folder names / album tags.
_NOISE = re.compile(
    r"[\[(][^\])]*(unabridged|abridged|audio ?book|audiobook|mp3|m4b|\d+ ?kbps)[^\])]*[\])]"
    r"|\b(unabridged|audiobook|audio book)\b",
    re.I,
)
_CODE_PREFIX = re.compile(r"^\s*[A-Z]{1,4}\d{1,3}\s*[:.\-]\s+")  # "HP03: ..."
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,3})\s*[-_.)]*\s+(?=\D)")  # "1 HARRY POTTER"
# A chapter / track number in front of a title: "CH01 ", "01 - ", "Track 3. ", "Chapter 01 - ".
_CHAPTER_PREFIX = re.compile(
    r"^\s*((ch|chapter|chapitre|kapitel|track|piste|part)\s*\.?\s*)?\d{1,4}(\s*[-_.:)]+\s*|\s+)(?=\S)",
    re.I,
)
# "The Boy Who Lived_01", "The Worst Birthday 01" (not "Book 2").
_COPY_SUFFIX = re.compile(r"(_\d{1,2}|\s+0\d)$")
# Quotes around a whole title: straight, curly, guillemets.
_OPENING_QUOTES = "\"'“\u2018«"
_CLOSING_QUOTES = "\"'”\u2019»"


@dataclass
class SpokenFile:
    """An audio file of a book / show being imported, with what its tags say."""

    path: str  # absolute
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    composer: str | None = None
    compilation: bool = False
    track: int | None = None
    disc: int | None = None
    year: int | None = None
    date: str | None = None  # ISO date (tags, else the file date)
    genre: str | None = None
    comment: str | None = None
    duration_ms: int = 0
    has_picture: bool = False
    chapters: int = 0  # chapters inside the file

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "SpokenFile":
        return cls(**data)


@dataclass
class Entry:
    """A chapter (audiobook) or an episode (podcast) as reviewed."""

    path: str
    title: str
    date: str | None = None  # podcasts: YYYY-MM-DD


@dataclass
class SpokenMetadata:
    """What the review edits, and what the import writes."""

    title: str
    author: str
    narrator: str | None = None
    series: str | None = None
    series_number: str | None = None
    year: int | None = None
    genre: str | None = None
    description: str | None = None
    cover: str | None = None  # "folder:<path>", "embedded:<path>", "url:<url>", None
    entries: list[Entry] = field(default_factory=list[Entry])
    # The MusicBrainz edition used (written to the tags: the edition stays identified).
    musicbrainz_release_id: str | None = None
    musicbrainz_release_group_id: str | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "SpokenMetadata":
        return cls(
            title=data["title"],
            author=data.get("author") or "",
            narrator=data.get("narrator"),
            series=data.get("series"),
            series_number=data.get("series_number"),
            year=data.get("year"),
            genre=data.get("genre"),
            description=data.get("description"),
            cover=data.get("cover"),
            entries=[Entry(**e) for e in data.get("entries", [])],
            musicbrainz_release_id=data.get("musicbrainz_release_id"),
            musicbrainz_release_group_id=data.get("musicbrainz_release_group_id"),
        )


# --- 1. books / shows in the selection ---------------------------------------------------


def find_units(source: Path) -> list[list[Path]]:
    """The books / shows in `source`: for each, its folders (the main one first). A
    folder named like "CD1" / "Part 2" belongs to its parent's book."""
    units: dict[Path, list[Path]] = {}
    for folder in files.find_album_folders(source):
        owner = folder
        while owner != source and _DISC_FOLDER.match(owner.name):
            owner = owner.parent
        units.setdefault(owner, [])
        if folder != owner:
            units[owner].append(folder)
    return [
        [owner, *sorted(parts, key=lambda p: natural_key(p.name))] for owner, parts in units.items()
    ]


def read_files(folders: list[Path]) -> list[SpokenFile]:
    """The audio files of a book / show (its folders in order), with their tags."""
    found: list[SpokenFile] = []
    for folder in folders:
        audio_files = [p for p in folder.iterdir() if p.is_file() and files.is_audio(p)]
        for path in sorted(audio_files, key=lambda p: natural_key(p.name)):
            audio = read_audio_file(path)
            if audio is None:
                continue
            tags = audio.tags
            mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()
            found.append(
                SpokenFile(
                    path=str(path),
                    title=tags.title,
                    artist=tags.display_artist,
                    album=tags.album,
                    album_artist=tags.display_album_artist,
                    composer=", ".join(tags.composers) or None,
                    compilation=tags.compilation,
                    track=tags.track_number,
                    disc=tags.disc_number,
                    year=tags.year,
                    date=_iso_date(tags.date or tags.release_date) or mtime,
                    genre=tags.genres[0] if tags.genres else None,
                    comment=tags.comment,
                    duration_ms=audio.info.duration_ms,
                    has_picture=tags.has_picture,
                    chapters=len(audio.chapters),
                )
            )
    return found


def folder_images(folders: list[Path]) -> list[Path]:
    """Pictures next to the files, covers first ("cover", "folder", "front")."""
    images = [
        p
        for folder in folders
        for p in folder.iterdir()
        if p.is_file() and suffix_of(p.name) in IMAGE_CONTENT_TYPES
    ]

    def rank(path: Path) -> tuple[int, str]:
        name = path.stem.casefold()
        return (0 if any(w in name for w in ("cover", "folder", "front")) else 1, name)

    return sorted(images, key=rank)


def _iso_date(value: str | None) -> str | None:
    if value and re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return value[:10]
    return None


# --- 2. the proposal -----------------------------------------------------------------------


def clean_title(value: str) -> str:
    """A book / show name from a folder name or an album tag: without leading numbers,
    codes ("HP03:") and noise ("(Unabridged)"); ALL CAPS become Title Case."""
    text = _NOISE.sub(" ", value)
    text = _CODE_PREFIX.sub("", text)
    text = _LEADING_NUMBER.sub("", text)
    text = re.sub(r"\s+", " ", text.replace("_", " ")).strip(" -.")
    return _title_case(text) if text.isupper() else text


def clean_chapter(value: str) -> str:
    """A chapter / episode title from a title tag or a file name: without its number
    ("CH01 ", "Chapter 01 - ") and copy suffixes ("_01"); quotes around it go
    ('Chapter 1: “The Boy Who Lived”'); ALL CAPS become Title Case."""
    text = _COPY_SUFFIX.sub("", value.strip())
    stripped = _CHAPTER_PREFIX.sub("", text, count=1).strip(" -.")
    text = stripped or text
    if len(text) > 2 and text[0] in _OPENING_QUOTES and text[-1] in _CLOSING_QUOTES:
        text = text[1:-1].strip()
    return _title_case(text) if text.isupper() else text


def _title_case(text: str) -> str:
    """ "THE PHILOSOPHER'S STONE" -> "The Philosopher's Stone" (str.title would give
    "Philosopher'S"); short words stay lowercase inside the title."""
    small = {"a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to"}
    words = text.lower().split(" ")
    return " ".join(w if i and w in small else w[:1].upper() + w[1:] for i, w in enumerate(words))


def _most_common(values: list[str | None]) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        if value and value.strip():
            counts[value.strip()] = counts.get(value.strip(), 0) + 1
    return max(counts, key=lambda v: counts[v]) if counts else None


def order(kind: str, items: list[SpokenFile]) -> list[SpokenFile]:
    """Audiobooks: disc / track when consistent, else the paths in natural order.
    Podcasts: newest first (date, then path)."""
    if kind == PODCAST:
        return sorted(items, key=lambda i: (i.date or "", natural_key(i.path)), reverse=True)
    if consistent_numbers([(i.disc, i.track) for i in items]):
        return sorted(items, key=lambda i: (i.disc or 1, i.track or 0, natural_key(i.path)))
    return sorted(items, key=lambda i: natural_key(i.path))


def propose(kind: str, folders: list[Path], items: list[SpokenFile]) -> SpokenMetadata:
    """What the review starts from."""
    main = folders[0]
    album = _most_common([i.album for i in items])
    title = clean_title(album or main.name) or clean_title(main.name) or main.name
    compilation = any(i.compilation for i in items)
    album_artist = _most_common([i.album_artist for i in items])
    artist = _most_common([i.artist for i in items])
    composer = _most_common([i.composer for i in items])
    if album_artist and album_artist.casefold() in VARIOUS:
        album_artist = None
    narrator = None
    if compilation and composer:
        # e.g. "Stephen Fry" as artist, "J.K. Rowling" as composer, flagged compilation.
        author, narrator = composer, artist
    else:
        author = album_artist or artist or composer or ""
        if kind == AUDIOBOOK and composer and composer != author:
            narrator = composer  # the usual audiobook tagging: composer = narrator
    if author.casefold() in VARIOUS:
        author = ""
    images = folder_images(folders)
    with_picture = next((i for i in items if i.has_picture), None)
    cover = (
        f"folder:{images[0]}"
        if images
        else f"embedded:{with_picture.path}"
        if with_picture
        else None
    )
    entries = [
        Entry(
            path=i.path,
            title=clean_chapter(i.title or Path(i.path).stem) or Path(i.path).stem,
            date=i.date if kind == PODCAST else None,
        )
        for i in order(kind, items)
    ]
    return SpokenMetadata(
        title=title,
        author=author,
        narrator=narrator if kind == AUDIOBOOK else None,
        year=min((i.year for i in items if i.year), default=None),
        genre="Podcast" if kind == PODCAST else "Audiobook",
        description=_most_common([i.comment for i in items]),
        cover=cover,
        entries=entries,
    )


def picture(cover: str) -> tuple[bytes, str] | None:
    """The image of a "folder:" / "embedded:" cover: (data, MIME type)."""
    source, _, value = cover.partition(":")
    path = Path(value)
    if source == "folder" and path.is_file():
        return path.read_bytes(), IMAGE_CONTENT_TYPES.get(suffix_of(path.name), "image/jpeg")
    if source == "embedded" and path.is_file():
        return extract_picture(path)
    return None


# --- 3. into the library -------------------------------------------------------------------


@dataclass
class Placed:
    folder: Path  # the book / show folder
    files: list[Path] = field(default_factory=list[Path])  # imported (their new place)
    skipped: list[str] = field(default_factory=list[str])  # episodes already there


def _existing_folder(parent: Path, name: str) -> Path | None:
    """The sub-folder of `parent` named `name`, ignoring case."""
    if not parent.is_dir():
        return None
    wanted = name.casefold()
    return next((c for c in parent.iterdir() if c.is_dir() and c.name.casefold() == wanted), None)


def target_folder(kind: str, metadata: SpokenMetadata, root: Path) -> Path:
    """`<Author>/<Title>` (audiobooks) or `<Show>` (podcasts), reusing existing folders
    whatever their case."""
    title = files.safe_component(metadata.title, "Untitled")
    if kind == PODCAST:
        return _existing_folder(root, title) or root / title
    author = files.safe_component(metadata.author, "Unknown Author")
    author_dir = _existing_folder(root, author) or root / author
    return _existing_folder(author_dir, title) or author_dir / title


def plan(kind: str, metadata: SpokenMetadata, root: Path) -> tuple[Path, list[tuple[Path, Path]]]:
    """The book / show folder and (source, destination) of each file. TaggerError when
    the review is incomplete or the book is already in the library."""
    if not metadata.title.strip():
        raise TaggerError("Give the title")
    if kind == AUDIOBOOK and not metadata.author.strip():
        raise TaggerError("Give the author")
    if not metadata.entries:
        raise TaggerError("No chapter to import")
    folder = target_folder(kind, metadata, root)
    if kind == AUDIOBOOK and folder.is_dir() and any(files.is_audio(c) for c in folder.iterdir()):
        raise TaggerError(
            f"This book is already in the library: {folder}. "
            "Change its title, delete that book first, or skip this one."
        )
    width = max(2, len(str(len(metadata.entries))))
    steps: list[tuple[Path, Path]] = []
    used: set[str] = set()
    for n, entry in enumerate(metadata.entries, 1):
        source = Path(entry.path)
        title = files.safe_component(entry.title, "Untitled")
        prefix = f"{n:0{width}d}" if kind == AUDIOBOOK else (entry.date or "0000-00-00")
        name = f"{prefix} - {title}"
        # Two episodes of the same day with the same title: "(2)".
        candidate, count = name, 1
        while candidate.casefold() in used:
            count += 1
            candidate = f"{name} ({count})"
        used.add(candidate.casefold())
        steps.append((source, folder / f"{candidate}{source.suffix.lower()}"))
    return folder, steps


def place(
    kind: str,
    metadata: SpokenMetadata,
    root: Path,
    *,
    move: bool,
    cover: tuple[bytes, str] | None,
) -> Placed:
    """Copies / moves the files into their folder under their new names, writes their
    tags and the cover. On a failure, what was copied goes again (moved files are put
    back)."""
    folder, steps = plan(kind, metadata, root)
    placed = Placed(folder)
    done: list[tuple[Path, Path]] = []
    folder.mkdir(parents=True, exist_ok=True)
    try:
        total = len(steps)
        for n, ((source, target), entry) in enumerate(zip(steps, metadata.entries, strict=True), 1):
            if target.exists():  # podcasts: an episode already imported
                placed.skipped.append(target.name)
                continue
            if move:
                shutil.move(source, target)
            else:
                shutil.copy2(source, target)
            done.append((source, target))
            _write_tags(kind, target, metadata, entry, n, total)
            placed.files.append(target)
        if cover is not None:
            data, mime = cover
            extension = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
            for old in folder.glob("cover.*"):
                old.unlink()
            (folder / f"cover.{extension}").write_bytes(data)
    except Exception:
        for source, target in done:
            if move:
                shutil.move(target, source)
            else:
                target.unlink(missing_ok=True)
        if not any(folder.iterdir()):
            folder.rmdir()
        raise
    if move:
        for source_dir in sorted(
            {Path(e.path).parent for e in metadata.entries}, key=lambda p: -len(p.parts)
        ):
            if source_dir.exists() and not any(files.is_audio(c) for c in source_dir.iterdir()):
                files.remove_emptied_folder(source_dir, source_dir.parent)
    return placed


def _write_tags(
    kind: str, path: Path, metadata: SpokenMetadata, entry: Entry, position: int, total: int
) -> None:
    import mediafile

    try:
        media: Any = mediafile.MediaFile(str(path))
        media.album = metadata.title
        media.albumartist = metadata.author or None
        media.artist = metadata.author or None
        media.composer = metadata.narrator or None
        media.title = entry.title
        media.comp = False
        media.disc = None
        media.disctotal = None
        media.genre = metadata.genre or None
        media.comments = metadata.description or None
        media.mb_albumid = metadata.musicbrainz_release_id
        media.mb_releasegroupid = metadata.musicbrainz_release_group_id
        if metadata.series:
            number = f", Book {metadata.series_number}" if metadata.series_number else ""
            media.grouping = f"{metadata.series}{number}"
        if kind == AUDIOBOOK:
            media.track, media.tracktotal = position, total
            media.year = metadata.year
            media.month = media.day = None
        else:
            media.track = media.tracktotal = None
            day = date.fromisoformat(entry.date) if entry.date else None
            if day:
                media.date = day
            else:
                media.year = metadata.year
        media.save()
    except (mediafile.UnreadableFileError, OSError, ValueError) as error:
        raise TaggerError(f"Cannot write the tags of {path.name}: {error}") from error
