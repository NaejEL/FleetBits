"""Add repository key lifecycle columns to device.

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device", sa.Column("repo_public_key", sa.Text(), nullable=True))
    op.add_column("device", sa.Column("repo_key_fingerprint", sa.Text(), nullable=True))
    op.add_column("device", sa.Column("repo_key_updated_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("device", "repo_key_updated_at")
    op.drop_column("device", "repo_key_fingerprint")
    op.drop_column("device", "repo_public_key")
