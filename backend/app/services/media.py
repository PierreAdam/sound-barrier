"""Audio files and cover art served to clients."""

import asyncio
import hashlib
import io
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Album, AlbumArtist, AppUser, Artist, Artwork, MusicFolder, Song
from app.scanner.formats import IMAGE_CONTENT_TYPES, suffix_of
from app.scanner.tags import extract_picture
from app.services import artist_info, browsing

MAX_COVER_SIZE = 2048


@dataclass(frozen=True)
class AudioFile:
    path: Path
    song: Song


async def song_file(session: AsyncSession, user: AppUser, song_id: str) -> AudioFile | None:
    """The file of a song the user may access, if it exists on disk."""
    parsed = browsing.parse_id(song_id)
    if parsed is None:
        return None
    folder_ids = await browsing.playable_folder_ids(session, user)
    row = (
        await session.execute(
            select(Song, MusicFolder.path)
            .join(MusicFolder, MusicFolder.id == Song.music_folder_id)
            .where(Song.id == parsed, Song.missing_since.is_(None))
            .where(Song.music_folder_id.in_(folder_ids))
        )
    ).first()
    if row is None:
        return None
    song, root = row
    path = Path(root) / song.path
    if not await asyncio.to_thread(path.is_file):
        return None
    return AudioFile(path, song)


# --- cover art ----------------------------------------------------------------


async def find_artwork(session: AsyncSession, cover_id: str) -> tuple[Artwork, str] | None:
    """Artwork and its music folder path for a `coverArt` value.

    We emit artwork ids (albums, songs) and artist ids (artists), but some clients send
    album or song ids too, so all of them are accepted.
    """
    parsed = browsing.parse_id(cover_id)
    if parsed is None:
        return None
    artwork_id = await session.scalar(select(Artwork.id).where(Artwork.id == parsed))
    if artwork_id is None:
        artwork_id = await session.scalar(select(Album.artwork_id).where(Album.id == parsed))
    if artwork_id is None:
        artwork_id = await session.scalar(
            select(func.coalesce(Album.artwork_id, Song.artwork_id))
            .select_from(Song)
            .join(Album, Album.id == Song.album_id)
            .where(Song.id == parsed)
        )
    if artwork_id is None:
        artwork_id = await _artist_artwork(session, parsed)
    if artwork_id is None:
        return None
    row = (
        await session.execute(
            select(Artwork, MusicFolder.path)
            .join(MusicFolder, MusicFolder.id == Artwork.music_folder_id)
            .where(Artwork.id == artwork_id)
        )
    ).first()
    return (row[0], row[1]) if row else None


async def _artist_artwork(session: AsyncSession, artist_id: uuid.UUID) -> uuid.UUID | None:
    """The artist's own image, else the cover of their most recent album."""
    image = await session.scalar(select(Artist.artwork_id).where(Artist.id == artist_id))
    if image is not None:
        return image
    return await session.scalar(
        select(Album.artwork_id)
        .join(AlbumArtist, AlbumArtist.album_id == Album.id)
        .where(
            AlbumArtist.artist_id == artist_id,
            AlbumArtist.role == "albumartist",
            Album.missing_since.is_(None),
            Album.artwork_id.is_not(None),
        )
        .order_by(func.coalesce(Album.year, 0).desc())
        .limit(1)
    )


@dataclass(frozen=True)
class CoverImage:
    data: bytes
    content_type: str


def _read_artwork(artwork: Artwork, root: str) -> tuple[bytes, str] | None:
    path = Path(root) / artwork.path
    if artwork.source == "embedded":
        return extract_picture(path)
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return data, IMAGE_CONTENT_TYPES.get(suffix_of(path.name), "image/jpeg")


def _resize(data: bytes, size: int) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image.thumbnail((size, size))
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=85)
        return output.getvalue()


def _cover_bytes(
    artwork: Artwork, root: str, size: int | None, cache_dir: Path
) -> CoverImage | None:
    if size is None:
        original = _read_artwork(artwork, root)
        return CoverImage(*original) if original else None
    # The cache key includes the source mtime, so a changed cover is picked up.
    key = hashlib.sha1(f"{artwork.id}:{artwork.mtime.isoformat()}:{size}".encode()).hexdigest()
    cached = cache_dir / f"{key}.jpg"
    if cached.is_file():
        return CoverImage(cached.read_bytes(), "image/jpeg")
    original = _read_artwork(artwork, root)
    if original is None:
        return None
    try:
        resized = _resize(original[0], size)
    except OSError:  # not an image Pillow can read: serve it as is
        return CoverImage(*original)
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = cached.with_suffix(".tmp")
    temporary.write_bytes(resized)
    temporary.replace(cached)
    return CoverImage(resized, "image/jpeg")


def _picture_bytes(
    path: Path, version: str, content_type: str, size: int | None, cache_dir: Path
) -> CoverImage | None:
    """An artist picture from an external source (downloaded in the data folder)."""
    try:
        original = path.read_bytes()
    except OSError:
        return None
    if size is None:
        return CoverImage(original, content_type)
    key = hashlib.sha1(f"artist:{path.name}:{version}:{size}".encode()).hexdigest()
    cached = cache_dir / f"{key}.jpg"
    if cached.is_file():
        return CoverImage(cached.read_bytes(), "image/jpeg")
    try:
        resized = _resize(original, size)
    except OSError:
        return CoverImage(original, content_type)
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = cached.with_suffix(".tmp")
    temporary.write_bytes(resized)
    temporary.replace(cached)
    return CoverImage(resized, "image/jpeg")


# Artist picture ids given to the web UI: "ar-<artist id>-<version>", so a new picture
# gets a new URL (browsers cache covers for a day).
ARTIST_PICTURE_PREFIX = "ar-"


def artist_picture_id(artist_id: uuid.UUID, version: str) -> str:
    return f"{ARTIST_PICTURE_PREFIX}{artist_id}-{version}"


async def cover_image(
    session: AsyncSession,
    cover_id: str,
    size: int | None,
    cache_dir: Path,
    pictures_dir: Path | None = None,
) -> CoverImage | None:
    if size is not None:
        size = max(1, min(size, MAX_COVER_SIZE))
    if cover_id.startswith(ARTIST_PICTURE_PREFIX):
        cover_id = cover_id[len(ARTIST_PICTURE_PREFIX) : len(ARTIST_PICTURE_PREFIX) + 36]
    # An artist with a picture from an external source (artist ids are also cover ids).
    artist_id = browsing.parse_id(cover_id)
    if pictures_dir is not None and artist_id is not None:
        found_picture = await artist_info.picture(session, artist_id)
        if found_picture is not None:
            image = await asyncio.to_thread(
                _picture_bytes,
                artist_info.picture_path(pictures_dir, artist_id),
                *found_picture,
                size,
                cache_dir,
            )
            if image is not None:
                return image
    found = await find_artwork(session, cover_id)
    if found is None:
        return None
    return await asyncio.to_thread(_cover_bytes, found[0], found[1], size, cache_dir)
