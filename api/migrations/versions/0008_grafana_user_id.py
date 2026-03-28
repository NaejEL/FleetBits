"""Add grafana_user_id to fleet_user.

Stores the Grafana numeric user ID so the provisioner can update/delete
Grafana accounts when FleetBits users change role, scope, or are deactivated.

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "fleet_user",
        sa.Column("grafana_user_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fleet_user", "grafana_user_id")
