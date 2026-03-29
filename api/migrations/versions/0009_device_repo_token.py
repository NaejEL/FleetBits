"""Add repo_token_hash to device.

Stores the SHA-256 hash of a per-device APT repository token.
This token is scoped exclusively to APT package downloads and is
kept separate from device_token_hash (the fleet API bearer token)
so that APT credential compromise does not grant fleet API access.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "device",
        sa.Column("repo_token_hash", sa.Text(), nullable=True),
    )
    op.create_index("ix_device_repo_token_hash", "device", ["repo_token_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_device_repo_token_hash", table_name="device")
    op.drop_column("device", "repo_token_hash")
