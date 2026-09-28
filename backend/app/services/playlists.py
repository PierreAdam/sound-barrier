"""Playlists (Subsonic getPlaylists, getPlaylist, createPlaylist, updatePlaylist,
deletePlaylist; also used by the web UI).

A user sees their own playlists and the public ones of others; only the owner (or an
admin) changes a playlist. Songs deleted from the library drop out of playlists.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Album, AppUser, Playlist, PlaylistEntry, Song
from app.services import browsing
from app.services.browsing import SongEntry

MAX_SONGS = 10000


class PlaylistNotFoundError(LookupError):
    pass


class PlaylistPermissionError(PermissionError):
    pass


@dataclass
class PlaylistSummary:
    playlist: Playlist
    owner: str
    song_count: int  # present songs
    duration_ms: int
    cover_art: str | None  # the cover of the first song's album


async def _summaries(
    session: AsyncSession, playlists: list[tuple[Playlist, str]]
) -> list[PlaylistSummary]:
    ids = [p.id for p, _ in playlists]
    counts = {
        playlist_id: (songs, int(duration or 0))
        for playlist_id, songs, duration in await session.execute(
            select(PlaylistEntry.playlist_id, func.count(Song.id), func.sum(Song.duration_ms))
            .join(Song, Song.id == PlaylistEntry.song_id)
            .where(PlaylistEntry.playlist_id.in_(ids), Song.missing_since.is_(None))
            .group_by(PlaylistEntry.playlist_id)
        )
    }
    covers: dict[uuid.UUID, uuid.UUID | None] = {}
    for playlist_id, artwork_id in await session.execute(
        select(PlaylistEntry.playlist_id, func.coalesce(Album.artwork_id, Song.artwork_id))
        .join(Song, Song.id == PlaylistEntry.song_id)
        .join(Album, Album.id == Song.album_id)
        .where(PlaylistEntry.playlist_id.in_(ids), Song.missing_since.is_(None))
        .order_by(PlaylistEntry.playlist_id, PlaylistEntry.position)
    ):
        covers.setdefault(playlist_id, artwork_id)
    result: list[PlaylistSummary] = []
    for playlist, owner in playlists:
        songs, duration = counts.get(playlist.id, (0, 0))
        cover = covers.get(playlist.id)
        result.append(
            PlaylistSummary(playlist, owner, songs, duration, str(cover) if cover else None)
        )
    return result


async def visible(session: AsyncSession, user: AppUser) -> list[PlaylistSummary]:
    """The user's playlists and the public ones of others, by name."""
    rows = (
        await session.execute(
            select(Playlist, AppUser.username)
            .join(AppUser, AppUser.id == Playlist.owner_id)
            .where((Playlist.owner_id == user.id) | Playlist.is_public)
            .order_by(func.lower(Playlist.name), Playlist.created_at)
        )
    ).all()
    return await _summaries(session, [(p, owner) for p, owner in rows])


async def _get(session: AsyncSession, user: AppUser, playlist_id: uuid.UUID) -> Playlist:
    playlist = await session.get(Playlist, playlist_id)
    if playlist is None or not (
        playlist.owner_id == user.id or playlist.is_public or user.is_admin
    ):
        raise PlaylistNotFoundError(str(playlist_id))
    return playlist


async def _editable(session: AsyncSession, user: AppUser, playlist_id: uuid.UUID) -> Playlist:
    playlist = await _get(session, user, playlist_id)
    if playlist.owner_id != user.id and not user.is_admin:
        raise PlaylistPermissionError("Only its owner can change this playlist")
    return playlist


async def _song_ids(session: AsyncSession, playlist_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await session.scalars(
                select(PlaylistEntry.song_id)
                .where(PlaylistEntry.playlist_id == playlist_id)
                .order_by(PlaylistEntry.position)
            )
        ).all()
    )


async def get(
    session: AsyncSession, user: AppUser, playlist_id: uuid.UUID
) -> tuple[PlaylistSummary, list[SongEntry]]:
    playlist = await _get(session, user, playlist_id)
    owner = await session.get(AppUser, playlist.owner_id)
    ids = await _song_ids(session, playlist_id)
    entries = await browsing.get_songs(session, user, ids)
    songs = [entries[song_id] for song_id in ids if song_id in entries]
    (summary,) = await _summaries(session, [(playlist, owner.username if owner else "")])
    return summary, songs


async def _write_songs(
    session: AsyncSession, user: AppUser, playlist: Playlist, song_ids: list[uuid.UUID]
) -> None:
    """Replaces the songs (unknown ids and songs the owner cannot see are left out)."""
    if len(song_ids) > MAX_SONGS:
        raise ValueError(f"A playlist holds at most {MAX_SONGS} songs")
    known = await browsing.get_songs(session, user, song_ids)
    kept = [song_id for song_id in song_ids if song_id in known]
    await session.execute(delete(PlaylistEntry).where(PlaylistEntry.playlist_id == playlist.id))
    session.add_all(
        PlaylistEntry(playlist_id=playlist.id, position=position, song_id=song_id)
        for position, song_id in enumerate(kept)
    )
    playlist.song_count = len(kept)
    playlist.duration_ms = sum(known[song_id].song.duration_ms for song_id in kept)
    playlist.changed_at = datetime.now(UTC)
    await session.flush()


async def create(
    session: AsyncSession, user: AppUser, name: str, song_ids: list[uuid.UUID]
) -> uuid.UUID:
    name = name.strip()
    if not name:
        raise ValueError("A playlist needs a name")
    playlist = Playlist(owner_id=user.id, name=name, is_public=False)
    session.add(playlist)
    await session.flush()
    await _write_songs(session, user, playlist, song_ids)
    return playlist.id


async def replace_songs(
    session: AsyncSession, user: AppUser, playlist_id: uuid.UUID, song_ids: list[uuid.UUID]
) -> None:
    playlist = await _editable(session, user, playlist_id)
    await _write_songs(session, user, playlist, song_ids)


async def update(
    session: AsyncSession,
    user: AppUser,
    playlist_id: uuid.UUID,
    *,
    name: str | None = None,
    comment: str | None = None,
    public: bool | None = None,
    add: list[uuid.UUID] | None = None,
    remove_indexes: list[int] | None = None,
) -> None:
    """`remove_indexes` are positions in the playlist as the client saw it (before
    `add`)."""
    playlist = await _editable(session, user, playlist_id)
    if name is not None and name.strip():
        playlist.name = name.strip()
    if comment is not None:
        playlist.comment = comment.strip() or None
    if public is not None:
        playlist.is_public = public
    if add or remove_indexes:
        # Positions refer to the songs the client sees (present ones).
        current = [s.song.id for s in (await get(session, user, playlist_id))[1]]
        doomed = set(remove_indexes or [])
        songs = [song_id for index, song_id in enumerate(current) if index not in doomed]
        await _write_songs(session, user, playlist, songs + (add or []))
    else:
        playlist.changed_at = datetime.now(UTC)
        await session.flush()


async def remove(session: AsyncSession, user: AppUser, playlist_id: uuid.UUID) -> None:
    playlist = await _editable(session, user, playlist_id)
    await session.delete(playlist)
    await session.flush()
