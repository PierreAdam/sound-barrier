"""The beets tagger: MusicBrainz matching, beets path formats, cover art, tag writing.

beets is used as a library, never through its command line:
- `identify` / `search` call its matcher (`tag_album`) and turn the proposals into
  `Candidate`s for the review page;
- `apply` runs a real beets import session on the album, whose "user" is the decision
  already taken in the web UI (a candidate, or as-is). Everything beets does on import
  then happens as with `beet import`: tags written from MusicBrainz, files copied to the
  path formats, fetchart / embedart, the album added to beets' own database.

beets keeps global state (configuration, plugins): every call must come from the same
thread (the import manager's tagger thread).

Configuration: our defaults (below), then `<beets dir>/config.yaml` if it exists, then
what Sound-Barrier must control (library location, copy / move, no prompts).
"""

import logging
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from app.library_manager import tag_files
from app.library_manager.tag_files import TagChange
from app.library_manager.tagger import (
    Candidate,
    Identification,
    ImportMode,
    ImportOptions,
    ItemInfo,
    Penalty,
    Recommendation,
    Tagger,
    TaggerError,
    TaggerLibrary,
    TrackMatch,
)

logger = logging.getLogger(__name__)

# Same as the beets configuration used before Sound-Barrier.
DEFAULT_CONFIG: dict[str, Any] = {
    "plugins": ["musicbrainz", "fetchart", "embedart"],
    "paths": {
        "default": "$albumartist/$album%aunique{}/$track - $title",
        "singleton": "Single/$artist/$title",
        "comp": "Compilations/$album%aunique{}/$track - $artist - $title",
    },
}

# beets' distance penalties: label, and the fields compared (files' "likely" value,
# candidate's value) when they are plain values.
_ALBUM_PENALTIES: dict[str, tuple[str, str | None, str | None]] = {
    "album": ("Album title", "album", "album"),
    "artist": ("Album artist", "artist", "artist"),
    "year": ("Year", "year", "year"),
    "media": ("Media", "media", "media"),
    "mediums": ("Number of discs", "disctotal", "mediums"),
    "country": ("Country", "country", "country"),
    "label": ("Label", "label", "label"),
    "catalognum": ("Catalog number", "catalognum", "catalognum"),
    "albumdisambig": ("Disambiguation", "albumdisambig", "albumdisambig"),
    "album_id": ("MusicBrainz release id", "mb_albumid", "album_id"),
    "data_source": ("Metadata source", "data_source", "data_source"),
    "tracks": ("Tracks", None, None),
    "missing_tracks": ("Tracks missing from the folder", None, None),
    "unmatched_tracks": ("Files matching no track", None, None),
}
_TRACK_ISSUES = {
    "track_title": "title",
    "track_length": "duration",
    "track_index": "track number",
    "track_id": "recording id",
    "track_artist": "artist",
    "medium": "disc",
}

_RECOMMENDATIONS = {
    0: Recommendation.NONE,
    1: Recommendation.LOW,
    2: Recommendation.MEDIUM,
    3: Recommendation.STRONG,
}


def beets_available() -> bool:
    try:
        import beets  # noqa: F401  # pyright: ignore[reportUnusedImport]
    except ImportError:
        return False
    return True


