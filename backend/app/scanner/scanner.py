"""Library scanner: syncs the library tables with the files of every music folder.

- Quick scan (default): only files whose size or mtime changed are re-read.
- Full scan: every file is re-read.
- Files that disappear are soft-deleted (`missing_since`), never deleted, so user data
  survives. A music folder that cannot be accessed is skipped entirely.
- Derived data (album counters and artwork, album genres, missing albums / artists) is
  recomputed with SQL at the end of every scan, so it is always consistent.
- A Postgres advisory lock ensures only one scan runs at a time, across processes.
"""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Boolean, delete, func, literal_column, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import Database
from app.core.text import normalize, strip_articles
from app.models import (
    Album,
    AlbumArtist,
    Artist,
    Artwork,
    Directory,
    Genre,
    MusicFolder,
    Scan,
    Song,
    SongArtist,
    SongGenre,
)
from app.scanner.formats import AUDIO_CONTENT_TYPES, COVER_FILE_NAMES, suffix_of
from app.scanner.tags import AudioFile, read_audio_file
from app.scanner.walker import DirectoryEntry, FileEntry, ancestors, is_within, walk, walk_targets

logger = logging.getLogger(__name__)

SCAN_LOCK_KEY = 0x53424152  # "SBAR": identifies the scan advisory lock
CHUNK_SIZE = 100  # files read and written per transaction
DEFAULT_WORKERS = 4  # tag-reading threads (see Settings.scan_workers)

UNKNOWN_ARTIST = "[Unknown Artist]"
UNKNOWN_ALBUM = "[Unknown Album]"
VARIOUS_ARTISTS = "Various Artists"


class ScanAlreadyRunningError(Exception):
    pass


@dataclass
class ScanStats:
    """Totals and progress, stored in the `scan` row (see models.system.Scan)."""

    phase: str = "starting"  # starting, walking, reading, finishing, done, failed
    files_seen: int = 0
    files_to_read: int = 0
    files_read: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0


async def run_scan(
    db: Database,
    *,
    full: bool = False,
    workers: int = DEFAULT_WORKERS,
    targets: dict[int, list[str]] | None = None,
) -> int:
    """Scans every music folder, or only `targets`: {music folder id: sub-directories
    relative to it} (e.g. an album just imported or deleted). Returns the `scan` row id."""
    async with db.engine.connect() as lock_connection:
        locked = await lock_connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": SCAN_LOCK_KEY}
        )
        if not locked:
            raise ScanAlreadyRunningError
        try:
            return await _ScanRun(db, full=full, workers=workers, targets=targets).run()
        finally:
            await lock_connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": SCAN_LOCK_KEY}
            )


def _now() -> datetime:
    return datetime.now(UTC)


def _pick_cover(images: list[FileEntry]) -> FileEntry | None:
    by_stem = {Path(image.path).stem.casefold(): image for image in images}
    for name in COVER_FILE_NAMES:
        if name in by_stem:
            return by_stem[name]
    return None


class _Scope:
    """What a targeted scan is responsible for: the target trees, and the parents of the
    targets (listed without their other sub-directories)."""

    def __init__(self, targets: list[str]) -> None:
        self.targets = targets
        self.parents = {p for t in targets for p in ancestors(t)}

    def has_directory(self, path: str) -> bool:
        if path in self.parents:
            return path != ""  # the music folder itself never goes missing
        return any(is_within(path, t) for t in self.targets)

    def has_song(self, path: str) -> bool:
        return path.rpartition("/")[0] in self.parents or any(
            is_within(path, t) for t in self.targets
        )


@dataclass
class _FolderState:
    """What the database knows about one music folder before the scan."""

    # path -> (id, size, mtime, missing_since)
    songs: dict[str, tuple[uuid.UUID, int, datetime, datetime | None]]
    directories: dict[str, uuid.UUID]  # path -> id
    seen_songs: set[uuid.UUID] = field(default_factory=set[uuid.UUID])
    seen_directories: set[uuid.UUID] = field(default_factory=set[uuid.UUID])
    seen_file_artwork: set[uuid.UUID] = field(default_factory=set[uuid.UUID])
    scope: _Scope | None = None  # targeted scan: only these paths can go missing


