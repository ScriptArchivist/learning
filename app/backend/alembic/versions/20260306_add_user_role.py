"""add role to users

Revision ID: 20260306_add_user_role
Revises: 20260305_live_sessions_ttl
Create Date: 2026-03-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260306_add_user_role"
down_revision = "20260305_live_sessions_ttl"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="user",
        ),
    )

    op.create_index(
        "ix_users_role",
        "users",
        ["role"],
    )


def downgrade():
    op.drop_index(
        "ix_users_role",
        table_name="users",
    )

    op.drop_column(
        "users",
        "role",
    )