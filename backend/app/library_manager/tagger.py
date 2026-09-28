"""The tagger abstraction: everything the import workflow needs from a tagging engine.

The workflow (jobs, review, API, UI) only talks to `Tagger`. Implementations:
- `AsIsTagger` (as_is.py): no matching, imports albums with their current tags;
- a beets-based tagger (MusicBrainz matching, path templates, cover art), next.

Methods are synchronous (beets is): the job runner calls them in a worker thread, one at
a time.
"""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.library_manager import tag_files
from app.library_manager.tag_files import TagChange


class Recommendation(StrEnum):
    """How confident the tagger is in its best candidate."""

    STRONG = "strong"  # applied automatically when auto-apply is on
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"  # no candidate


class ImportMode(StrEnum):
    COPY = "copy"  # sources stay in the import folder
    MOVE = "move"
    IN_PLACE = "in_place"  # files already in the library: tagged where they are


@dataclass
class ItemInfo:
    """One audio file of the album being imported, with its current tags."""

    path: str  # absolute
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track: int | None = None
    disc: int | None = None
    year: int | None = None
    duration_ms: int | None = None

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ItemInfo":
        return cls(**data)


@dataclass
class TrackMatch:
    """A track of a candidate release, and which item it was matched to."""

    title: str
    artist: str | None = None
    track: int | None = None
    disc: int | None = None
    duration_ms: int | None = None
    item_index: int | None = None  # index in the task's items, None = missing
    # What differs between the file and this track (e.g. "duration", "title").
    issues: list[str] = field(default_factory=list[str])


@dataclass
class Penalty:
    """One reason why a candidate is not a 100 % match."""

    key: str  # the tagger's name for it (e.g. beets' "media")
    label: str  # for people: "Media"
    share: float  # of the match lost (0.05: the match is 5 points lower)
    current: str | None = None  # the files' value
    proposed: str | None = None  # the candidate's value
    detail: str | None = None  # e.g. "3 tracks: duration"


@dataclass
class Candidate:
    """A release the album may be (e.g. a MusicBrainz release)."""

    id: str  # opaque to the workflow, understood by the tagger (e.g. MB release id)
    source: str  # e.g. "musicbrainz"
    artist: str
    album: str
    distance: float  # 0 = perfect match, 1 = unrelated
    year: int | None = None
    label: str | None = None
    country: str | None = None
    media: str | None = None
    catalog_number: str | None = None
    url: str | None = None
    tracks: list[TrackMatch] = field(default_factory=list[TrackMatch])
    extra_items: list[int] = field(default_factory=list[int])  # items matching no track
    penalties: list[Penalty] = field(default_factory=list[Penalty])  # biggest first

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Candidate":
        values: dict[str, Any] = dict(data)
        values["tracks"] = [TrackMatch(**t) for t in data.get("tracks", [])]
        values["penalties"] = [Penalty(**p) for p in data.get("penalties", [])]
        return cls(**values)


@dataclass
class Identification:
    candidates: list[Candidate]  # best first
    recommendation: Recommendation


@dataclass
class ImportOptions:
    mode: ImportMode = ImportMode.COPY
    write_tags: bool = True


@dataclass
class TaggerLibrary:
    """What the tagger's own database knows about the library."""

    albums: int
    paths: set[str]  # relative to the library folder, "/" separated
    missing: list[str]  # of those, the files no longer on disk


class TaggerError(Exception):
    """An import problem to show to the admin (e.g. files already in the library)."""


class Tagger(ABC):
    #: Shown in the UI.
    name: str
    #: False when the tagger cannot look albums up (only "import as-is" is possible).
    supports_matching: bool

    @abstractmethod
    def identify(self, items: list[ItemInfo]) -> Identification:
        """Candidates for an album, from its files and current tags."""

    @abstractmethod
    def search(
        self,
        items: list[ItemInfo],
        *,
        artist: str | None = None,
        album: str | None = None,
        release_id: str | None = None,
    ) -> Identification:
        """Candidates for a manual search (artist + album, or a release id / URL)."""

    @abstractmethod
    def apply(
        self,
        items: list[ItemInfo],
        candidate: Candidate | None,
        library_root: Path,
        options: ImportOptions,
    ) -> list[Path]:
        """Imports the album into `library_root`, tagged from `candidate` (None: current
        tags, "as-is"). Returns the paths of the imported files."""

    def library(self, library_root: Path) -> TaggerLibrary | None:
        """The tagger's own database (None: it has none, e.g. no beets)."""
        return None

    def write_tags(self, changes: list[TagChange], library_root: Path) -> None:
        """Writes tag changes into files of the library (tag editor)."""
        for change in changes:
            tag_files.write(change)

    def embed_cover(self, paths: list[Path], jpeg: bytes, library_root: Path) -> None:
        """Embeds this front cover into files of the library."""
        for path in paths:
            tag_files.embed_picture(path, jpeg)

    def forget_missing(self, library_root: Path) -> int:
        """Removes the entries whose file is gone from the tagger's database."""
        return 0

    def forget(self, paths: list[Path], library_root: Path) -> None:  # noqa: B027
        """Optional hook, called after files of the library in `library_root` were deleted
        (e.g. to update beets' own database)."""
