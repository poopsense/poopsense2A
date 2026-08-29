"""add explicitly consented community posts

Revision ID: d82c1a74fe09
Revises: b47f90d2e631
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d82c1a74fe09"
down_revision: Union[str, None] = "b47f90d2e631"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "community_posts",
        sa.Column("id", sa.String(length=100), nullable=False),
        sa.Column("household_id", sa.String(length=100), nullable=False),
        sa.Column("subject_member_id", sa.String(length=100), nullable=False),
        sa.Column("author_user_id", sa.String(length=100), nullable=False),
        sa.Column("agent_alias", sa.String(length=100), nullable=False),
        sa.Column("topic", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("consent_version", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["author_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["household_id"], ["households.id"]),
        sa.ForeignKeyConstraint(["subject_member_id"], ["household_members.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_community_posts_household_id"), "community_posts", ["household_id"])
    op.create_index(op.f("ix_community_posts_subject_member_id"), "community_posts", ["subject_member_id"])
    op.create_index(op.f("ix_community_posts_author_user_id"), "community_posts", ["author_user_id"])
    op.create_index(op.f("ix_community_posts_topic"), "community_posts", ["topic"])
    op.create_index(op.f("ix_community_posts_status"), "community_posts", ["status"])


def downgrade() -> None:
    for name in ["ix_community_posts_status", "ix_community_posts_topic", "ix_community_posts_author_user_id", "ix_community_posts_subject_member_id", "ix_community_posts_household_id"]:
        op.drop_index(name, table_name="community_posts")
    op.drop_table("community_posts")
