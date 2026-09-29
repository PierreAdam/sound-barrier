"""Podcasts and audiobooks, from their own library folders (never mixed with music).

A show (podcast) or a book (audiobook) is an album of the scanner; its episodes / chapters
are its songs. Podcast episodes come newest first (file date), audiobook chapters in order
(disc, track when the tags are consistent, else the file names). Where the user stopped is
their bookmark (services/bookmarks.py).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import consistent_numbers, natural_key
from app.models import Album, AppUser, Bookmark, MusicFolder, Song
from app.services import browsing, music_folders
from app.services.browsing import SongEntry

CONTINUE_LISTENING = 12


@dataclass
class Show:
    album: Album
    kind: str  # podcasts, audiobooks
    episodes: list[SongEntry] = field(default_factory=list[SongEntry])  # in listening order

    @property
    def duration_ms(self) -> int:
        return sum(e.song.duration_ms for e in self.episodes)

    @property
    def latest(self) -> datetime | None:
        return max((e.song.file_mtime for e in self.episodes), default=None)


@dataclass
class Resume:
    """A started episode / chapter (a bookmark) and its show."""

    show: Show
    episode: SongEntry
    changed_at: datetime


def _order(kind: str, episodes: list[SongEntry]) -> list[SongEntry]:
    if kind == music_folders.AUDIOBOOKS:
        if consistent_numbers([(e.song.disc_number, e.song.track_number) for e in episodes]):
            return sorted(
                episodes,
                key=lambda e: (e.song.disc_number or 1, e.song.track_number or 0, e.song.path),
            )
        return sorted(episodes, key=lambda e: natural_key(e.song.path))
    return sorted(episodes, key=lambda e: (e.song.file_mtime, e.song.path), reverse=True)


async def _folders(session: AsyncSession, user: AppUser, kinds: tuple[str, ...]) -> dict[int, str]:
    """The user's folders of these kinds (the ones that are on): id -> kind."""
    found: dict[int, str] = {}
    for kind in kinds:
        for folder_id in await browsing.spoken_folder_ids(session, user, kind):
            found[folder_id] = kind
    return found


async def shows(
    session: AsyncSession,
    user: AppUser,
    kinds: tuple[str, ...] = music_folders.SPOKEN_KINDS,
    album_id: uuid.UUID | None = None,
) -> list[Show]:
    """The shows / books of these kinds (or only `album_id`), by title."""
    folders = await _folders(session, user, kinds)
    where = [Song.album_id == album_id] if album_id else []
    entries = await browsing.folder_songs(session, user, list(folders), *where)
    by_album: dict[uuid.UUID, Show] = {}
    for entry in entries:
        kind = folders.get(entry.song.music_folder_id)
        if kind is None:
            continue
        show = by_album.setdefault(entry.album.id, Show(entry.album, kind))
        show.episodes.append(entry)
    for show in by_album.values():
        show.episodes = _order(show.kind, show.episodes)
    return sorted(by_album.values(), key=lambda s: s.album.sort_name.casefold())


async def show(session: AsyncSession, user: AppUser, album_id: uuid.UUID) -> Show | None:
    found = await shows(session, user, album_id=album_id)
    return found[0] if found else None


async def continue_listening(
    session: AsyncSession, user: AppUser, kinds: tuple[str, ...]
) -> list[Resume]:
    """What the user started and did not finish: the latest bookmark of each show / book,
    most recent first."""
    folders = await _folders(session, user, kinds)
    if not folders:
        return []
    rows = (
        await session.execute(
            select(Bookmark.song_id, Song.album_id, Bookmark.changed_at)
            .join(Song, Song.id == Bookmark.song_id)
            .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
            .where(
                Bookmark.user_id == user.id,
                Song.missing_since.is_(None),
                Song.music_folder_id.in_(list(folders)),
            )
            .order_by(Bookmark.changed_at.desc())
        )
    ).all()
    latest: dict[uuid.UUID, tuple[uuid.UUID, datetime]] = {}
    for song_id, album_id, changed_at in rows:
        latest.setdefault(album_id, (song_id, changed_at))
    picked = list(latest.items())[:CONTINUE_LISTENING]
    found: list[Resume] = []
    for album_id, (song_id, changed_at) in picked:
        current = await show(session, user, album_id)
        episode = (
            next((e for e in current.episodes if e.song.id == song_id), None) if current else None
        )
        if current and episode:
            found.append(Resume(current, episode, changed_at))
    return found


async def newest_episodes(
    session: AsyncSession, user: AppUser, count: int
) -> list[tuple[Show, SongEntry]]:
    """The latest podcast episodes (Subsonic getNewestPodcasts)."""
    folders = await _folders(session, user, (music_folders.PODCASTS,))
    entries = await browsing.folder_songs(
        session, user, list(folders), order_by=(Song.file_mtime.desc(),)
    )
    found: list[tuple[Show, SongEntry]] = []
    cache: dict[uuid.UUID, Show] = {}
    for entry in entries[:count]:
        show_of = cache.setdefault(
            entry.album.id, Show(entry.album, music_folders.PODCASTS, [entry])
        )
        found.append((show_of, entry))
    return found
