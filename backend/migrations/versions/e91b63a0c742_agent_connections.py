"""add mutual consent agent connections

Revision ID: e91b63a0c742
Revises: d82c1a74fe09
"""
from alembic import op
import sqlalchemy as sa

revision = "e91b63a0c742"
down_revision = "d82c1a74fe09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_connections",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("initiator_household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("initiator_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("target_household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("target_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("initiator_alias", sa.String(100), nullable=False),
        sa.Column("target_alias", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("consent_version", sa.String(30), nullable=False),
        sa.Column("created_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("responded_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("initiator_household_id", "initiator_member_id", "target_household_id", "target_member_id", "status"):
        op.create_index(f"ix_agent_connections_{column}", "agent_connections", [column])


def downgrade() -> None:
    for column in ("status", "target_member_id", "target_household_id", "initiator_member_id", "initiator_household_id"):
        op.drop_index(f"ix_agent_connections_{column}", table_name="agent_connections")
    op.drop_table("agent_connections")
