"""transcripts (speech to text of podcasts and audiobooks) and worker tokens

Revision ID: 5a1d9c3e7f42
Revises: c4f7a2e9b815
Create Date: 2026-09-29 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5a1d9c3e7f42"
down_revision: str | None = "c4f7a2e9b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_token",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name=op.f("fk_worker_token_created_by_app_user"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_token")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_worker_token_token_hash")),
    )
    op.create_table(
        "transcript",
        sa.Column("song_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.UUID(), nullable=True),
        sa.Column("worker_name", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("lrc_written", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["song_id"], ["song.id"], name=op.f("fk_transcript_song_id_song"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["worker_id"],
            ["worker_token.id"],
            name=op.f("fk_transcript_worker_id_worker_token"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("song_id", name=op.f("pk_transcript")),
    )
    op.create_index(op.f("ix_transcript_worker_id"), "transcript", ["worker_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_transcript_worker_id"), table_name="transcript")
    op.drop_table("transcript")
    op.drop_table("worker_token")
