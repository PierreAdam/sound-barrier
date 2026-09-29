import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, uuid_pk


class WorkerToken(Base):
    """Lets a transcription worker (the companion app, `transcriber/`) take work and send
    transcripts, nothing else: it signs in neither to the web UI nor to the Subsonic API."""

    __tablename__ = "worker_token"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str]
    token_hash: Mapped[str] = mapped_column(unique=True)  # sha256; the token is never stored
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_used_at: Mapped[datetime | None]


class Transcript(TimestampMixin, Base):
    """The text of a podcast episode or an audiobook file, made by a worker (speech to
    text), with its timing: served like synced lyrics (services/transcripts.py).

    A row also tracks the work: "working" (claimed by a worker until `lease_until`, which
    it renews while it works), "done" or "failed".
    """

    __tablename__ = "transcript"

    song_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("song.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str]
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("worker_token.id", ondelete="SET NULL"), index=True
    )
    worker_name: Mapped[str | None]  # kept when the token is revoked
    lease_until: Mapped[datetime | None]
    progress: Mapped[float] = mapped_column(server_default=text("0"))  # 0..1
    model: Mapped[str | None]  # e.g. "whisper large-v3"
    language: Mapped[str | None]  # ISO 639-1, detected or chosen
    # [{"startMs": int, "endMs": int, "text": str, "words": [{"startMs", "text"}] | None}]
    lines: Mapped[list[dict[str, Any]] | None]
    error: Mapped[str | None]
    lrc_written: Mapped[bool] = mapped_column(server_default=text("false"))
