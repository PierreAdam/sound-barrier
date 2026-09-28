from datetime import datetime
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, bigint_pk


class Scan(Base):
    __tablename__ = "scan"

    id: Mapped[int] = bigint_pk()
    kind: Mapped[str]  # "full", "quick" or "targeted" (only some folders, e.g. an import)
    status: Mapped[str]  # "running", "done" or "failed"
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]
    # Progress, shown live in the settings page.
    phase: Mapped[str] = mapped_column(server_default=text("'starting'"))  # see scanner
    files_to_read: Mapped[int] = mapped_column(server_default=text("0"))
    files_read: Mapped[int] = mapped_column(server_default=text("0"))
    files_seen: Mapped[int] = mapped_column(server_default=text("0"))
    added: Mapped[int] = mapped_column(server_default=text("0"))
    updated: Mapped[int] = mapped_column(server_default=text("0"))
    removed: Mapped[int] = mapped_column(server_default=text("0"))
    error: Mapped[str | None]


class ServerSetting(Base):
    __tablename__ = "server_setting"

    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
