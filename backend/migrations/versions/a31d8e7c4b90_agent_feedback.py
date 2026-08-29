"""add agent feedback loop

Revision ID: a31d8e7c4b90
Revises: f28c6d91a4e2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a31d8e7c4b90"
down_revision: Union[str, None] = "f28c6d91a4e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("agent_messages.id"), nullable=False),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("created_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("message_id", "created_by_user_id", name="uq_agent_feedback_message_user"),
    )
    for column in ("message_id", "household_id", "subject_member_id", "created_by_user_id", "rating"):
        op.create_index(f"ix_agent_feedback_{column}", "agent_feedback", [column])


def downgrade() -> None:
    for column in ("rating", "created_by_user_id", "subject_member_id", "household_id", "message_id"):
        op.drop_index(f"ix_agent_feedback_{column}", table_name="agent_feedback")
    op.drop_table("agent_feedback")
