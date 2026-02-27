"""add live_sessions table

Revision ID: 20260227_add_live_sessions
Revises: outbox_reliability_upgrade
Create Date: 2026-02-27
"""

from alembic import op
import sqlalchemy as sa


# !!! ВАЖНО:
# Replaces: укажи актуальный head revision из alembic/versions (тот, который сейчас самый последний).
revision = "20260227_add_live_sessions"
down_revision = "0fccd4901429"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "live_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stream_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )

    op.create_index("ix_live_sessions_owner_id", "live_sessions", ["owner_id"])
    op.create_index("ix_live_sessions_stream_key", "live_sessions", ["stream_key"], unique=True)
    op.create_index("ix_live_sessions_status", "live_sessions", ["status"])
    op.create_index("ix_live_sessions_created_at", "live_sessions", ["created_at"])


def downgrade():
    op.drop_index("ix_live_sessions_created_at", table_name="live_sessions")
    op.drop_index("ix_live_sessions_status", table_name="live_sessions")
    op.drop_index("ix_live_sessions_stream_key", table_name="live_sessions")
    op.drop_index("ix_live_sessions_owner_id", table_name="live_sessions")
    op.drop_table("live_sessions")