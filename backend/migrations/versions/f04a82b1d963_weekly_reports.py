"""add weekly health reports

Revision ID: f04a82b1d963
Revises: e91b63a0c742
"""
from alembic import op
import sqlalchemy as sa

revision = "f04a82b1d963"
down_revision = "e91b63a0c742"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weekly_health_reports",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False), sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False), sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(50), nullable=False), sa.Column("model_version", sa.String(100), nullable=False),
        sa.Column("created_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("household_id", "subject_member_id", "period_start", name="uq_weekly_report_period"),
    )
    for column in ("household_id", "subject_member_id", "period_start", "status"):
        op.create_index(f"ix_weekly_health_reports_{column}", "weekly_health_reports", [column])


def downgrade() -> None:
    for column in ("status", "period_start", "subject_member_id", "household_id"):
        op.drop_index(f"ix_weekly_health_reports_{column}", table_name="weekly_health_reports")
    op.drop_table("weekly_health_reports")
