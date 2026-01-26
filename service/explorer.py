# service/explorer.py
"""
Service layer для исследователей.
Обрабатывает бизнес-логику и делегирует работу с данными в data-слой.
"""

from typing import List
from sqlalchemy.orm import Session

from model.explorer import Explorer
import data.explorer as data


def get_all(db: Session) -> List[Explorer]:
    """
    Получить всех исследователей.
    
    Args:
        db: Сессия SQLAlchemy для работы с БД
    
    Returns:
        Список всех исследователей
    """
    return data.get_all(db)


def get_one(db: Session, name: str) -> Explorer:
    """
    Получить одного исследователя по имени.
    
    Args:
        db: Сессия SQLAlchemy
        name: Имя исследователя
    
    Returns:
        Объект Explorer или вызывает исключение Missing
    """
    return data.get_one(db, name)


def create(db: Session, explorer: Explorer) -> Explorer:
    """
    Создать нового исследователя.
    
    Args:
        db: Сессия SQLAlchemy
        explorer: Данные нового исследователя
    
    Returns:
        Созданный исследователь
    
    Raises:
        Duplicate: если исследователь с таким именем уже существует
    """
    return data.create(db, explorer)


def replace(db: Session, name: str, explorer: Explorer) -> Explorer:
    """
    Полностью заменить исследователя.
    Если не найден - создает нового.
    
    Args:
        db: Сессия SQLAlchemy
        name: Имя исследователя для замены
        explorer: Новые данные
    
    Returns:
        Обновленный или созданный исследователь
    """
    return data.replace(db, name, explorer)


def modify(db: Session, name: str, explorer: Explorer) -> Explorer:
    """
    Частично обновить данные исследователя.
    
    Args:
        db: Сессия SQLAlchemy
        name: Имя исследователя для обновления
        explorer: Данные для обновления (только измененные поля)
    
    Returns:
        Обновленный исследователь
    """
    return data.modify(db, name, explorer)


def delete(db: Session, name: str) -> bool:
    """
    Удалить исследователя по имени.
    
    Args:
        db: Сессия SQLAlchemy
        name: Имя исследователя для удаления
    
    Returns:
        True если удалено успешно
    
    Raises:
        Missing: если исследователь не найден
    """
    return data.delete(db, name)