import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, LargeBinary, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


def _role(default: bool = True) -> Mapped[bool]:
    return mapped_column(server_default=text("true" if default else "false"))


class AppUser(TimestampMixin, Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = uuid_pk()
    username: Mapped[str] = mapped_column(unique=True)
    # Encrypted, not hashed: Subsonic token auth needs the plaintext (see core.crypto).
    password_enc: Mapped[bytes] = mapped_column(LargeBinary)
    email: Mapped[str | None]
    max_bit_rate: Mapped[int] = mapped_column(server_default=text("0"))  # 0 = unlimited
    scrobbling_enabled: Mapped[bool] = _role()

    is_admin: Mapped[bool] = _role(default=False)
    settings_role: Mapped[bool] = _role()
    download_role: Mapped[bool] = _role()
    upload_role: Mapped[bool] = _role(default=False)
    playlist_role: Mapped[bool] = _role()
    cover_art_role: Mapped[bool] = _role()
    comment_role: Mapped[bool] = _role()
    podcast_role: Mapped[bool] = _role(default=False)
    stream_role: Mapped[bool] = _role()
    jukebox_role: Mapped[bool] = _role(default=False)
    share_role: Mapped[bool] = _role(default=False)
    video_conversion_role: Mapped[bool] = _role(default=False)

    avatar_path: Mapped[str | None]
    last_seen_at: Mapped[datetime | None]
    # Web UI preferences (theme, player...), see services/preferences.py.
    preferences: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))


class UserMusicFolder(Base):
    """Restricts a user to some music folders. A user with no rows sees every folder."""

    __tablename__ = "user_music_folder"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    music_folder_id: Mapped[int] = mapped_column(
        ForeignKey("music_folder.id", ondelete="CASCADE"), primary_key=True
    )


class ApiKey(Base):
    __tablename__ = "api_key"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str]
    key_hash: Mapped[str] = mapped_column(unique=True)  # sha256; the key itself is never stored
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None]


class WebSession(Base):
    """Login session of the web UI for our own `/api` (cookie). Not used by `/rest`."""

    __tablename__ = "web_session"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(unique=True)  # sha256 of the cookie value
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
