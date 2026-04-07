"""add uploads table

Revision ID: 20260302_add_uploads_table
Revises: 20260227_add_live_sessions
Create Date: 2026-03-02
"""

from alembic import op
import sqlalchemy as sa


revision = "20260302_add_uploads_table"
down_revision = "20260227_add_live_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("video_id", sa.Integer(), sa.ForeignKey("videos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_key", sa.String(length=1000), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=True),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_uploads_video_id", "uploads", ["video_id"])
    op.create_index("ix_uploads_owner_id", "uploads", ["owner_id"])
    op.create_index("ix_uploads_status", "uploads", ["status"])


def downgrade():
    op.drop_index("ix_uploads_status", table_name="uploads")
    op.drop_index("ix_uploads_owner_id", table_name="uploads")
    op.drop_index("ix_uploads_video_id", table_name="uploads")
    op.drop_table("uploads")