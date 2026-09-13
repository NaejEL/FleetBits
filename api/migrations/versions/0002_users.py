"""Multi-user support — fleet_user table.

Adds the fleet_user table for real multi-user authentication with
hashed passwords and RBAC roles (admin / operator / technician / viewer / ci_bot).

The single-user OPERATOR_USERNAME/OPERATOR_PASSWORD env-var mode is removed;
the app seeds a first admin user from those env vars on startup when the table
is empty, then the table is authoritative.

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fleet_user",
        sa.Column("user_id", sa.Text, primary_key=True),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False, server_default="viewer"),
        sa.Column("site_scope", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_fleet_user_username", "fleet_user", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_fleet_user_username", table_name="fleet_user")
    op.drop_table("fleet_user")
