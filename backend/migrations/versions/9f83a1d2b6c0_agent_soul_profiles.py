"""add agent soul profiles

Revision ID: 9f83a1d2b6c0
Revises: 3c4f92d8a611
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "9f83a1d2b6c0"
down_revision: Union[str, None] = "3c4f92d8a611"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("soul", sa.JSON(), nullable=False),
        sa.Column("proactive_enabled", sa.Boolean(), nullable=False),
        sa.Column("daily_non_redline_limit", sa.Integer(), nullable=False),
        sa.Column("quiet_start", sa.String(5), nullable=False),
        sa.Column("quiet_end", sa.String(5), nullable=False),
        sa.Column("timezone", sa.String(60), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("household_id", "subject_member_id", name="uq_agent_profile_scope"),
    )
    op.create_index("ix_agent_profiles_household_id", "agent_profiles", ["household_id"])
    op.create_index("ix_agent_profiles_subject_member_id", "agent_profiles", ["subject_member_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_profiles_subject_member_id", table_name="agent_profiles")
    op.drop_index("ix_agent_profiles_household_id", table_name="agent_profiles")
    op.drop_table("agent_profiles")
