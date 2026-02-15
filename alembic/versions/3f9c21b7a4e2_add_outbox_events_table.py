"""add outbox events table

Revision ID: 3f9c21b7a4e2
Revises: 90d22c3ea9c6
Create Date: 2026-02-15 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "3f9c21b7a4e2"
down_revision = "90d22c3ea9c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),

        sa.Column("event_type", sa.String(length=200), nullable=False),

        sa.Column("aggregate_type", sa.String(length=50), nullable=True),
        sa.Column("aggregate_id", sa.String(length=100), nullable=True),

        sa.Column("payload", sa.JSON(), nullable=False),

        # ВАЖНО: строковый статус вместо PG enum (устраняет DuplicateObject)
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),

        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),

        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index("ix_outbox_event_type", "outbox_events", ["event_type"])
    op.create_index("ix_outbox_aggregate_type", "outbox_events", ["aggregate_type"])
    op.create_index("ix_outbox_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_status", "outbox_events", ["status"])
    op.create_index("ix_outbox_available_at", "outbox_events", ["available_at"])
    op.create_index(
        "ix_outbox_pending_available",
        "outbox_events",
        ["status", "available_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_pending_available", table_name="outbox_events")
    op.drop_index("ix_outbox_available_at", table_name="outbox_events")
    op.drop_index("ix_outbox_status", table_name="outbox_events")
    op.drop_index("ix_outbox_aggregate_id", table_name="outbox_events")
    op.drop_index("ix_outbox_aggregate_type", table_name="outbox_events")
    op.drop_index("ix_outbox_event_type", table_name="outbox_events")

    op.drop_table("outbox_events")
