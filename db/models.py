# db/models.py
"""
Модели базы данных (SQLAlchemy).
Создают таблицы в PostgreSQL.
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base  # импортируем наш базовый класс

class Explorer(Base):
    """
    Таблица 'explorers' в базе данных.
    Соответствует Pydantic модели Explorer из model/explorer.py
    """
    __tablename__ = "explorers"  # имя таблицы в БД

    # id - добавили для БД (в Pydantic модели его не было)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # name - как в Pydantic модели, но с дополнительными настройками для БД
    name: Mapped[str] = mapped_column(
        String(100),      # макс. 100 символов
        unique=True,      # имена должны быть уникальными
        nullable=False    # поле обязательно для заполнения
    )
    
    # country - как в Pydantic модели
    country: Mapped[str] = mapped_column(
        String(2),        # код страны из 2 букв (например, "US")
        nullable=False    # обязательно
    )
    
    # description - как в Pydantic модели
    description: Mapped[str | None] = mapped_column(
        Text(),           # текст без ограничения длины
        default="",       # значение по умолчанию (как в Pydantic)
        nullable=True     # может быть пустым
    )

    def __repr__(self) -> str:
        """Красивый вывод объекта при печати."""
        return f"<Explorer(id={self.id}, name='{self.name}', country='{self.country}')>"