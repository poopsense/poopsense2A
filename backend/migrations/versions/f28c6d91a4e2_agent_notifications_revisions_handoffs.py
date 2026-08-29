"""add agent notifications, soul revisions, and structured handoffs

Revision ID: f28c6d91a4e2
Revises: e14b79ac230d
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f28c6d91a4e2"
down_revision: Union[str, None] = "e14b79ac230d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_profile_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Integer(), sa.ForeignKey("agent_profiles.id"), nullable=False),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("changed_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("change_reason", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile_id", "version", name="uq_agent_profile_revision"),
    )
    for column in ("profile_id", "household_id", "subject_member_id"):
        op.create_index(f"ix_agent_profile_revisions_{column}", "agent_profile_revisions", [column])

    op.create_table(
        "agent_handoffs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(100), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("from_step_index", sa.Integer(), nullable=False),
        sa.Column("to_step_index", sa.Integer(), nullable=False),
        sa.Column("from_agent", sa.String(60), nullable=False),
        sa.Column("to_agent", sa.String(60), nullable=False),
        sa.Column("skill_name", sa.String(100), nullable=False),
        sa.Column("skill_version", sa.String(30), nullable=False),
        sa.Column("context_domains", sa.JSON(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("authorization_basis", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "from_step_index", "to_step_index", name="uq_agent_handoff_steps"),
    )
    op.create_index("ix_agent_handoffs_run_id", "agent_handoffs", ["run_id"])
    op.create_index("ix_agent_handoffs_status", "agent_handoffs", ["status"])

    op.create_table(
        "user_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("recipient_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=True),
        sa.Column("agent_action_id", sa.Integer(), sa.ForeignKey("agent_actions.id"), nullable=False, unique=True),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("authorization_basis", sa.String(200), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("household_id", "recipient_user_id", "subject_member_id", "status"):
        op.create_index(f"ix_user_notifications_{column}", "user_notifications", [column])


def downgrade() -> None:
    for column in ("status", "subject_member_id", "recipient_user_id", "household_id"):
        op.drop_index(f"ix_user_notifications_{column}", table_name="user_notifications")
    op.drop_table("user_notifications")
    op.drop_index("ix_agent_handoffs_status", table_name="agent_handoffs")
    op.drop_index("ix_agent_handoffs_run_id", table_name="agent_handoffs")
    op.drop_table("agent_handoffs")
    for column in ("subject_member_id", "household_id", "profile_id"):
        op.drop_index(f"ix_agent_profile_revisions_{column}", table_name="agent_profile_revisions")
    op.drop_table("agent_profile_revisions")