class BeetsTagger(Tagger):
    name = "beets (MusicBrainz)"
    supports_matching = True

    def __init__(self, beets_dir: Path) -> None:
        self._dir = beets_dir
        self._configured = False
        self._lib: Any = None
        self._lib_root: Path | None = None

    # --- setup ----------------------------------------------------------------------

    def _configure(self) -> None:
        if self._configured:
            return
        from beets import config, plugins

        self._dir.mkdir(parents=True, exist_ok=True)
        # beets' own folder (relative paths, caches): ours, never the user's home.
        os.environ["BEETSDIR"] = str(self._dir)
        config.clear()
        config.read(user=False, defaults=True)
        config.set(DEFAULT_CONFIG)
        user_file = self._dir / "config.yaml"
        if user_file.is_file():
            config.set_file(str(user_file))
            logger.info("beets configuration read from %s", user_file)
        names = config["plugins"].as_str_seq()
        if "musicbrainz" not in names:
            config["plugins"] = [*names, "musicbrainz"]
        config["library"] = str(self._dir / "library.db")
        config["statefile"] = str(self._dir / "state.pickle")
        config["threaded"] = False
        config["import"].set(
            {
                # Decisions come from the web UI: nothing to resume or ask.
                "resume": False,
                "incremental": False,
                "quiet": True,
                "timid": False,
                "autotag": True,
                "singletons": False,
                "group_albums": False,
                "pretend": False,
                "log": None,
                "duplicate_action": "skip",
                "link": False,
                "hardlink": False,
                "reflink": False,
                "delete": False,
            }
        )
        plugins.load_plugins()
        loaded = sorted(p.name for p in plugins.find_plugins())
        logger.info("beets plugins: %s", ", ".join(loaded))
        self._configured = True

    def _library(self, root: Path) -> Any:
        """beets' database; its directory is the library folder (paths are built in it)."""
        from beets import config, context, library

        self._configure()
        if self._lib is None or root != self._lib_root:
            config["directory"] = str(root)
            self._lib = library.Library(config["library"].as_filename(), str(root))
            self._lib_root = root
        # beets stores paths relative to this directory, kept in a context variable:
        # set it in the calling thread too, or path queries match nothing.
        context.set_music_dir(self._lib.directory)
        return self._lib

    def _read(self, items: list[ItemInfo]) -> list[Any]:
        from beets.library import Item

        try:
            return [Item.from_path(item.path) for item in items]
        except Exception as error:  # beets' ReadError and friends
            raise TaggerError(f"Cannot read the files: {error}") from error

    # --- matching -------------------------------------------------------------------

    def identify(self, items: list[ItemInfo]) -> Identification:
        from beets.autotag.match import tag_album
        from beets.autotag.source import Source

        self._configure()
        beets_items = self._read(items)
        source = Source.from_items(beets_items)
        return self._identification(beets_items, tag_album(source), source.data)

    def search(
        self,
        items: list[ItemInfo],
        *,
        artist: str | None = None,
        album: str | None = None,
        release_id: str | None = None,
    ) -> Identification:
        from beets.autotag.match import tag_album
        from beets.autotag.source import Source

        self._configure()
        beets_items = self._read(items)
        source = Source.from_items(beets_items)
        if release_id and release_id.strip():
            # An id or a MusicBrainz URL (the plugin extracts the id).
            proposal = tag_album(source, search_ids=[release_id.strip()])
        else:
            # beets only uses the search terms when both are given.
            proposal = tag_album(
                source,
                search_artist=(artist or "").strip() or source.artist,
                search_name=(album or "").strip() or source.name,
            )
        return self._identification(beets_items, proposal, source.data)

    def _identification(
        self, beets_items: list[Any], proposal: Any, likelies: Any
    ) -> Identification:
        candidates = [_candidate(beets_items, match, likelies) for match in proposal.candidates]
        recommendation = _RECOMMENDATIONS.get(int(proposal.recommendation), Recommendation.NONE)
        if not candidates:
            recommendation = Recommendation.NONE
        return Identification(candidates, recommendation)

    # --- import ---------------------------------------------------------------------

    def apply(
        self,
        items: list[ItemInfo],
        candidate: Candidate | None,
        library_root: Path,
        options: ImportOptions,
    ) -> list[Path]:
        from beets import config
        from beets.importer.tasks import ImportTask

        lib = self._library(library_root)
        # In place (files already in the library): neither copied nor moved, only tagged.
        config["import"]["copy"] = options.mode is ImportMode.COPY
        config["import"]["move"] = options.mode is ImportMode.MOVE
        config["import"]["write"] = options.write_tags
        config["import"]["search_ids"] = [candidate.id] if candidate else []

        beets_items = self._read(items)
        folders = sorted({os.fsencode(Path(item.path).parent) for item in items})
        task = ImportTask(None, folders, beets_items)
        session = _make_session(lib, candidate.id if candidate else None)
        session.run_task(task)

        if session.duplicates:
            raise TaggerError(
                f"This album is already in beets' library: {', '.join(session.duplicates)}. "
                "Delete that album first, or skip this one."
            )
        if session.error:
            raise TaggerError(session.error)
        if task.skip:
            raise TaggerError("beets did not import this album")
        return [Path(os.fsdecode(item.path)) for item in task.imported_items()]

    def _item_paths(self, lib: Any, root: Path) -> list[tuple[Any, str]]:
        found: list[tuple[Any, str]] = []
        for item in lib.items():
            path = Path(os.fsdecode(item.path))
            try:
                found.append((item, path.relative_to(root).as_posix()))
            except ValueError:
                found.append((item, path.as_posix()))  # outside the library folder
        return found

    def library(self, library_root: Path) -> TaggerLibrary | None:
        if not (self._dir / "library.db").is_file():
            return TaggerLibrary(0, set(), [])
        lib = self._library(library_root)
        items = self._item_paths(lib, library_root)
        missing = [relative for item, relative in items if not os.path.exists(item.path)]
        return TaggerLibrary(len(lib.albums()), {relative for _, relative in items}, missing)

    def forget_missing(self, library_root: Path) -> int:
        if not (self._dir / "library.db").is_file():
            return 0
        lib = self._library(library_root)
        gone = [
            item for item, _ in self._item_paths(lib, library_root) if not os.path.exists(item.path)
        ]
        for item in gone:
            item.remove(delete=False, with_album=True)
        return len(gone)

    def _items_by_path(self, lib: Any, paths: list[Path]) -> dict[Path, Any]:
        from beets.dbcore.query import PathQuery

        found: dict[Path, Any] = {}
        for path in paths:
            for item in lib.items(PathQuery("path", os.fsencode(path))):
                found[path] = item
        return found

    def write_tags(self, changes: list[TagChange], library_root: Path) -> None:
        """Through beets for the files it knows (its database stays in sync), directly
        for the others."""
        if not (self._dir / "library.db").is_file():
            super().write_tags(changes, library_root)
            return
        lib = self._library(library_root)
        items = self._items_by_path(lib, [c.path for c in changes])
        albums: dict[int, Any] = {}
        for change in changes:
            item = items.get(change.path)
            if item is None:
                tag_files.write(change)
                continue
            fields = dict(change.fields)
            if "year" in fields:  # a new year: the old month and day no longer apply
                fields.update(month=0, day=0)
            if "genre" in fields:  # beets 2.14+: a list, "genres"
                genre = fields.pop("genre")
                fields["genres"] = [genre] if genre else []
            item.update(fields)
            try:
                item.write()
            except Exception as error:  # beets' ReadError / WriteError
                raise tag_files.TagWriteError(
                    f"Cannot write the tags of {change.path.name}: {error}"
                ) from error
            item.store()
            album = item.get_album()
            if album is not None:
                albums[album.id] = album
        # beets' album rows follow their (edited) items' album-level fields.
        album_fields = ("album", "albumartist", "year", "genres", "comp")
        for album in albums.values():
            first = next(iter(album.items()), None)
            if first is not None:
                for name in album_fields:
                    if name in first:
                        album[name] = first[name]
                album.store(inherit=False)

    def embed_cover(self, paths: list[Path], jpeg: bytes, library_root: Path) -> None:
        super().embed_cover(paths, jpeg, library_root)
        if not (self._dir / "library.db").is_file():
            return
        lib = self._library(library_root)
        for item in self._items_by_path(lib, paths).values():
            item.mtime = item.current_mtime()  # not "modified outside beets"
            item.store()

    def forget(self, paths: list[Path], library_root: Path) -> None:
        from beets.dbcore.query import PathQuery

        if not (self._dir / "library.db").is_file():
            return
        lib = self._library(library_root)
        for path in paths:
            for item in lib.items(PathQuery("path", os.fsencode(path))):
                item.remove(delete=False, with_album=True)


