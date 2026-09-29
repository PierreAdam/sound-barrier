"""Library tables. Written only by the scanner."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, LibraryItemMixin, TimestampMixin, uuid_pk


def _trigram_index(table: str, column: str) -> Index:
    return Index(
        f"ix_{table}_{column}_trgm",
        column,
        postgresql_using="gin",
        postgresql_ops={column: "gin_trgm_ops"},
    )


class MusicFolder(Base):
    __tablename__ = "music_folder"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str]
    path: Mapped[str] = mapped_column(unique=True)
    # music, podcasts or audiobooks (services/music_folders.py): never mixed.
    kind: Mapped[str] = mapped_column(server_default=text("'music'"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Artwork(Base):
    __tablename__ = "artwork"
    __table_args__ = (UniqueConstraint("music_folder_id", "source", "path"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    music_folder_id: Mapped[int] = mapped_column(ForeignKey("music_folder.id", ondelete="CASCADE"))
    # "embedded" (picture inside an audio file) or "file" (cover.jpg, folder.png...)
    source: Mapped[str]
    path: Mapped[str]  # relative to the music folder
    mtime: Mapped[datetime]
    width: Mapped[int | None]
    height: Mapped[int | None]


class Directory(LibraryItemMixin, Base):
    __tablename__ = "directory"
    __table_args__ = (UniqueConstraint("music_folder_id", "path"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    music_folder_id: Mapped[int] = mapped_column(ForeignKey("music_folder.id", ondelete="CASCADE"))
    # null = top-level directory of the music folder
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("directory.id", ondelete="CASCADE"), index=True
    )
    path: Mapped[str]
    name: Mapped[str]
    artwork_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork.id", ondelete="SET NULL")
    )
    mtime: Mapped[datetime]


class Artist(LibraryItemMixin, Base):
    __tablename__ = "artist"
    __table_args__ = (_trigram_index("artist", "name_search"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    # Scanner identity: "mbz:<id>" or "name:<normalized name>"
    match_key: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    sort_name: Mapped[str]
    name_search: Mapped[str]
    mbz_artist_id: Mapped[str | None]
    artwork_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork.id", ondelete="SET NULL")
    )
    album_count: Mapped[int] = mapped_column(server_default=text("0"))


class Album(LibraryItemMixin, Base):
    __tablename__ = "album"
    __table_args__ = (_trigram_index("album", "name_search"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    # Scanner identity: "mbz:<id>" or "<album artist>|<album name>|<directory>"
    match_key: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    sort_name: Mapped[str]
    name_search: Mapped[str]
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artist.id"), index=True)
    display_artist: Mapped[str]
    year: Mapped[int | None] = mapped_column(SmallInteger)
    release_date: Mapped[str | None]  # partial ISO date: YYYY, YYYY-MM or YYYY-MM-DD
    original_release_date: Mapped[str | None]
    is_compilation: Mapped[bool] = mapped_column(server_default=text("false"))
    release_types: Mapped[list[str]] = mapped_column(server_default=text("'{}'"))
    record_labels: Mapped[list[str]] = mapped_column(server_default=text("'{}'"))
    moods: Mapped[list[str]] = mapped_column(server_default=text("'{}'"))
    explicit_status: Mapped[str | None]
    disc_titles: Mapped[list[dict[str, Any]]] = mapped_column(server_default=text("'[]'"))
    mbz_album_id: Mapped[str | None]
    mbz_release_group_id: Mapped[str | None]
    artwork_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork.id", ondelete="SET NULL")
    )
    song_count: Mapped[int] = mapped_column(server_default=text("0"))
    duration_ms: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class Song(LibraryItemMixin, Base):
    __tablename__ = "song"
    __table_args__ = (
        UniqueConstraint("music_folder_id", "path"),
        Index("ix_song_album_order", "album_id", "disc_number", "track_number"),
        _trigram_index("song", "title_search"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    music_folder_id: Mapped[int] = mapped_column(ForeignKey("music_folder.id", ondelete="CASCADE"))
    directory_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("directory.id", ondelete="CASCADE"), index=True
    )
    album_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("album.id"))
    artist_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("artist.id"), index=True)
    path: Mapped[str]
    title: Mapped[str]
    sort_title: Mapped[str]
    title_search: Mapped[str]
    display_artist: Mapped[str]
    display_composer: Mapped[str | None]
    track_number: Mapped[int | None] = mapped_column(SmallInteger)
    disc_number: Mapped[int | None] = mapped_column(SmallInteger)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    duration_ms: Mapped[int]
    bit_rate: Mapped[int]  # kbps
    sample_rate: Mapped[int | None]
    bit_depth: Mapped[int | None] = mapped_column(SmallInteger)
    channels: Mapped[int | None] = mapped_column(SmallInteger)
    size: Mapped[int] = mapped_column(BigInteger)
    suffix: Mapped[str]
    content_type: Mapped[str]
    bpm: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None]
    explicit_status: Mapped[str | None]
    replaygain_track_gain: Mapped[float | None] = mapped_column(REAL)
    replaygain_track_peak: Mapped[float | None] = mapped_column(REAL)
    replaygain_album_gain: Mapped[float | None] = mapped_column(REAL)
    replaygain_album_peak: Mapped[float | None] = mapped_column(REAL)
    mbz_recording_id: Mapped[str | None]
    mbz_track_id: Mapped[str | None]
    artwork_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("artwork.id", ondelete="SET NULL")
    )
    file_mtime: Mapped[datetime]
    # Chapters inside the file (audiobooks): [{"startMs": 0, "title": "Chapter 1"}, ...]
    chapters: Mapped[list[dict[str, Any]] | None]


class Genre(Base):
    __tablename__ = "genre"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(unique=True)


class SongArtist(Base):
    __tablename__ = "song_artist"

    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("song.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artist.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # artist, albumartist, composer, performer, conductor, lyricist...
    role: Mapped[str] = mapped_column(primary_key=True)
    # e.g. the instrument for a performer; empty string when not applicable
    sub_role: Mapped[str] = mapped_column(primary_key=True, server_default=text("''"))
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class AlbumArtist(Base):
    __tablename__ = "album_artist"

    album_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("album.id", ondelete="CASCADE"), primary_key=True
    )
    artist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("artist.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[str] = mapped_column(primary_key=True)
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class SongGenre(Base):
    __tablename__ = "song_genre"

    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("song.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("genre.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class AlbumGenre(Base):
    __tablename__ = "album_genre"

    album_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("album.id", ondelete="CASCADE"), primary_key=True
    )
    genre_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("genre.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class Lyrics(TimestampMixin, Base):
    __tablename__ = "lyrics"

    id: Mapped[uuid.UUID] = uuid_pk()
    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("song.id", ondelete="CASCADE"), index=True
    )
    lang: Mapped[str] = mapped_column(server_default=text("'xxx'"))
    synced: Mapped[bool]
    offset_ms: Mapped[int] = mapped_column(server_default=text("0"))
    lines: Mapped[list[dict[str, Any]]]  # [{"start_ms": int | None, "value": str}]
    source: Mapped[str]  # "embedded" or "lrc"
