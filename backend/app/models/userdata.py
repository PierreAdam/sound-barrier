"""Per-user data: annotations, playlists, play queues, bookmarks, play history."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, SmallInteger, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.models.base import Base, bigint_pk, uuid_pk


def _user_fk(primary_key: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=primary_key)


def _song_fk(primary_key: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("song.id", ondelete="CASCADE"), primary_key=primary_key)


class AnnotationMixin:
    """Stars, ratings and play counts. One table per annotated item type."""

    __item_table__: str

    user_id: Mapped[uuid.UUID] = _user_fk(primary_key=True)
    starred_at: Mapped[datetime | None]
    rating: Mapped[int | None] = mapped_column(SmallInteger)  # 1-5
    play_count: Mapped[int] = mapped_column(server_default=text("0"))
    last_played_at: Mapped[datetime | None]

    @declared_attr
    def item_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            ForeignKey(f"{cls.__item_table__}.id", ondelete="CASCADE"),
            primary_key=True,
            index=True,
        )


class SongAnnotation(AnnotationMixin, Base):
    __tablename__ = "song_annotation"
    __item_table__ = "song"


class AlbumAnnotation(AnnotationMixin, Base):
    __tablename__ = "album_annotation"
    __item_table__ = "album"


class ArtistAnnotation(AnnotationMixin, Base):
    __tablename__ = "artist_annotation"
    __item_table__ = "artist"


class DirectoryAnnotation(AnnotationMixin, Base):
    __tablename__ = "directory_annotation"
    __item_table__ = "directory"


class Playlist(Base):
    __tablename__ = "playlist"

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str]
    comment: Mapped[str | None]
    is_public: Mapped[bool] = mapped_column(server_default=text("false"))
    song_count: Mapped[int] = mapped_column(server_default=text("0"))
    duration_ms: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PlaylistEntry(Base):
    __tablename__ = "playlist_entry"

    playlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playlist.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)  # 0-based
    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("song.id", ondelete="CASCADE"), index=True
    )


class PlaylistAllowedUser(Base):
    __tablename__ = "playlist_allowed_user"

    playlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playlist.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = _user_fk(primary_key=True)


class PlayQueue(Base):
    __tablename__ = "play_queue"

    user_id: Mapped[uuid.UUID] = _user_fk(primary_key=True)
    current_song_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("song.id", ondelete="SET NULL")
    )
    # Position of the current song in the queue (the same song can be queued twice).
    current_index: Mapped[int | None]
    position_ms: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    changed_by: Mapped[str]  # client name (`c` param)


class PlayQueueEntry(Base):
    __tablename__ = "play_queue_entry"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("play_queue.user_id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    song_id: Mapped[uuid.UUID] = _song_fk()


class WebQueueMixin:
    """A queue of the web UI (see WebPlayQueue and WebPlayer)."""

    # Play order. No foreign keys: songs deleted since are dropped when read.
    song_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    # Shuffled queues: the play positions in the original order (to turn shuffle off).
    original_order: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    current_index: Mapped[int]  # in play order, -1 for none
    position_ms: Mapped[int] = mapped_column(BigInteger)
    revision: Mapped[int]  # +1 at every save: browsers tell whether theirs is outdated
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class WebPlayQueue(WebQueueMixin, Base):
    """The Shared player's queue: one per user, used by every browser not assigned to
    one of their players (reopening the web UI anywhere brings it back). Subsonic
    clients keep theirs in `play_queue`."""

    __tablename__ = "web_play_queue"

    user_id: Mapped[uuid.UUID] = _user_fk(primary_key=True)


class WebPlayer(WebQueueMixin, Base):
    """A player the user created (e.g. "Phone"), with its own queue: the browsers
    assigned to it (kept in their local storage) play that queue instead of the Shared
    one. Deleted with its queue."""

    __tablename__ = "web_player"
    __table_args__ = (
        # Names are unique per user, whatever the case.
        Index("uq_web_player_user_id_name", "user_id", func.lower(text("name")), unique=True),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Bookmark(Base):
    __tablename__ = "bookmark"

    user_id: Mapped[uuid.UUID] = _user_fk(primary_key=True)
    song_id: Mapped[uuid.UUID] = _song_fk(primary_key=True)
    position_ms: Mapped[int] = mapped_column(BigInteger)
    comment: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PlayHistory(Base):
    """Append-only log of scrobbles."""

    __tablename__ = "play_history"
    __table_args__ = (Index("ix_play_history_user_played", "user_id", "played_at"),)

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("song.id", ondelete="CASCADE"), index=True
    )
    played_at: Mapped[datetime]
    client: Mapped[str]
    submission: Mapped[bool]  # true = counted play, false = "now playing" notification


class NowPlaying(Base):
    __tablename__ = "now_playing"

    user_id: Mapped[uuid.UUID] = _user_fk(primary_key=True)
    client: Mapped[str] = mapped_column(primary_key=True)
    song_id: Mapped[uuid.UUID] = _song_fk()
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
