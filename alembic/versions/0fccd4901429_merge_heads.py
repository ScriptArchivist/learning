"""merge heads

Revision ID: 0fccd4901429
Revises: c1a2b3d4e5f6, outbox_reliability
Create Date: 2026-02-24 10:59:07.646216

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0fccd4901429'
down_revision: Union[str, Sequence[str], None] = ('c1a2b3d4e5f6', 'outbox_reliability')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