def _value(value: Any) -> str | None:
    return None if value in (None, "", 0) else str(value)


def _penalties(match: Any, likelies: Any, track_issues: list[list[str]]) -> list[Penalty]:
    """beets' distance, penalty by penalty (what `beet import` prints as "(media, year)")."""
    info = match.info
    penalties: list[Penalty] = []
    for key, share in match.distance.items():
        label, current_field, proposed_field = _ALBUM_PENALTIES.get(
            key, (key.replace("_", " ").capitalize(), None, None)
        )
        penalty = Penalty(key=key, label=label, share=round(float(share), 4))
        if current_field and proposed_field:
            penalty.current = _value(likelies.get(current_field))
            penalty.proposed = _value(getattr(info, proposed_field, None))
        if key == "tracks":
            differing = [issues for issues in track_issues if issues]
            kinds = sorted({issue for issues in differing for issue in issues})
            penalty.detail = f"{len(differing)} of {len(track_issues)}: {', '.join(kinds)}"
        elif key == "missing_tracks":
            penalty.detail = str(len(info.tracks) - len(match.mapping))
        elif key == "unmatched_tracks":
            penalty.detail = str(len(match.extra_items))
        penalties.append(penalty)
    return penalties


def _candidate(beets_items: list[Any], match: Any, likelies: Any) -> Candidate:
    info = match.info
    index_of = {id(item): index for index, item in enumerate(beets_items)}
    item_for_track = {id(track): item for item, track in match.mapping.items()}
    track_distances: dict[Any, Any] = getattr(match.distance, "tracks", {}) or {}
    tracks: list[TrackMatch] = []
    track_issues: list[list[str]] = []  # of the matched tracks
    for track in info.tracks:
        item = item_for_track.get(id(track))
        length = getattr(track, "length", None)
        issues: list[str] = []
        track_distance = track_distances.get(track)
        if item is not None and track_distance is not None:
            issues = [_TRACK_ISSUES.get(str(key), str(key)) for key, _ in track_distance.items()]
            track_issues.append(issues)
        tracks.append(
            TrackMatch(
                title=track.title or "",
                artist=getattr(track, "artist", None),
                track=getattr(track, "medium_index", None) or getattr(track, "index", None),
                disc=getattr(track, "medium", None),
                duration_ms=round(length * 1000) if length else None,
                item_index=index_of.get(id(item)) if item is not None else None,
                issues=issues,
            )
        )
    source = getattr(info, "data_source", None) or "MusicBrainz"
    release_id = info.album_id or ""
    url = getattr(info, "data_url", None)
    if not url and source.lower() == "musicbrainz" and release_id:
        url = f"https://musicbrainz.org/release/{release_id}"
    media = getattr(info, "media", None)
    mediums = getattr(info, "mediums", None)
    if media and mediums and mediums > 1:
        media = f"{mediums}x{media}"
    return Candidate(
        id=release_id,
        source=source.lower(),
        artist=info.artist or "",
        album=info.album or "",
        distance=round(float(match.distance), 4),
        year=getattr(info, "year", None) or None,
        label=getattr(info, "label", None) or None,
        country=getattr(info, "country", None) or None,
        media=media or None,
        catalog_number=getattr(info, "catalognum", None) or None,
        url=url,
        tracks=tracks,
        extra_items=[index_of[id(i)] for i in match.extra_items if id(i) in index_of],
        penalties=_penalties(match, likelies, track_issues),
    )


