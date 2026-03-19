"""add title to live_sessions

Revision ID: 20260319_live_title
Revises: 20260306_add_user_role
Create Date: 2026-03-19
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260319_live_title"
down_revision = "20260306_add_user_role"
branch_labels = None
depends_on = None


TABLE_NAME = "live_sessions"
COLUMN_NAME = "title"


def upgrade():
    op.add_column(
        TABLE_NAME,
        sa.Column(
            COLUMN_NAME,
            sa.String(length=255),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column(TABLE_NAME, COLUMN_NAME)