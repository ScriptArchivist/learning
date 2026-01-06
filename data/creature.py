from pydantic import BaseModel
import sqlite3
from errors import Missing, Duplicate    # твои кастомные исключения

# --- Настройка подключения к SQLite ---
conn = sqlite3.connect("database.db")
curs = conn.cursor()

# --- Создание таблицы, если её нет ---
curs.execute("""
CREATE TABLE IF NOT EXISTS creature (
    name TEXT PRIMARY KEY,
    description TEXT,
    country TEXT,
    area TEXT,
    aka TEXT
)
""")
conn.commit()


# --- Модель Pydantic v2 ---
class Creature(BaseModel):
    name: str
    description: str
    country: str
    area: str
    aka: str


# --- Вспомогательные функции ---
def model_to_dict(creature: Creature) -> dict:
    """Конвертация Pydantic-модели в словарь для SQLite."""
    return creature.model_dump()  # Pydantic v2: вместо dict() используем model_dump


def row_to_model(row: tuple) -> Creature:
    """Конвертация строки из БД в объект Creature."""
    if row is None:
        raise Missing("Creature not found")
    name, description, country, area, aka = row
    return Creature.model_construct(
        name=name,
        description=description,
        country=country,
        area=area,
        aka=aka
    )


# --- CRUD функции ---
def create(creature: Creature) -> Creature:
    """Создать новое существо."""
    try:
        curs.execute(
            "INSERT INTO creature (name, description, country, area, aka) VALUES (:name, :description, :country, :area, :aka)",
            model_to_dict(creature)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise Duplicate(f"Creature '{creature.name}' already exists")
    return get_one(creature.name)


def get_one(name: str) -> Creature:
    """Получить одно существо по имени."""
    curs.execute("SELECT name, description, country, area, aka FROM creature WHERE name = ?", (name,))
    row = curs.fetchone()
    return row_to_model(row)


def modify(creature: Creature) -> Creature:
    """Обновить существующее существо."""
    curs.execute(
        "UPDATE creature SET description=:description, country=:country, area=:area, aka=:aka WHERE name=:name",
        model_to_dict(creature)
    )
    conn.commit()
    if curs.rowcount == 0:
        raise Missing(f"Creature '{creature.name}' not found")
    return get_one(creature.name)


def delete(name: str) -> bool:
    """Удалить существо по имени."""
    curs.execute("DELETE FROM creature WHERE name=?", (name,))
    conn.commit()
    if curs.rowcount == 0:
        raise Missing(f"Creature '{name}' not found")
    return True
