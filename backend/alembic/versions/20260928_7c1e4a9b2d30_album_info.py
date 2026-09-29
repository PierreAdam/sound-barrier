"""album info

Revision ID: 7c1e4a9b2d30
Revises: 3f2a9c1d7b64
Create Date: 2026-09-28 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c1e4a9b2d30"
down_revision: str | None = "3f2a9c1d7b64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "album_info",
        sa.Column("album_id", sa.UUID(), nullable=False),
        sa.Column("lastfm_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["album_id"],
            ["album.id"],
            name=op.f("fk_album_info_album_id_album"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("album_id", name=op.f("pk_album_info")),
    )


def downgrade() -> None:
    op.drop_table("album_info")
