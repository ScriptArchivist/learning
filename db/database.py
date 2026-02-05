# db/database.py
# Создаем подключение к базе данных

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# БАЗОВЫЙ КЛАСС ДЛЯ МОДЕЛЕЙ
Base = declarative_base()

# Импортируем настройки из config
try:
    from src.config import settings
    # Используем DATABASE_URL из .env если есть, иначе дефолт
    DATABASE_URL = settings.database_url
except ImportError:
    # Fallback для совместимости
    DATABASE_URL = "postgresql+psycopg://postgres:postgres@db:5432/app"

# 1. СОЗДАЕМ ДВИЖОК (ENGINE) - главный объект для работы с БД
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Проверяет, живое ли соединение перед использованием
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

# 2. СОЗДАЕМ ФАБРИКУ СЕССИЙ (SESSION FACTORY)
# Эта фабрика будет создавать новые сессии БД
SessionLocal = sessionmaker(
    bind=engine,      # Привязываем к нашему движку
    autocommit=False, # Отключаем авто-сохранение (коммиты делаем вручную)
    autoflush=False,  # Отключаем авто-синхронизацию с БД
)

# 3. ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ СЕССИИ
def get_db():
    """
    Эта функция создает и отдает сессию базы данных.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 4. АЛИАС ДЛЯ ОБРАТНОЙ СОВМЕСТИМОСТИ (ДОБАВЛЕНО)
def get_session():
    """
    Алиас для обратной совместимости со старым кодом.
    Используется в web/explorer.py.
    """
    return get_db()