def _make_session(lib: Any, release_id: str | None) -> Any:
    """A beets import session answering with the decision taken in the web UI."""
    from beets import config, plugins
    from beets.importer import stages
    from beets.importer.actions import Action, DuplicateAction
    from beets.importer.session import ImportSession
    from beets.util import pipeline

    class Session(ImportSession):
        def __init__(self) -> None:
            super().__init__(lib, None, [])
            self.duplicates: list[str] = []
            self.error: str | None = None

        def should_resume(self, path: bytes) -> bool:
            return False

        def choose_match(self, task: Any) -> Any:
            if release_id is None:
                return Action.ASIS
            for match in task.candidates:
                if match.info.album_id == release_id:
                    return match
            self.error = "This release was not found again on MusicBrainz: search it again"
            return Action.SKIP

        def choose_item(self, task: Any) -> Any:
            return Action.SKIP

        def get_duplicate_action(self, task: Any, found_duplicates: list[Any]) -> Any:
            self.duplicates = [
                f"{getattr(d, 'albumartist', '')} - {getattr(d, 'album', '')}"
                for d in found_duplicates
            ]
            return DuplicateAction.SKIP

        def run_task(self, task: Any) -> None:
            """`ImportSession.run()` for one prepared task instead of folders to walk."""
            self.set_config(config["import"])
            task.candidates, task.rec = [], None
            coroutines: list[Any] = [_single(task)]
            if release_id is not None:  # as-is needs no lookup
                coroutines.append(stages.lookup_candidates(self))
            coroutines.append(stages.user_query(self))
            for stage in (*plugins.early_import_stages(), *plugins.import_stages()):
                coroutines.append(stages.plugin_stage(self, stage))
            coroutines.append(stages.manipulate_files(self))
            plugins.send("import_begin", session=self)
            pipeline.Pipeline(coroutines).run_sequential()

    return Session()


def _single(task: Any) -> Iterator[Any]:
    yield task
