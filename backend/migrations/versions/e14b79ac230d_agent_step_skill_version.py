"""add skill version to agent steps

Revision ID: e14b79ac230d
Revises: c7e12a4f905b
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "e14b79ac230d"
down_revision: Union[str, None] = "c7e12a4f905b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_steps", sa.Column("skill_version", sa.String(30), nullable=False, server_default="1.0.0"))


def downgrade() -> None:
    op.drop_column("agent_steps", "skill_version")
