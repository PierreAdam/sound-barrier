"""Import jobs (Manage Library page). The matching itself is done by a Tagger (see
app/library_manager): these tables only record what was found and what was decided."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, bigint_pk


class ImportJob(Base):
    """One "Import" click: one or more folders to import."""

    __tablename__ = "import_job"

    id: Mapped[int] = bigint_pk()
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL")
    )
    sources: Mapped[list[str]] = mapped_column(JSONB)  # absolute folder paths
    # import: new music copied into the library. adopt: albums already in the library,
    # added to the tagger's database (matched, tags written, files left where they are).
    kind: Mapped[str] = mapped_column(server_default=text("'import'"))
    status: Mapped[str]  # queued, running, done, failed
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class ImportTask(Base):
    """One album folder found by a job, and its matching / decision / result."""

    __tablename__ = "import_task"
    __table_args__ = (Index("ix_import_task_status", "status"),)

    id: Mapped[int] = bigint_pk()
    job_id: Mapped[int] = mapped_column(ForeignKey("import_job.id", ondelete="CASCADE"), index=True)
    source_dir: Mapped[str]
    # queued, analyzing, pending (waits for a decision), applying, imported, skipped, failed
    status: Mapped[str]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # files + tags
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    recommendation: Mapped[str | None]  # strong, medium, low, none
    decision: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # imported paths
    error: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
