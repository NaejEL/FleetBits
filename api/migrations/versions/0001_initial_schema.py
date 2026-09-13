"""Initial schema — all Fleet API tables.

Create the full baseline schema in FK-safe order:
  profile → site → zone → device → service_unit
  → provision_token → deployment → hotfix → override → audit_event

Revision ID: 0001
Revises:
Create Date: 2026-01-01
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # profile
    # ------------------------------------------------------------------
    op.create_table(
        "profile",
        sa.Column("profile_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("baseline_stack", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    )

    # ------------------------------------------------------------------
    # site
    # ------------------------------------------------------------------
    op.create_table(
        "site",
        sa.Column("site_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("timezone", sa.Text, nullable=True),
        sa.Column("quiet_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # ------------------------------------------------------------------
    # zone
    # ------------------------------------------------------------------
    op.create_table(
        "zone",
        sa.Column("zone_id", sa.Text, primary_key=True),
        sa.Column("site_id", sa.Text, sa.ForeignKey("site.site_id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("criticality", sa.Text, nullable=False, server_default="standard"),
        sa.Column("profile_id", sa.Text, sa.ForeignKey("profile.profile_id"), nullable=True),
    )
    op.create_index("ix_zone_site_id", "zone", ["site_id"])

    # ------------------------------------------------------------------
    # device
    # ------------------------------------------------------------------
    op.create_table(
        "device",
        sa.Column("device_id", sa.Text, primary_key=True),
        sa.Column("zone_id", sa.Text, sa.ForeignKey("zone.zone_id"), nullable=True),
        sa.Column("site_id", sa.Text, sa.ForeignKey("site.site_id"), nullable=True),
        sa.Column("shared_zones", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("hostname", sa.Text, nullable=False),
        sa.Column("local_ip", postgresql.INET(), nullable=True),
        sa.Column("headscale_ip", postgresql.INET(), nullable=True),
        sa.Column("os_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_seen", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("agent_version", sa.Text, nullable=True),
        sa.Column("ring", sa.Integer, nullable=True),
        sa.Column("device_token_hash", sa.Text, nullable=True),
    )
    op.create_index("ix_device_zone_id", "device", ["zone_id"])
    op.create_index("ix_device_site_id", "device", ["site_id"])
    op.create_index("ix_device_token_hash", "device", ["device_token_hash"], unique=True)

    # ------------------------------------------------------------------
    # service_unit
    # ------------------------------------------------------------------
    op.create_table(
        "service_unit",
        sa.Column("service_id", sa.Text, primary_key=True),
        sa.Column("device_id", sa.Text, sa.ForeignKey("device.device_id"), nullable=False),
        sa.Column("unit_name", sa.Text, nullable=False),
        sa.Column("current_version", sa.Text, nullable=True),
        sa.Column("state", sa.Text, nullable=True),
        sa.Column("restart_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_failure", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_service_unit_device_id", "service_unit", ["device_id"])

    # ------------------------------------------------------------------
    # provision_token
    # ------------------------------------------------------------------
    op.create_table(
        "provision_token",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("device_id", sa.Text, sa.ForeignKey("device.device_id"), nullable=True),
        sa.Column("allowed_device_ids", postgresql.ARRAY(sa.Text), nullable=True),
        sa.Column("created_by", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # deployment
    # ------------------------------------------------------------------
    op.create_table(
        "deployment",
        sa.Column(
            "deployment_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("artifact_type", sa.Text, nullable=False),
        sa.Column("artifact_ref", sa.Text, nullable=False),
        sa.Column("resolved_commit", sa.Text, nullable=True),
        sa.Column("rollout_mode", sa.Text, nullable=False),
        sa.Column("target_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("change_id", sa.Text, nullable=True),
        sa.Column("requested_by", sa.Text, nullable=False),
        sa.Column("semaphore_job_id", sa.Text, nullable=True),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_deployment_status", "deployment", ["status"])
    op.create_index("ix_deployment_rollout_mode", "deployment", ["rollout_mode"])

    # ------------------------------------------------------------------
    # hotfix
    # ------------------------------------------------------------------
    op.create_table(
        "hotfix",
        sa.Column("hotfix_id", sa.Text, primary_key=True),
        sa.Column("target_scope", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_type", sa.Text, nullable=False),
        sa.Column("artifact_ref", sa.Text, nullable=False),
        sa.Column("resolved_commit", sa.Text, nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("requested_by", sa.Text, nullable=False),
        sa.Column("change_id", sa.Text, nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("recon_policy", sa.Text, nullable=False, server_default="decide-later"),
        sa.Column("reconciled", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("status", sa.Text, nullable=False, server_default="open"),
        sa.Column("semaphore_job_id", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_hotfix_reconciled", "hotfix", ["reconciled"])

    # ------------------------------------------------------------------
    # override
    # ------------------------------------------------------------------
    op.create_table(
        "override",
        sa.Column(
            "override_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("target_id", sa.Text, nullable=False),
        sa.Column("component", sa.Text, nullable=False),
        sa.Column("artifact_type", sa.Text, nullable=False),
        sa.Column("artifact_ref", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("created_by", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("reconciled", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("ix_override_scope_target", "override", ["scope", "target_id"])

    # ------------------------------------------------------------------
    # audit_event  (append-only — no FK constraints to allow orphan events)
    # ------------------------------------------------------------------
    op.create_table(
        "audit_event",
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("actor_role", sa.Text, nullable=True),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip_address", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_event_actor", "audit_event", ["actor"])
    op.create_index("ix_audit_event_created_at", "audit_event", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_device_token_hash", table_name="device")
    op.drop_table("audit_event")
    op.drop_table("override")
    op.drop_table("hotfix")
    op.drop_table("deployment")
    op.drop_table("provision_token")
    op.drop_table("service_unit")
    op.drop_table("device")
    op.drop_table("zone")
    op.drop_table("site")
    op.drop_table("profile")
