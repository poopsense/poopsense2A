"""persist agent conversations and messages

Revision ID: 7e3a9fd2c1b4
Revises: 0bdff5595b23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7e3a9fd2c1b4"
down_revision: Union[str, None] = "0bdff5595b23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_conversations",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("created_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_conversations_household_id", "agent_conversations", ["household_id"])
    op.create_index("ix_agent_conversations_subject_member_id", "agent_conversations", ["subject_member_id"])
    op.create_index("ix_agent_conversations_created_by_user_id", "agent_conversations", ["created_by_user_id"])
    op.create_index("ix_agent_conversations_status", "agent_conversations", ["status"])
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.String(100), sa.ForeignKey("agent_conversations.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(100), nullable=True),
        sa.Column("authorization_basis", sa.String(200), nullable=False),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("message_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_messages_conversation_id", "agent_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_messages_conversation_id", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("ix_agent_conversations_status", table_name="agent_conversations")
    op.drop_index("ix_agent_conversations_created_by_user_id", table_name="agent_conversations")
    op.drop_index("ix_agent_conversations_subject_member_id", table_name="agent_conversations")
    op.drop_index("ix_agent_conversations_household_id", table_name="agent_conversations")
    op.drop_table("agent_conversations")
