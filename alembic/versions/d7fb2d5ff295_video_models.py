"""video_models

Revision ID: xxx
Revises: предыдущий_revision_id
Create Date: 2024-...

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "xxx"
down_revision = None  # или предыдущий ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Таблица users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=100), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("storage_limit", sa.BigInteger(), nullable=True),
        sa.Column("used_storage", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_id"), "users", ["id"], unique=False)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    # Таблица videos
    op.create_table(
        "videos",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=500), nullable=True),
        sa.Column("duration", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            sa.Enum("UPLOADING", "UPLOADED", "PROCESSING", "READY", "FAILED", name="videostatus"),
            nullable=True,
        ),
        sa.Column(
            "visibility",
            sa.Enum("PUBLIC", "PRIVATE", "UNLISTED", name="visibility"),
            nullable=True,
        ),
        sa.Column("is_blocked", sa.Boolean(), nullable=True),
        sa.Column("original_path", sa.String(length=1000), nullable=True),
        sa.Column("thumbnail_path", sa.String(length=1000), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),

        # ✅ PR#2: lease/lock для идемпотентности на уровне БД
        sa.Column("processing_lock_token", sa.String(length=36), nullable=True),
        sa.Column("processing_lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),

        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(op.f("ix_videos_id"), "videos", ["id"], unique=False)
    op.create_index(op.f("ix_videos_owner_id"), "videos", ["owner_id"], unique=False)
    op.create_index(op.f("ix_videos_status"), "videos", ["status"], unique=False)
    op.create_index(op.f("ix_videos_uploaded_at"), "videos", ["uploaded_at"], unique=False)
    op.create_index(op.f("ix_videos_visibility"), "videos", ["visibility"], unique=False)

    # индексы для lease/lock
    op.create_index("ix_videos_processing_lock_token", "videos", ["processing_lock_token"], unique=False)
    op.create_index(
        "ix_videos_processing_lock_expires_at",
        "videos",
        ["processing_lock_expires_at"],
        unique=False,
    )

    # Таблица video_formats
    op.create_table(
        "video_formats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column("resolution", sa.String(length=20), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("codec", sa.String(length=20), nullable=True),
        sa.Column("bitrate_kbps", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("is_ready", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_video_formats_id"), "video_formats", ["id"], unique=False)
    op.create_index(op.f("ix_video_formats_is_ready"), "video_formats", ["is_ready"], unique=False)
    op.create_index(op.f("ix_video_formats_video_id"), "video_formats", ["video_id"], unique=False)

    # Таблица processing_tasks
    op.create_table(
        "processing_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("video_id", sa.Integer(), nullable=False),
        sa.Column(
            "task_type",
            sa.Enum("TRANSCODE", "THUMBNAIL", "METADATA", name="processingtasktype"),
            nullable=False,
        ),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PROCESSING", "SUCCESS", "FAILED", name="taskstatus"),
            nullable=True,
        ),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id"),
    )
    op.create_index(op.f("ix_processing_tasks_id"), "processing_tasks", ["id"], unique=False)
    op.create_index(op.f("ix_processing_tasks_status"), "processing_tasks", ["status"], unique=False)
    op.create_index(op.f("ix_processing_tasks_task_type"), "processing_tasks", ["task_type"], unique=False)
    op.create_index(op.f("ix_processing_tasks_video_id"), "processing_tasks", ["video_id"], unique=False)


def downgrade() -> None:
    op.drop_table("processing_tasks")
    op.drop_table("video_formats")
    op.drop_table("videos")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS taskstatus")
    op.execute("DROP TYPE IF EXISTS processingtasktype")
    op.execute("DROP TYPE IF EXISTS visibility")
    op.execute("DROP TYPE IF EXISTS videostatus")
