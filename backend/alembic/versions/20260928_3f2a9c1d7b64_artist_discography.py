"""artist discography

Revision ID: 3f2a9c1d7b64
Revises: 6d1bc6554fdf
Create Date: 2026-09-28 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3f2a9c1d7b64"
down_revision: str | None = "6d1bc6554fdf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("artist_info", sa.Column("mbz_artist_id_override", sa.Text(), nullable=True))
    op.add_column("artist_info", sa.Column("discography_mbid", sa.Text(), nullable=True))
    op.add_column(
        "artist_info",
        sa.Column(
            "discography",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "artist_info",
        sa.Column(
            "release_groups",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "artist_info",
        sa.Column("discography_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("artist_info", sa.Column("discography_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("artist_info", "discography_error")
    op.drop_column("artist_info", "discography_fetched_at")
    op.drop_column("artist_info", "release_groups")
    op.drop_column("artist_info", "discography")
    op.drop_column("artist_info", "discography_mbid")
    op.drop_column("artist_info", "mbz_artist_id_override")
