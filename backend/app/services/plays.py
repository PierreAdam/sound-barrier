"""Plays (Subsonic `scrobble`): play counts and "last played" per user, play history,
"now playing"."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AlbumAnnotation,
    AppUser,
    ArtistAnnotation,
    NowPlaying,
    PlayHistory,
    SongAnnotation,
)
from app.services import browsing
from app.services.browsing import SongEntry

type _Annotation = type[SongAnnotation] | type[AlbumAnnotation] | type[ArtistAnnotation]


async def _count_play(
    session: AsyncSession, model: _Annotation, user: AppUser, item_id: uuid.UUID, at: datetime
) -> None:
    statement = insert(model).values(
        user_id=user.id, item_id=item_id, play_count=1, last_played_at=at
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[model.user_id, model.item_id],
            set_={
                "play_count": model.play_count + 1,
                "last_played_at": func.greatest(model.last_played_at, at),
            },
        )
    )


async def scrobble(
    session: AsyncSession,
    user: AppUser,
    song_ids: list[uuid.UUID],
    times: list[datetime | None],
    *,
    submission: bool,
    client: str,
) -> int:
    """`submission`: counted plays (song, album, artist counts; history). Otherwise the
    songs being played now. Unknown / invisible songs are ignored. Returns how many
    songs were taken into account."""
    entries = await browsing.get_songs(session, user, song_ids)
    now = datetime.now(UTC)
    handled = 0
    for index, song_id in enumerate(song_ids):
        entry = entries.get(song_id)
        if entry is None:
            continue
        handled += 1
        at = (times[index] if index < len(times) else None) or now
        song = entry.song
        if not submission:
            statement = insert(NowPlaying).values(
                user_id=user.id, client=client, song_id=song.id, updated_at=now
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[NowPlaying.user_id, NowPlaying.client],
                    set_={"song_id": song.id, "updated_at": now},
                )
            )
            continue
        session.add(
            PlayHistory(
                user_id=user.id, song_id=song.id, played_at=at, client=client, submission=True
            )
        )
        await _count_play(session, SongAnnotation, user, song.id, at)
        await _count_play(session, AlbumAnnotation, user, song.album_id, at)
        await _count_play(session, ArtistAnnotation, user, song.artist_id, at)
    await session.flush()
    return handled


@dataclass(frozen=True)
class NowPlayingEntry:
    song: SongEntry
    username: str
    client: str
    minutes_ago: int


async def now_playing(session: AsyncSession, user: AppUser) -> list[NowPlayingEntry]:
    """What everyone is listening to: songs announced as playing that are not over yet
    (announced less than their duration ago, plus a minute), songs the caller may see."""
    rows = (
        await session.execute(
            select(NowPlaying, AppUser.username)
            .join(AppUser, AppUser.id == NowPlaying.user_id)
            .order_by(NowPlaying.updated_at.desc())
        )
    ).all()
    entries = await browsing.get_songs(session, user, [row.song_id for row, _ in rows])
    now = datetime.now(UTC)
    result: list[NowPlayingEntry] = []
    for row, username in rows:
        entry = entries.get(row.song_id)
        if entry is None:
            continue
        elapsed = now - row.updated_at
        if elapsed > timedelta(milliseconds=entry.song.duration_ms) + timedelta(minutes=1):
            continue
        result.append(
            NowPlayingEntry(entry, username, row.client, int(elapsed.total_seconds() // 60))
        )
    return result
