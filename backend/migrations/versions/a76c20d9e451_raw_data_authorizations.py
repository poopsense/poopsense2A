"""add raw data authorizations and upload audit

Revision ID: a76c20d9e451
Revises: f04a82b1d963
"""
from alembic import op
import sqlalchemy as sa

revision = "a76c20d9e451"
down_revision = "f04a82b1d963"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_data_authorizations",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("device_id", sa.String(100), sa.ForeignKey("device_bindings.device_id"), nullable=False),
        sa.Column("purpose", sa.String(300), nullable=False),
        sa.Column("data_types", sa.JSON(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("deletion_status", sa.String(30), nullable=False),
        sa.Column("granted_by_user_id", sa.String(100), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in ("household_id", "device_id", "status", "deletion_status", "expires_at"):
        op.create_index(f"ix_raw_data_authorizations_{column}", "raw_data_authorizations", [column])
    op.create_table(
        "raw_data_uploads",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("authorization_id", sa.String(100), sa.ForeignKey("raw_data_authorizations.id"), nullable=False),
        sa.Column("household_id", sa.String(100), sa.ForeignKey("households.id"), nullable=False),
        sa.Column("device_id", sa.String(100), sa.ForeignKey("device_bindings.device_id"), nullable=False),
        sa.Column("object_key", sa.String(200), nullable=False),
        sa.Column("data_type", sa.String(40), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("device_id", "object_key", name="uq_raw_upload_object"),
    )
    for column in ("authorization_id", "household_id", "device_id", "status"):
        op.create_index(f"ix_raw_data_uploads_{column}", "raw_data_uploads", [column])


def downgrade() -> None:
    for column in ("status", "device_id", "household_id", "authorization_id"):
        op.drop_index(f"ix_raw_data_uploads_{column}", table_name="raw_data_uploads")
    op.drop_table("raw_data_uploads")
    for column in ("expires_at", "deletion_status", "status", "device_id", "household_id"):
        op.drop_index(f"ix_raw_data_authorizations_{column}", table_name="raw_data_authorizations")
    op.drop_table("raw_data_authorizations")
