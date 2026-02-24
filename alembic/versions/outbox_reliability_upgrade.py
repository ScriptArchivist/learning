"""upgrade outbox reliability (status, locked_at)

Revision ID: xxxx_outbox_reliability
Revises: 3f9c21b7a4e2
Create Date: 2026-02-24
"""

from alembic import op
import sqlalchemy as sa

revision = "outbox_reliability"
down_revision = "3f9c21b7a4e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Добавляем locked_at
    op.add_column(
        "outbox_events",
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_outbox_status_locked",
        "outbox_events",
        ["status", "locked_at"],
    )

    # 2) Переименуем pending → new
    op.execute(
        "UPDATE outbox_events SET status = 'new' WHERE status = 'pending';"
    )

    op.alter_column(
        "outbox_events",
        "status",
        server_default="new",
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_status_locked", table_name="outbox_events")
    op.drop_column("outbox_events", "locked_at")