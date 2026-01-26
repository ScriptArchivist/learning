# db/database.py
# Создаем подключение к базе данных

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Строка подключения к PostgreSQL
# Формат: postgresql+драйвер://логин:пароль@хост:порт/название_бд
DATABASE_URL = "postgresql+psycopg://postgres:postgres@db:5432/app"

# 1. СОЗДАЕМ ДВИЖОК (ENGINE) - главный объект для работы с БД
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Проверяет, живое ли соединение перед использованием
)

# 2. СОЗДАЕМ ФАБРИКУ СЕССИЙ (SESSION FACTORY)
# Эта фабрика будет создавать новые сессии БД
SessionLocal = sessionmaker(
    bind=engine,      # Привязываем к нашему движку
    autocommit=False, # Отключаем авто-сохранение (коммиты делаем вручную)
    autoflush=False,  # Отключаем авто-синхронизацию с БД
)

# 3. ФУНКЦИЯ ДЛЯ ПОЛУЧЕНИЯ СЕССИИ
def get_session():
    """
    Эта функция создает и отдает сессию базы данных.
    
    Как работает:
    1. Создаем новую сессию
    2. Отдаем её (yield) тому, кто вызвал функцию
    3. После использования - закрываем сессию
    
    Используется в FastAPI:
    @app.get("/users")
    def get_users(db = Depends(get_session)):
        # здесь db - наша сессия
        users = db.query(User).all()
        return users
    """
    
    # Создаем новую сессию
    db = SessionLocal()
    
    try:
        # Отдаем сессию наружу
        yield db
    finally:
        # Всегда закрываем сессию, даже если была ошибка
        db.close()