"""Similar songs ("instant mix", getSimilarSongs2): songs of the artist mixed with songs of
its similar artists (Last.fm, only those of the library). Without similar artists: songs
of the artist's main genre."""

import random
import uuid
from collections import Counter
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import PasswordCipher
from app.models import AppUser
from app.services import artist_info, browsing
from app.services.browsing import SongEntry

SIMILAR_ARTISTS = 10  # of the library, most similar first
OWN_SHARE = 0.3  # of the mix: the artist's own songs


async def similar_songs(
    session: AsyncSession,
    user: AppUser,
    artist_id: uuid.UUID,
    count: int,
    *,
    http: httpx.AsyncClient,
    cipher: PasswordCipher,
    pictures_dir: Path,
) -> list[SongEntry] | None:
    """Up to `count` songs in a random order; None for an unknown artist."""
    details = await artist_info.get(
        session,
        user,
        artist_id,
        http=http,
        cipher=cipher,
        pictures_dir=pictures_dir,
        top_songs=0,
    )
    if details is None:
        return None
    own = await browsing.artist_songs(session, user, artist_id)
    others: list[SongEntry] = []
    similar_ids = [s.artist_id for s in details.similar if s.artist_id and s.artist_id != artist_id]
    for similar_id in similar_ids[:SIMILAR_ARTISTS]:
        others += await browsing.artist_songs(session, user, similar_id)
    if not others:
        others = await _same_genre(session, user, own, count)
    own_ids = {e.song.id for e in own}
    others = [e for e in others if e.song.id not in own_ids]

    wanted_own = max(1, round(count * OWN_SHARE)) if others else count
    mix = random.sample(own, min(len(own), wanted_own))
    mix += random.sample(others, min(len(others), count - len(mix)))
    if len(mix) < count:  # not enough similar songs: more of the artist's own
        chosen = {e.song.id for e in mix}
        rest = [e for e in own if e.song.id not in chosen]
        mix += random.sample(rest, min(len(rest), count - len(mix)))
    random.shuffle(mix)
    return mix


async def _same_genre(
    session: AsyncSession, user: AppUser, songs: list[SongEntry], count: int
) -> list[SongEntry]:
    genres = Counter(genre for entry in songs for genre in entry.genres)
    if not genres:
        return []
    genre = genres.most_common(1)[0][0]
    return await browsing.random_songs(session, user, size=count * 2, genre=genre)
