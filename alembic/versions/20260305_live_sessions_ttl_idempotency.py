"""live sessions ttl + idempotency

Revision ID: 20260305_live_sessions_ttl
Revises: 20260302_add_uploads_table
Create Date: 2026-03-05
"""

from alembic import op
import sqlalchemy as sa


revision = "20260305_live_sessions_ttl"
down_revision = "20260302_add_uploads_table"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("live_sessions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("live_sessions", sa.Column("idempotency_key", sa.String(length=128), nullable=True))
    op.add_column("live_sessions", sa.Column("request_hash", sa.String(length=64), nullable=True))

    op.create_index("ix_live_sessions_expires_at", "live_sessions", ["expires_at"])
    op.create_index("ix_live_sessions_request_hash", "live_sessions", ["request_hash"])
    op.create_index("ux_live_sessions_idempotency_key", "live_sessions", ["idempotency_key"], unique=True)


def downgrade():
    op.drop_index("ux_live_sessions_idempotency_key", table_name="live_sessions")
    op.drop_index("ix_live_sessions_request_hash", table_name="live_sessions")
    op.drop_index("ix_live_sessions_expires_at", table_name="live_sessions")

    op.drop_column("live_sessions", "request_hash")
    op.drop_column("live_sessions", "idempotency_key")
    op.drop_column("live_sessions", "expires_at")