class _ScanRun:
    def __init__(
        self,
        db: Database,
        *,
        full: bool,
        workers: int,
        targets: dict[int, list[str]] | None = None,
    ) -> None:
        self.db = db
        self.full = full
        # A target "" is the whole folder: a normal scan of that folder.
        self.targets = targets
        self.kind = "full" if full else "targeted" if targets else "quick"
        self.workers = max(1, workers)
        self.stats = ScanStats()
        self.scan_id = 0
        # Caches of rows already written during this scan (match key -> id).
        self.artists: dict[str, uuid.UUID] = {}
        self.albums: dict[str, uuid.UUID] = {}
        self.genres: dict[str, uuid.UUID] = {}  # casefolded name -> id
        self.disc_titles: dict[uuid.UUID, dict[int, str]] = {}
        self.dirty_disc_titles: set[uuid.UUID] = set()

    async def run(self) -> int:
        async with self.db.session() as session:
            # We hold the lock, so any scan still marked as running was interrupted.
            await session.execute(
                update(Scan)
                .where(Scan.status == "running")
                .values(status="failed", error="interrupted", finished_at=_now())
            )
            scan = Scan(kind=self.kind, status="running")
            session.add(scan)
            await session.commit()
            self.scan_id = scan.id
            query = select(MusicFolder).order_by(MusicFolder.id)
            if self.targets is not None:
                query = query.where(MusicFolder.id.in_(self.targets))
            folders = (await session.scalars(query)).all()

        logger.info("Scan %s started (%s)", self.scan_id, self.kind)
        try:
            with ThreadPoolExecutor(self.workers, thread_name_prefix="tags") as executor:
                for folder in folders:
                    await self._scan_folder(folder, executor)
            self.stats.phase = "finishing"
            async with self.db.session() as session:
                await self._save_progress(session)
                await session.commit()
                await refresh_derived_data(session)
                await session.commit()
        except Exception as error:
            await self._finish("failed", error=str(error))
            raise
        await self._finish("done")
        logger.info("Scan %s finished: %s", self.scan_id, self.stats)
        return self.scan_id

    async def _finish(self, status: str, error: str | None = None) -> None:
        self.stats.phase = status
        async with self.db.session() as session:
            await session.execute(
                update(Scan)
                .where(Scan.id == self.scan_id)
                .values(status=status, error=error, finished_at=_now(), **vars(self.stats))
            )
            await session.commit()

    async def _save_progress(self, session: AsyncSession) -> None:
        await session.execute(
            update(Scan).where(Scan.id == self.scan_id).values(**vars(self.stats))
        )

    # --- per folder -------------------------------------------------------

    async def _scan_folder(self, folder: MusicFolder, executor: ThreadPoolExecutor) -> None:
        root = Path(folder.path)
        if not await asyncio.to_thread(root.is_dir):
            logger.warning("Music folder %s (%s) is not accessible, skipped", folder.name, root)
            return
        self.stats.phase = "walking"
        async with self.db.session() as session:
            await self._save_progress(session)
            await session.commit()
        targets = self._folder_targets(folder)
        if targets is None:
            entries = await asyncio.to_thread(walk, root)
        else:
            entries = await asyncio.to_thread(walk_targets, root, targets)

        async with self.db.session() as session:
            state = await self._load_state(session, folder)
            state.scope = _Scope(targets) if targets is not None else None
            present = sum(1 for _, _, _, missing in state.songs.values() if missing is None)
            if targets is None and present and not any(e.audio_files for e in entries):
                # A folder with songs that suddenly looks empty is far more likely an
                # unmounted / not-yet-ready drive than a deleted library: keep everything.
                logger.warning(
                    "Music folder %s (%s) has no audio files anymore (%s known songs): "
                    "skipped. Is the drive mounted?",
                    folder.name,
                    root,
                    present,
                )
                return
            directory_ids = await self._write_directories(session, folder, entries, state)
            to_read = self._select_files(entries, state)
            await self._mark_unchanged_present(session, state)
            self.stats.phase = "reading"
            self.stats.files_to_read += len(to_read)
            await self._save_progress(session)
            await session.commit()
        logger.info(
            "Folder %s: %s directories, %s audio files, %s to read",
            folder.name,
            len(entries),
            sum(len(e.audio_files) for e in entries),
            len(to_read),
        )

        loop = asyncio.get_running_loop()
        for start in range(0, len(to_read), CHUNK_SIZE):
            if start:
                logger.info("Folder %s: %s / %s files read", folder.name, start, len(to_read))
            chunk = to_read[start : start + CHUNK_SIZE]
            results = await asyncio.gather(
                *(
                    loop.run_in_executor(executor, read_audio_file, root / file.path)
                    for _, file in chunk
                )
            )
            async with self.db.session() as session:
                for (directory, file), audio in zip(chunk, results, strict=True):
                    if audio is None:
                        continue
                    song_id = await self._write_song(
                        session, folder, directory_ids[directory.path], directory, file, audio
                    )
                    state.seen_songs.add(song_id)
                await self._write_disc_titles(session)
                self.stats.files_read += len(chunk)
                await self._save_progress(session)
                await session.commit()

        async with self.db.session() as session:
            await self._mark_missing(session, folder, state)
            await self._save_progress(session)
            await session.commit()

    def _folder_targets(self, folder: MusicFolder) -> list[str] | None:
        """Sub-directories to scan in `folder`, None for the whole folder."""
        if self.targets is None:
            return None
        targets = [t.strip("/") for t in self.targets.get(folder.id, [])]
        return None if not targets or "" in targets else targets

    async def _load_state(self, session: AsyncSession, folder: MusicFolder) -> _FolderState:
        songs = await session.execute(
            select(Song.id, Song.path, Song.size, Song.file_mtime, Song.missing_since).where(
                Song.music_folder_id == folder.id
            )
        )
        directories = await session.execute(
            select(Directory.id, Directory.path).where(Directory.music_folder_id == folder.id)
        )
        return _FolderState(
            songs={path: (id_, size, mtime, missing) for id_, path, size, mtime, missing in songs},
            directories={path: id_ for id_, path in directories},
        )

    def _select_files(
        self, entries: list[DirectoryEntry], state: _FolderState
    ) -> list[tuple[DirectoryEntry, FileEntry]]:
        """Files to (re-)read. Unchanged files are only marked as seen."""
        to_read: list[tuple[DirectoryEntry, FileEntry]] = []
        for directory in entries:
            for file in directory.audio_files:
                self.stats.files_seen += 1
                known = state.songs.get(file.path)
                if known and not self.full and known[1:3] == (file.size, file.mtime):
                    state.seen_songs.add(known[0])
                else:
                    to_read.append((directory, file))
        return to_read

    async def _mark_unchanged_present(self, session: AsyncSession, state: _FolderState) -> None:
        for ids in _batches(list(state.seen_songs)):
            await session.execute(
                update(Song)
                .where(Song.id.in_(ids), Song.missing_since.is_not(None))
                .values(missing_since=None)
            )

    async def _mark_missing(
        self, session: AsyncSession, folder: MusicFolder, state: _FolderState
    ) -> None:
        now = _now()
        scope = state.scope
        gone_songs = [
            id_
            for path, (id_, *_) in state.songs.items()
            if id_ not in state.seen_songs and (scope is None or scope.has_song(path))
        ]
        for ids in _batches(gone_songs):
            result = await session.execute(
                update(Song)
                .where(Song.id.in_(ids), Song.missing_since.is_(None))
                .values(missing_since=now)
                .returning(Song.id)
            )
            self.stats.removed += len(result.all())
        gone_directories = [
            id_
            for path, id_ in state.directories.items()
            if id_ not in state.seen_directories and (scope is None or scope.has_directory(path))
        ]
        for ids in _batches(gone_directories):
            await session.execute(
                update(Directory)
                .where(Directory.id.in_(ids), Directory.missing_since.is_(None))
                .values(missing_since=now)
            )
        # Folder images that no longer exist. References are set to NULL by the FKs.
        # A targeted scan only knows the images of its target directories.
        in_scope = (
            []
            if scope is None
            else [or_(*(Artwork.path.startswith(f"{t}/") for t in scope.targets))]
        )
        await session.execute(
            delete(Artwork).where(
                Artwork.music_folder_id == folder.id,
                Artwork.source == "file",
                Artwork.id.not_in(state.seen_file_artwork),
                *in_scope,
            )
        )
        # Embedded pictures of songs that no longer have one.
        await session.execute(
            delete(Artwork).where(
                Artwork.music_folder_id == folder.id,
                Artwork.source == "embedded",
                ~select(Song.id).where(Song.artwork_id == Artwork.id).exists(),
                ~select(Album.id).where(Album.artwork_id == Artwork.id).exists(),
            )
        )

    # --- directories and artwork -----------------------------------------

    async def _write_directories(
        self,
        session: AsyncSession,
        folder: MusicFolder,
        entries: list[DirectoryEntry],
        state: _FolderState,
    ) -> dict[str, uuid.UUID]:
        ids: dict[str, uuid.UUID] = {}
        for entry in entries:  # parents come before children
            cover = _pick_cover(entry.image_files)
            artwork_id = None
            if cover is not None:
                artwork_id = await self._upsert_artwork(session, folder, "file", cover)
                state.seen_file_artwork.add(artwork_id)
            parent = entry.parent_path
            statement = insert(Directory).values(
                music_folder_id=folder.id,
                parent_id=ids[parent] if parent is not None else None,
                path=entry.path,
                name=entry.name or folder.name,
                artwork_id=artwork_id,
                mtime=entry.mtime,
                missing_since=None,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[Directory.music_folder_id, Directory.path],
                set_={
                    "parent_id": statement.excluded.parent_id,
                    "name": statement.excluded.name,
                    "artwork_id": statement.excluded.artwork_id,
                    "mtime": statement.excluded.mtime,
                    "missing_since": None,
                    "updated_at": text("now()"),
                },
            ).returning(Directory.id)
            directory_id = (await session.execute(statement)).scalar_one()
            ids[entry.path] = directory_id
            state.seen_directories.add(directory_id)
        return ids

    async def _upsert_artwork(
        self, session: AsyncSession, folder: MusicFolder, source: str, file: FileEntry
    ) -> uuid.UUID:
        statement = insert(Artwork).values(
            music_folder_id=folder.id, source=source, path=file.path, mtime=file.mtime
        )
        statement = statement.on_conflict_do_update(
            index_elements=[Artwork.music_folder_id, Artwork.source, Artwork.path],
            set_={"mtime": statement.excluded.mtime},
        ).returning(Artwork.id)
        return (await session.execute(statement)).scalar_one()

    # --- songs, albums, artists, genres -----------------------------------

    async def _write_song(
        self,
        session: AsyncSession,
        folder: MusicFolder,
        directory_id: uuid.UUID,
        directory: DirectoryEntry,
        file: FileEntry,
        audio: AudioFile,
    ) -> uuid.UUID:
        tags, info = audio.tags, audio.info
        title = tags.title or Path(file.path).stem

        artist_names = tags.artists or [UNKNOWN_ARTIST]
        artist_ids = [
            await self._artist(
                session,
                name,
                _aligned(tags.artist_mbz_ids, i, len(artist_names)),
                tags.artist_sort if len(artist_names) == 1 else None,
            )
            for i, name in enumerate(artist_names)
        ]

        if tags.album_artists:
            album_artist_names, album_artist_mbz_ids = tags.album_artists, tags.album_artist_mbz_ids
        elif tags.compilation:
            album_artist_names, album_artist_mbz_ids = [VARIOUS_ARTISTS], []
        else:
            album_artist_names, album_artist_mbz_ids = artist_names, tags.artist_mbz_ids
        album_artist_ids = [
            await self._artist(
                session,
                name,
                _aligned(album_artist_mbz_ids, i, len(album_artist_names)),
                tags.album_artist_sort if len(album_artist_names) == 1 else None,
            )
            for i, name in enumerate(album_artist_names)
        ]
        display_album_artist = tags.display_album_artist or " • ".join(album_artist_names)

        album_id = await self._album(
            session, audio, directory, album_artist_ids, display_album_artist
        )
        if tags.disc_number and tags.disc_subtitle:
            titles = self.disc_titles.setdefault(album_id, {})
            if titles.get(tags.disc_number) != tags.disc_subtitle:
                titles[tags.disc_number] = tags.disc_subtitle
                self.dirty_disc_titles.add(album_id)

        artwork_id = None
        if tags.has_picture:
            artwork_id = await self._upsert_artwork(session, folder, "embedded", file)

        suffix = suffix_of(file.path)
        values: dict[str, Any] = {
            "music_folder_id": folder.id,
            "directory_id": directory_id,
            "album_id": album_id,
            "artist_id": artist_ids[0],
            "path": file.path,
            "title": title,
            "sort_title": strip_articles(tags.title_sort or title),
            "title_search": normalize(title),
            "display_artist": tags.display_artist or " • ".join(artist_names),
            "display_composer": " • ".join(tags.composers) or None,
            "track_number": tags.track_number,
            "disc_number": tags.disc_number,
            "year": tags.year,
            "duration_ms": info.duration_ms,
            "bit_rate": info.bit_rate,
            "sample_rate": info.sample_rate,
            "bit_depth": info.bit_depth,
            "channels": info.channels,
            "size": file.size,
            "suffix": suffix,
            "content_type": AUDIO_CONTENT_TYPES.get(suffix, "application/octet-stream"),
            "bpm": tags.bpm,
            "comment": tags.comment,
            "explicit_status": tags.explicit_status,
            "replaygain_track_gain": tags.replaygain_track_gain,
            "replaygain_track_peak": tags.replaygain_track_peak,
            "replaygain_album_gain": tags.replaygain_album_gain,
            "replaygain_album_peak": tags.replaygain_album_peak,
            "mbz_recording_id": tags.mbz_recording_id,
            "mbz_track_id": tags.mbz_track_id,
            "artwork_id": artwork_id,
            "file_mtime": file.mtime,
            "missing_since": None,
        }
        statement = insert(Song).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[Song.music_folder_id, Song.path],
            set_={**{k: statement.excluded[k] for k in values}, "updated_at": text("now()")},
        ).returning(Song.id, literal_column("xmax = 0", Boolean).label("inserted"))
        song_id, inserted = (await session.execute(statement)).one()
        if inserted:
            self.stats.added += 1
        else:
            self.stats.updated += 1

        # Artists by role (OpenSubsonic `artists`, `albumArtists`, `contributors`).
        roles: list[tuple[uuid.UUID, str, str]] = [(a, "artist", "") for a in artist_ids]
        roles += [(a, "albumartist", "") for a in album_artist_ids]
        for contributor in tags.contributors:
            contributor_id = await self._artist(session, contributor.name, None, None)
            roles.append((contributor_id, contributor.role, contributor.sub_role))
        await session.execute(delete(SongArtist).where(SongArtist.song_id == song_id))
        rows = [
            {"song_id": song_id, "artist_id": a, "role": r, "sub_role": s, "position": i}
            for i, (a, r, s) in enumerate(dict.fromkeys(roles))
        ]
        await session.execute(insert(SongArtist), rows)

        await session.execute(delete(SongGenre).where(SongGenre.song_id == song_id))
        genre_ids = list(dict.fromkeys([await self._genre(session, g) for g in tags.genres]))
        if genre_ids:
            await session.execute(
                insert(SongGenre),
                [
                    {"song_id": song_id, "genre_id": g, "position": i}
                    for i, g in enumerate(genre_ids)
                ],
            )
        return song_id

    async def _artist(
        self, session: AsyncSession, name: str, mbz_id: str | None, sort_name: str | None
    ) -> uuid.UUID:
        normalized = normalize(name)
        key = f"mbz:{mbz_id}" if mbz_id else f"name:{normalized}"
        if key in self.artists:
            return self.artists[key]
        if not mbz_id:
            # Same name as an artist identified by MusicBrainz: most likely the same artist.
            existing = await session.scalar(
                select(Artist.id)
                .where(Artist.name_search == normalized, Artist.match_key.startswith("mbz:"))
                .limit(1)
            )
            if existing is not None:
                self.artists[key] = existing
                return existing

        values = {
            "match_key": key,
            "name": name,
            "sort_name": sort_name or strip_articles(name),
            "name_search": normalized,
            "mbz_artist_id": mbz_id,
        }
        statement = insert(Artist).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[Artist.match_key],
            set_={
                **{k: statement.excluded[k] for k in values if k != "match_key"},
                "updated_at": text("now()"),
            },
        ).returning(Artist.id)
        artist_id = (await session.execute(statement)).scalar_one()
        self.artists[key] = artist_id
        return artist_id

    async def _album(
        self,
        session: AsyncSession,
        audio: AudioFile,
        directory: DirectoryEntry,
        album_artist_ids: list[uuid.UUID],
        display_artist: str,
    ) -> uuid.UUID:
        tags = audio.tags
        name = tags.album or directory.name or UNKNOWN_ALBUM
        if tags.mbz_album_id:
            key = f"mbz:{tags.mbz_album_id}"
        else:
            key = f"{normalize(display_artist)}|{normalize(name)}"
        if key in self.albums:
            return self.albums[key]

        values: dict[str, Any] = {
            "match_key": key,
            "name": name,
            "sort_name": strip_articles(tags.album_sort or name),
            "name_search": normalize(name),
            "artist_id": album_artist_ids[0],
            "display_artist": display_artist,
            "year": tags.year,
            "release_date": tags.release_date or tags.date,
            "original_release_date": tags.original_date,
            "is_compilation": tags.compilation,
            "release_types": tags.release_types,
            "record_labels": tags.labels,
            "moods": tags.moods,
            "explicit_status": tags.explicit_status,
            "mbz_album_id": tags.mbz_album_id,
            "mbz_release_group_id": tags.mbz_release_group_id,
        }
        statement = insert(Album).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[Album.match_key],
            set_={
                **{k: statement.excluded[k] for k in values if k != "match_key"},
                "updated_at": text("now()"),
            },
        ).returning(Album.id, Album.disc_titles)
        album_id, disc_titles = (await session.execute(statement)).one()
        self.albums[key] = album_id
        self.disc_titles[album_id] = {int(d["disc"]): str(d["title"]) for d in disc_titles}

        await session.execute(delete(AlbumArtist).where(AlbumArtist.album_id == album_id))
        await session.execute(
            insert(AlbumArtist),
            [
                {"album_id": album_id, "artist_id": a, "role": "albumartist", "position": i}
                for i, a in enumerate(dict.fromkeys(album_artist_ids))
            ],
        )
        return album_id

    async def _genre(self, session: AsyncSession, name: str) -> uuid.UUID:
        key = name.casefold()
        if key in self.genres:
            return self.genres[key]
        genre_id = await session.scalar(
            select(Genre.id).where(func.lower(Genre.name) == name.lower()).limit(1)
        )
        if genre_id is None:
            statement = insert(Genre).values(name=name)
            statement = statement.on_conflict_do_update(
                index_elements=[Genre.name], set_={"name": statement.excluded.name}
            ).returning(Genre.id)
            genre_id = (await session.execute(statement)).scalar_one()
        self.genres[key] = genre_id
        return genre_id

    async def _write_disc_titles(self, session: AsyncSession) -> None:
        for album_id in self.dirty_disc_titles:
            titles = [
                {"disc": disc, "title": title}
                for disc, title in sorted(self.disc_titles[album_id].items())
            ]
            await session.execute(
                update(Album).where(Album.id == album_id).values(disc_titles=titles)
            )
        self.dirty_disc_titles.clear()


