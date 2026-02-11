# alembic/env.py
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

import sys
import os

# --- ВАЖНО: Добавляем путь к вашему проекту ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- ИМПОРТИРУЕМ НАШИ МОДЕЛИ ---
try:
    from db.base import Base
    
    # Устанавливаем метаданные для autogenerate
    target_metadata = Base.metadata
    
    print("✅ Модели успешно импортированы")
    print(f"✅ Таблицы для миграции: {list(Base.metadata.tables.keys())}")
    
except ImportError as e:
    print(f"❌ Ошибка импорта моделей: {e}")
    print("Проверьте пути импорта и структуру проекта")
    target_metadata = None
    raise

# --- НАСТРОЙКИ ДЛЯ AUTOGENERATE (опционально) ---
def include_object(object, name, type_, reflected, compare_to):
    """
    Функция фильтрации объектов для autogenerate.
    Можно исключить определенные таблицы из миграций.
    """
    # Пример: исключить системные таблицы
    if name and name.startswith('sqlite_'):
        return False
    return True

def process_revision_directives(context, revision, directives):
    """
    Кастомизация генерации миграций.
    """
    if config.cmd_opts and config.cmd_opts.autogenerate:
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []
            print("ℹ️  Нет изменений в моделях, миграция не создана")

# --- ФУНКЦИИ МИГРАЦИЙ ---
def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Сравнивать типы колонок
        compare_server_default=True,  # Сравнивать значения по умолчанию
        include_object=include_object,  # Применяем фильтр объектов
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
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