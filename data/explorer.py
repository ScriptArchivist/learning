# data/explorer.py
"""
Data layer для работы с исследователями.
Взаимодействует с PostgreSQL через SQLAlchemy ORM.
"""

from typing import List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

# Импортируем наши модели
from model.explorer import Explorer as PydanticExplorer
from db.models import Explorer as SQLExplorer
from errors import Missing, Duplicate


def row_to_model(row: SQLExplorer) -> PydanticExplorer:
    """
    Преобразует SQLAlchemy объект в Pydantic модель.
    """
    
    if not row:
        return None
    
    return PydanticExplorer(
        name=row.name,
        country=row.country,
        description=row.description or ""  # гарантируем строку, даже если None
    )


def model_to_dict(explorer: PydanticExplorer) -> dict:
    """Преобразует Pydantic модель в словарь."""
    return explorer.dict() if explorer else None


def get_one(db: Session, name: str) -> PydanticExplorer:
    """
    Получает одного исследователя по имени.
    
    Args:
        db: Сессия SQLAlchemy
        name: Имя исследователя
    
    Returns:
        PydanticExplorer объект
    
    Raises:
        Missing: если исследователь не найден
    """
    db_explorer = db.query(SQLExplorer).filter(SQLExplorer.name == name).first()
    
    if db_explorer:
        return row_to_model(db_explorer)
    else:
        raise Missing(msg=f"Explorer {name} not found")
    

def replace(name: str, explorer) -> Explorer:
    return modify(name, explorer)


def get_all(db: Session) -> List[PydanticExplorer]:
    """
    Получает всех исследователей.
    
    Args:
        db: Сессия SQLAlchemy
    
    Returns:
        Список PydanticExplorer объектов
    """
    db_explorers = db.query(SQLExplorer).all()
    return [row_to_model(exp) for exp in db_explorers]


def create(db: Session, explorer: PydanticExplorer) -> PydanticExplorer:
    """
    Создает нового исследователя.
    
    Args:
        db: Сессия SQLAlchemy
        explorer: Pydantic модель исследователя
    
    Returns:
        Созданный PydanticExplorer
    
    Raises:
        Duplicate: если исследователь с таким именем уже существует
    """
    if not explorer:
        return None
    
    # Проверяем, нет ли уже такого имени
    existing = db.query(SQLExplorer).filter(SQLExplorer.name == explorer.name).first()
    if existing:
        raise Duplicate(msg=f"Explorer {explorer.name} already exists")
    
    # Создаем SQLAlchemy объект
    db_explorer = SQLExplorer(
        name=explorer.name,
        country=explorer.country,
        description=explorer.description
    )
    
    try:
        # Добавляем в сессию и коммитим
        db.add(db_explorer)
        db.commit()
        db.refresh(db_explorer)
        
        # Возвращаем Pydantic модель
        return PydanticExplorer(
            name=db_explorer.name,
            country=db_explorer.country,
            description=db_explorer.description or ""
        )
    except IntegrityError as e:
        db.rollback()
        raise Duplicate(msg=f"Explorer {explorer.name} already exists") from e


def modify(db: Session, name: str, explorer_data) -> PydanticExplorer:
    """
    Обновляет данные исследователя.
    
    Args:
        db: Сессия SQLAlchemy
        name: Текущее имя исследователя (для поиска)
        explorer_data: Новые данные (Pydantic модель или dict)
    
    Returns:
        Обновленный PydanticExplorer
    
    Raises:
        Missing: если исследователь не найден
        Duplicate: если новое имя уже занято
    """
    if not (name and explorer_data):
        return None
    
    # Преобразуем входные данные в словарь
    if hasattr(explorer_data, "dict"):
        update_data = explorer_data.dict(exclude_unset=True)  # только переданные поля
    else:
        update_data = explorer_data
    
    # Ищем существующего исследователя
    db_explorer = db.query(SQLExplorer).filter(SQLExplorer.name == name).first()
    if not db_explorer:
        raise Missing(msg=f"Explorer {name} not found")
    
    # Если меняется имя, проверяем уникальность нового имени
    new_name = update_data.get("name")
    if new_name and new_name != name:
        existing = db.query(SQLExplorer).filter(SQLExplorer.name == new_name).first()
        if existing:
            raise Duplicate(msg=f"Explorer {new_name} already exists")
    
    # Обновляем поля
    for key, value in update_data.items():
        if hasattr(db_explorer, key):
            setattr(db_explorer, key, value)
    
    try:
        db.commit()
        db.refresh(db_explorer)
        return row_to_model(db_explorer)
    except IntegrityError as e:
        db.rollback()
        raise Duplicate(msg=f"Update failed for explorer {name}") from e


def replace(db: Session, name: str, explorer: PydanticExplorer) -> PydanticExplorer:
    """
    Полностью заменяет исследователя.
    Если исследователя нет - создает нового.
    """
    try:
        # Пробуем обновить
        return modify(db, name, explorer)
    except Missing:
        # Если не нашли - создаем нового (но с проверкой имени)
        if explorer.name != name:
            raise Missing(msg=f"Cannot replace: name mismatch ({name} != {explorer.name})")
        return create(db, explorer)


def delete(db: Session, name: str) -> bool:
    """
    Удаляет исследователя по имени.
    
    Args:
        db: Сессия SQLAlchemy
        name: Имя исследователя для удаления
    
    Returns:
        True если удалено успешно
    
    Raises:
        Missing: если исследователь не найден
    """
    if not name:
        return False
    
    result = db.query(SQLExplorer).filter(SQLExplorer.name == name).delete()
    db.commit()
    
    if result == 1:
        return True
    else:
        raise Missing(msg=f"Explorer {name} not found")