def _aligned(values: list[str], index: int, count: int) -> str | None:
    """MusicBrainz ids are only trusted when they line up one-to-one with the names."""
    return values[index] if len(values) == count else None


def _batches(ids: Sequence[uuid.UUID], size: int = 5000) -> list[Sequence[uuid.UUID]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


_TRACK_ORDER = "s.disc_number NULLS FIRST, s.track_number NULLS FIRST, s.path"

_DERIVED_DATA_SQL = [
    # Album counters; albums without any present song are missing. "Added" (created_at,
    # the Subsonic `created` date, "newest" lists) goes back to the date of its oldest
    # file (when it was written into the library, not when this server first scanned it)
    # but never forward: re-tagging files (beets) must not make an album look new.
    """
    UPDATE album a SET
        song_count = c.songs,
        duration_ms = c.duration,
        created_at = least(a.created_at, coalesce(c.first_file, a.created_at)),
        missing_since = CASE WHEN c.songs = 0 THEN coalesce(a.missing_since, now()) END
    FROM (
        SELECT al.id, count(s.id) AS songs, coalesce(sum(s.duration_ms), 0) AS duration,
               min(s.file_mtime) AS first_file
        FROM album al
        LEFT JOIN song s ON s.album_id = al.id AND s.missing_since IS NULL
        GROUP BY al.id
    ) c
    WHERE c.id = a.id
    """,
    # Album cover: folder image of its first track, else the first embedded picture.
    f"""
    UPDATE album a SET artwork_id = (
        SELECT coalesce(fa.id, s.artwork_id)
        FROM song s
        JOIN directory d ON d.id = s.directory_id
        LEFT JOIN artwork fa ON fa.id = d.artwork_id AND fa.source = 'file'
        WHERE s.album_id = a.id AND s.missing_since IS NULL
          AND coalesce(fa.id, s.artwork_id) IS NOT NULL
        ORDER BY {_TRACK_ORDER}
        LIMIT 1
    )
    """,
    # Directories without a folder image show the first embedded picture they contain.
    f"""
    UPDATE directory d SET artwork_id = (
        SELECT s.artwork_id FROM song s
        WHERE s.directory_id = d.id AND s.missing_since IS NULL AND s.artwork_id IS NOT NULL
        ORDER BY {_TRACK_ORDER}
        LIMIT 1
    )
    WHERE d.artwork_id IS NULL
    """,
    # Album genres: genres of its present songs, most frequent first.
    "DELETE FROM album_genre",
    """
    INSERT INTO album_genre (album_id, genre_id, position)
    SELECT s.album_id, sg.genre_id,
           row_number() OVER (
               PARTITION BY s.album_id ORDER BY count(*) DESC, min(sg.position)
           ) - 1
    FROM song_genre sg
    JOIN song s ON s.id = sg.song_id AND s.missing_since IS NULL
    GROUP BY s.album_id, sg.genre_id
    """,
    # Artist album counts; artists with neither albums nor songs are missing.
    """
    UPDATE artist ar SET
        album_count = c.albums,
        missing_since = CASE
            WHEN c.albums = 0 AND NOT EXISTS (
                SELECT 1 FROM song_artist sa
                JOIN song s ON s.id = sa.song_id AND s.missing_since IS NULL
                WHERE sa.artist_id = ar.id
            ) THEN coalesce(ar.missing_since, now())
        END
    FROM (
        SELECT a.id, count(al.id) AS albums
        FROM artist a
        LEFT JOIN album_artist aa ON aa.artist_id = a.id AND aa.role = 'albumartist'
        LEFT JOIN album al ON al.id = aa.album_id AND al.missing_since IS NULL
        GROUP BY a.id
    ) c
    WHERE c.id = ar.id
    """,
]


async def refresh_derived_data(session: AsyncSession) -> None:
    """Album counters and covers, album genres, missing albums / artists (whole library)."""
    for statement in _DERIVED_DATA_SQL:
        await session.execute(text(statement))
