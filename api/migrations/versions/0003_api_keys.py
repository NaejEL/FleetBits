"""Add api_key table for CI bots and service account tokens.

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("key_id", sa.Text, primary_key=True),
        sa.Column("key_name", sa.Text, nullable=False),
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("site_scope", sa.Text, nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_api_key_name", "api_key", ["key_name"], unique=True)
    op.create_index("ix_api_key_token_hash", "api_key", ["token_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_api_key_token_hash", table_name="api_key")
    op.drop_index("ix_api_key_name", table_name="api_key")
    op.drop_table("api_key")
