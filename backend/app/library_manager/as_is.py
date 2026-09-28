"""A tagger without matching: imports albums with the tags they already have.

Used until beets is integrated, and as the "import as-is" choice. Files are placed like
the default beets path template: `<album artist>/<album>/<track> - <title>.<ext>`.
"""

import shutil
from pathlib import Path

from app.library_manager.files import is_audio, safe_component
from app.library_manager.tagger import (
    Candidate,
    Identification,
    ImportMode,
    ImportOptions,
    ItemInfo,
    Recommendation,
    Tagger,
    TaggerError,
)
from app.scanner.formats import IMAGE_CONTENT_TYPES, suffix_of


def _existing_folder(parent: Path, name: str) -> Path | None:
    """The sub-folder of `parent` named `name`, ignoring case (library disks are often
    case-sensitive: "ROCKISDEAD" and "Rockisdead" must be seen as the same album)."""
    if not parent.is_dir():
        return None
    wanted = name.casefold()
    return next((c for c in parent.iterdir() if c.is_dir() and c.name.casefold() == wanted), None)


def plan(items: list[ItemInfo], library_root: Path) -> list[tuple[Path, Path]]:
    """(source, destination) of each file, or TaggerError when the album is already in
    the library. Nothing is written: also usable as a dry run."""
    multi_disc = len({item.disc for item in items if item.disc}) > 1
    result: list[tuple[Path, Path]] = []
    album_dirs: set[Path] = set()
    for item in items:
        source = Path(item.path)
        artist = safe_component(item.album_artist or item.artist or "", "Unknown Artist")
        album = safe_component(item.album or source.parent.name, "Unknown Album")
        title = safe_component(item.title or source.stem, "Untitled")
        number = f"{item.track:02d} - " if item.track else ""
        if multi_disc and item.disc:
            number = f"{item.disc}-{number}"
        # An existing artist folder is reused whatever its case.
        artist_dir = _existing_folder(library_root, artist) or library_root / artist
        album_dir = _existing_folder(artist_dir, album) or artist_dir / album
        album_dirs.add(album_dir)
        result.append((source, album_dir / f"{number}{title}{source.suffix.lower()}"))

    targets = [target for _, target in result]
    if len(set(targets)) != len(targets):
        raise TaggerError("Several files would get the same name: check their tags")
    # Never mix an import into an existing album folder (duplicate, other edition...).
    for folder in album_dirs:
        if folder.is_dir() and any(is_audio(child) for child in folder.iterdir()):
            raise TaggerError(
                f"This album is already in the library: {folder}. "
                "Delete that album first, or skip this one."
            )
    return result


class AsIsTagger(Tagger):
    name = "Current tags (no matching)"
    supports_matching = False

    def identify(self, items: list[ItemInfo]) -> Identification:
        return Identification([], Recommendation.NONE)

    def search(
        self,
        items: list[ItemInfo],
        *,
        artist: str | None = None,
        album: str | None = None,
        release_id: str | None = None,
    ) -> Identification:
        return Identification([], Recommendation.NONE)

    def apply(
        self,
        items: list[ItemInfo],
        candidate: Candidate | None,
        library_root: Path,
        options: ImportOptions,
    ) -> list[Path]:
        if candidate is not None:
            raise TaggerError("This tagger can only import albums as they are")
        if options.mode is ImportMode.IN_PLACE:
            return [Path(item.path) for item in items]  # no database of its own to fill
        steps = plan(items, library_root)

        transfer = shutil.copy2 if options.mode is ImportMode.COPY else shutil.move
        done: list[Path] = []
        for source, target in steps:
            target.parent.mkdir(parents=True, exist_ok=True)
            transfer(source, target)
            done.append(target)

        # Folder images come along (cover.jpg...).
        album_dir = steps[0][1].parent
        for source_dir in {Path(item.path).parent for item in items}:
            for extra in source_dir.iterdir():
                if extra.is_file() and suffix_of(extra.name) in IMAGE_CONTENT_TYPES:
                    target = album_dir / extra.name
                    if not target.exists():
                        transfer(extra, target)
        return done
