"""add read-only health pet profiles and checkins

Revision ID: b47f90d2e631
Revises: a31d8e7c4b90
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b47f90d2e631"
down_revision: Union[str, None] = "a31d8e7c4b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pet_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("selected_skin", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("household_id", "subject_member_id", name="uq_pet_profile_member"),
    )
    op.create_index("ix_pet_profiles_household_id", "pet_profiles", ["household_id"])
    op.create_index("ix_pet_profiles_subject_member_id", "pet_profiles", ["subject_member_id"])
    op.create_table(
        "pet_checkins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("subject_member_id", sa.String(100), sa.ForeignKey("household_members.id"), nullable=False),
        sa.Column("checkin_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("created_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("household_id", "subject_member_id", "checkin_date", name="uq_pet_daily_checkin"),
    )
    for column in ("household_id", "subject_member_id", "checkin_date", "created_by_user_id"):
        op.create_index(f"ix_pet_checkins_{column}", "pet_checkins", [column])


def downgrade() -> None:
    for column in ("created_by_user_id", "checkin_date", "subject_member_id", "household_id"):
        op.drop_index(f"ix_pet_checkins_{column}", table_name="pet_checkins")
    op.drop_table("pet_checkins")
    op.drop_index("ix_pet_profiles_subject_member_id", table_name="pet_profiles")
    op.drop_index("ix_pet_profiles_household_id", table_name="pet_profiles")
    op.drop_table("pet_profiles")
