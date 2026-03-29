"""Add per-device MQTT credentials.

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("device", sa.Column("mqtt_username", sa.Text(), nullable=True))
    op.add_column("device", sa.Column("mqtt_password_hash", sa.Text(), nullable=True))
    op.add_column("device", sa.Column("mqtt_credentials_issued_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("device", "mqtt_credentials_issued_at")
    op.drop_column("device", "mqtt_password_hash")
    op.drop_column("device", "mqtt_username")
