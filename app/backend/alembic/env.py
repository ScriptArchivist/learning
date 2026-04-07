# alembic/env.py
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

import os
import sys

# Добавляем корень проекта в PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_database_url() -> str:
    """
    Для миграций всегда используем master/write БД.
    Приоритет:
    1. database_write_url
    2. DATABASE_WRITE_URL
    3. DATABASE_URL
    4. sqlalchemy.url из alembic.ini
    5. fallback
    """
    return (
        os.getenv("database_write_url")
        or os.getenv("DATABASE_WRITE_URL")
        or os.getenv("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
        or "postgresql+psycopg://postgres:postgres@db-master:5432/app"
    )


# Явно подменяем URL для Alembic из окружения
config.set_main_option("sqlalchemy.url", get_database_url())


# --- импорт моделей ---
try:
    from db.base import Base
    import db.models  # noqa: F401

    target_metadata = Base.metadata

    print("✅ Модели успешно импортированы")
    print(f"✅ Таблицы для миграции: {list(Base.metadata.tables.keys())}")
    print(f"✅ Alembic DB URL: {get_database_url()}")

except ImportError as e:
    print(f"❌ Ошибка импорта моделей: {e}")
    print("Проверьте пути импорта и структуру проекта")
    target_metadata = None
    raise


def include_object(object, name, type_, reflected, compare_to):
    """
    Фильтр объектов для autogenerate.
    """
    if name and name.startswith("sqlite_"):
        return False
    return True


def process_revision_directives(context, revision, directives):
    """
    Кастомизация генерации миграций.
    """
    if config.cmd_opts and getattr(config.cmd_opts, "autogenerate", False):
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []
            print("ℹ️  Нет изменений в моделях, миграция не создана")


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            include_object=include_object,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()