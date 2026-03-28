"""Add optional profile_id on device for device-level profile assignment.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device", sa.Column("profile_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_device_profile_id_profile",
        "device",
        "profile",
        ["profile_id"],
        ["profile_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_device_profile_id_profile", "device", type_="foreignkey")
    op.drop_column("device", "profile_id")
