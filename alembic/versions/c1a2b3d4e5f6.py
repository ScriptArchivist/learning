from alembic import op
import sqlalchemy as sa

revision = "c1a2b3d4e5f6"  # <= короткий!
down_revision = "3f9c21b7a4e2"
branch_labels = None
depends_on = None


def upgrade():
    # колонки: IF NOT EXISTS через raw SQL, т.к. alembic op.add_column не умеет IF NOT EXISTS
    op.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS client_upload_id VARCHAR(64)")
    op.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS upload_id VARCHAR(36)")
    op.execute("ALTER TABLE videos ADD COLUMN IF NOT EXISTS upload_etag VARCHAR(64)")

    # индексы
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_videos_owner_client_upload_id "
        "ON videos (owner_id, client_upload_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_videos_upload_id ON videos (upload_id)")


def downgrade():
    # при downgrade IF EXISTS
    op.execute("DROP INDEX IF EXISTS ix_videos_upload_id")
    op.execute("DROP INDEX IF EXISTS ix_videos_owner_client_upload_id")

    op.execute("ALTER TABLE videos DROP COLUMN IF EXISTS upload_etag")
    op.execute("ALTER TABLE videos DROP COLUMN IF EXISTS upload_id")
    op.execute("ALTER TABLE videos DROP COLUMN IF EXISTS client_upload_id")
