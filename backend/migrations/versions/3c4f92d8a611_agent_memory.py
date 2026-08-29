"""add versioned agent memory

Revision ID: 3c4f92d8a611
Revises: 7e3a9fd2c1b4
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "3c4f92d8a611"
down_revision: Union[str, None] = "7e3a9fd2c1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_memory_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("logical_id", sa.String(100), nullable=False),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("memory_key", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("authored_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("logical_id", "version", name="uq_agent_memory_version"),
    )
    for name, columns in [
        ("ix_agent_memory_entries_logical_id", ["logical_id"]),
        ("ix_agent_memory_entries_household_id", ["household_id"]),
        ("ix_agent_memory_entries_subject_member_id", ["subject_member_id"]),
        ("ix_agent_memory_entries_source_type", ["source_type"]),
        ("ix_agent_memory_entries_active", ["active"]),
    ]:
        op.create_index(name, "agent_memory_entries", columns)


def downgrade() -> None:
    for name in [
        "ix_agent_memory_entries_active", "ix_agent_memory_entries_source_type",
        "ix_agent_memory_entries_subject_member_id", "ix_agent_memory_entries_household_id",
        "ix_agent_memory_entries_logical_id",
    ]:
        op.drop_index(name, table_name="agent_memory_entries")
    op.drop_table("agent_memory_entries")
