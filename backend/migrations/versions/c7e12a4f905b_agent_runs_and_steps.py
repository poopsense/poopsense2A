"""add persistent agent runs and steps

Revision ID: c7e12a4f905b
Revises: 9f83a1d2b6c0
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c7e12a4f905b"
down_revision: Union[str, None] = "9f83a1d2b6c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=True),
        sa.Column("conversation_id", sa.String(100), sa.ForeignKey("agent_conversations.id"), nullable=True),
        sa.Column("trigger", sa.String(40), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("max_steps", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("policy_version", sa.String(50), nullable=False),
        sa.Column("authorization_basis", sa.String(200), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_agent_runs_household_id", "agent_runs", ["household_id"])
    op.create_index("ix_agent_runs_subject_member_id", "agent_runs", ["subject_member_id"])
    op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_table(
        "agent_steps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(100), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("agent_name", sa.String(60), nullable=False),
        sa.Column("skill_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("input_summary", sa.JSON(), nullable=False),
        sa.Column("output_summary", sa.JSON(), nullable=False),
        sa.Column("authorization_basis", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("run_id", "step_index", name="uq_agent_run_step"),
    )
    op.create_index("ix_agent_steps_run_id", "agent_steps", ["run_id"])
    op.create_index("ix_agent_steps_status", "agent_steps", ["status"])


def downgrade() -> None:
    op.drop_index("ix_agent_steps_status", table_name="agent_steps")
    op.drop_index("ix_agent_steps_run_id", table_name="agent_steps")
    op.drop_table("agent_steps")
    for name in ["ix_agent_runs_status", "ix_agent_runs_conversation_id",
                 "ix_agent_runs_subject_member_id", "ix_agent_runs_household_id"]:
        op.drop_index(name, table_name="agent_runs")
    op.drop_table("agent_runs")
