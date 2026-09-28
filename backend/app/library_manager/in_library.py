"""Whether the album folders of the import browser are already in the library (an
information for the admin: importing again is still possible).

An album folder is a folder that directly contains audio files. It is in the library when,
in this order:
1. its files' tags name a library album: same MusicBrainz release or release group, else
   same album artist and album title (normalized: "(Deluxe Edition)" and the like ignored);
2. (files without album tags) its name, and its parent's, once cleaned of years, formats
   and bracketed extras ("Delain - Dark Waters (2023)", "Dethklok (FLAC)/2023 - Dethalbum
   IV"), contain a library artist and one of that artist's albums;
3. it was imported by Sound-Barrier and the imported files are still in the library.

Tags are read once per folder and kept until the folder changes (its modification time).
"""

import asyncio
import os
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import title_key
from app.library_manager.files import is_audio
from app.library_manager.imports import IMPORTED
from app.models import Album, ImportTask, Song
from app.scanner.tags import read_audio_file

_BRACKETED = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
# Words that describe the files, not the music: formats, bitrates, sources, discs.
_NOISE = re.compile(
    r"\b(?:flac|mp3|aac|alac|m4a|ogg|opus|wav|ape|wv|dsd|hi-?res|lossless|"
    r"\d{2,3}\s?kbps|\d{2,3}k|v0|v2|320|24bit|24-bit|16bit|\d{2}(?:\.\d)?\s?khz|"
    r"web|cd|cdrip|vinyl|lp|ep|remaster(?:ed)?|deluxe|edition|disc\s?\d+|cd\s?\d+)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass
class FolderTags:
    """What the audio files of a folder say (the most common album)."""

    tracks: int
    album: str | None = None
    album_artist: str | None = None
    release_ids: set[str] = field(default_factory=set[str])
    release_group_ids: set[str] = field(default_factory=set[str])
    titles: list[str] = field(default_factory=list[str])  # title_key of each track
    recording_ids: set[str] = field(default_factory=set[str])


@dataclass
class InLibrary:
    path: str
    album_id: str
    album: str
    artist: str
    tracks: int  # audio files in the folder
    library_tracks: int | None  # of them in the library; None: unknown (no title tags)
    reason: str  # "tags", "name" or "imported"


_cache: dict[str, tuple[int, FolderTags]] = {}
_cache_lock = threading.Lock()


def _read_folder(folder: Path) -> FolderTags:
    files = sorted(p for p in folder.iterdir() if p.is_file() and is_audio(p))
    found = FolderTags(tracks=len(files))
    albums: Counter[tuple[str, str]] = Counter()
    for path in files:
        audio = read_audio_file(path)
        if audio is None:
            continue
        tags = audio.tags
        artist = tags.display_album_artist or tags.display_artist
        if tags.album and artist:
            albums[(artist, tags.album)] += 1
        if tags.mbz_album_id:
            found.release_ids.add(tags.mbz_album_id)
        if tags.mbz_release_group_id:
            found.release_group_ids.add(tags.mbz_release_group_id)
        if tags.mbz_recording_id:
            found.recording_ids.add(tags.mbz_recording_id)
        if tags.title:
            found.titles.append(title_key(tags.title))
    if albums:
        (found.album_artist, found.album), _ = albums.most_common(1)[0]
    return found


def folder_tags(folder: Path) -> FolderTags:
    """The folder's tags, read again only when its content changed."""
    key = os.path.normcase(str(folder))
    mtime = folder.stat().st_mtime_ns
    with _cache_lock:
        cached = _cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    found = _read_folder(folder)
    with _cache_lock:
        _cache[key] = (mtime, found)
    return found


def clean_name(name: str, *, keep_years: bool = False) -> str:
    """A folder name without what is not the artist or the album: "Dethklok (FLAC)" ->
    "dethklok", "2023 - Dethalbum IV" -> "dethalbum iv" (`keep_years`: for albums named
    after a year, e.g. "1984")."""
    text = _BRACKETED.sub(" ", name)
    text = _NOISE.sub(" ", text)
    if not keep_years:
        text = _YEAR.sub(" ", text)
    return title_key(text.replace("_", " ").replace(".", " "))


def _contains(text: str, phrase: str) -> bool:
    """Whether `phrase` appears in `text` as whole words (both in title_key form)."""
    return bool(phrase) and f" {phrase} " in f" {text} "


@dataclass
class _LibraryAlbum:
    id: str
    name: str
    artist: str
    artist_key: str
    title_key: str


class LibraryIndex:
    """The library's albums, looked up by MusicBrainz ids and by names."""

    def __init__(self, albums: list[_LibraryAlbum], ids: dict[str, _LibraryAlbum]) -> None:
        self.by_id = ids  # MusicBrainz release and release group ids
        self.by_names = {(a.artist_key, a.title_key): a for a in albums}
        self.by_artist: dict[str, list[_LibraryAlbum]] = {}
        for album in albums:
            self.by_artist.setdefault(album.artist_key, []).append(album)

    def from_tags(self, tags: FolderTags) -> _LibraryAlbum | None:
        for mbid in (*tags.release_ids, *tags.release_group_ids):
            if mbid in self.by_id:
                return self.by_id[mbid]
        if tags.album and tags.album_artist:
            return self.by_names.get((title_key(tags.album_artist), title_key(tags.album)))
        return None

    def from_names(self, folder: Path) -> _LibraryAlbum | None:
        owns = [clean_name(folder.name), clean_name(folder.name, keep_years=True)]
        text = f"{clean_name(folder.parent.name)} {owns[1]}"
        found: _LibraryAlbum | None = None
        for artist_key, albums in self.by_artist.items():
            if not _contains(text, artist_key):
                continue
            for album in albums:
                # The album is in the folder's own name (the parent may be the artist's
                # folder); the longest title wins ("Bloody Hammers - Washed in the Blood").
                if any(_contains(own, album.title_key) for own in owns) and (
                    found is None or len(album.title_key) > len(found.title_key)
                ):
                    found = album
        return found


async def library_index(session: AsyncSession) -> LibraryIndex:
    rows = (
        await session.execute(
            select(
                Album.id,
                Album.name,
                Album.display_artist,
                Album.mbz_album_id,
                Album.mbz_release_group_id,
            ).where(Album.missing_since.is_(None))
        )
    ).all()
    albums: list[_LibraryAlbum] = []
    ids: dict[str, _LibraryAlbum] = {}
    for album_id, name, artist, release, group in rows:
        album = _LibraryAlbum(str(album_id), name, artist, title_key(artist), title_key(name))
        albums.append(album)
        for mbid in (release, group):
            if mbid:
                ids.setdefault(mbid, album)
    return LibraryIndex(albums, ids)


def _normalized(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


async def _imported(session: AsyncSession, folders: list[Path]) -> dict[str, str]:
    """Folders imported by Sound-Barrier whose files are still in the library: their
    album id."""
    wanted = {_normalized(str(folder)): folder for folder in folders}
    tasks = (
        await session.execute(
            select(ImportTask.source_dir, ImportTask.result).where(ImportTask.status == IMPORTED)
        )
    ).all()
    paths: dict[str, list[str]] = {}
    for source, result in tasks:
        key = _normalized(source)
        if key in wanted and result:
            imported_paths: list[Any] = result.get("paths") or []
            paths[key] = [str(path) for path in imported_paths]
    found: dict[str, str] = {}
    for key, imported in paths.items():
        album_id = await session.scalar(
            select(Song.album_id)
            .where(Song.path.in_(imported), Song.missing_since.is_(None))
            .limit(1)
        )
        if album_id is not None:
            found[key] = str(album_id)
    return found


async def _song_keys(
    session: AsyncSession, album_ids: set[str]
) -> dict[str, tuple[set[str], set[str]]]:
    """Per album: its songs' title keys and MusicBrainz recording ids."""
    rows = (
        await session.execute(
            select(Song.album_id, Song.title, Song.mbz_recording_id).where(
                Song.album_id.in_(album_ids), Song.missing_since.is_(None)
            )
        )
    ).all()
    keys: dict[str, tuple[set[str], set[str]]] = {}
    for album_id, title, recording in rows:
        titles, recordings = keys.setdefault(str(album_id), (set(), set()))
        titles.add(title_key(title))
        if recording:
            recordings.add(recording)
    return keys


def _library_tracks(tags: FolderTags, titles: set[str], recordings: set[str]) -> int | None:
    if not tags.titles and not tags.recording_ids:
        return None
    by_recording = len(tags.recording_ids & recordings)
    by_title = sum(1 for title in tags.titles if title in titles)
    return min(tags.tracks, max(by_recording, by_title))


async def album_folders_in_library(session: AsyncSession, folders: list[Path]) -> list[InLibrary]:
    """Which of these album folders are in the library (the others are left out)."""
    if not folders:
        return []
    index = await library_index(session)
    imported = await _imported(session, folders)
    albums = {a.id: a for group in index.by_artist.values() for a in group}
    matches: list[tuple[Path, FolderTags, _LibraryAlbum, str]] = []
    for folder in folders:
        tags = await asyncio.to_thread(folder_tags, folder)
        album = index.from_tags(tags)
        reason = "tags"
        if album is None and not tags.album:
            album, reason = index.from_names(folder), "name"
        if album is None and _normalized(str(folder)) in imported:
            album, reason = albums.get(imported[_normalized(str(folder))]), "imported"
        if album is not None:
            matches.append((folder, tags, album, reason))
    songs = await _song_keys(session, {album.id for _, _, album, _ in matches})
    return [
        InLibrary(
            path=str(folder),
            album_id=album.id,
            album=album.name,
            artist=album.artist,
            tracks=tags.tracks,
            library_tracks=_library_tracks(tags, *songs.get(album.id, (set(), set()))),
            reason=reason,
        )
        for folder, tags, album, reason in matches
    ]
