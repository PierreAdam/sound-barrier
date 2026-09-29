"""import task: audiobook / podcast review (folders, proposal, lookup)

Revision ID: c4f7a2e9b815
Revises: 9e3c5a7b1d24
Create Date: 2026-09-29 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4f7a2e9b815"
down_revision: str | None = "9e3c5a7b1d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("import_task", sa.Column("spoken", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("import_task", "spoken")
