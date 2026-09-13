"""Add JWT revocation support.

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fleet_user", sa.Column("token_valid_after", sa.TIMESTAMP(timezone=True), nullable=True))

    op.create_table(
        "revoked_jwt",
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column("sub", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("jti"),
    )

    op.create_index("ix_revoked_jwt_expires_at", "revoked_jwt", ["expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_revoked_jwt_expires_at", table_name="revoked_jwt")
    op.drop_table("revoked_jwt")
    op.drop_column("fleet_user", "token_valid_after")
