from .init import conn, curs
from model.creature import Creature

curs.execute(       # Создание таблицы creature, если она не существует
    """
    create table if not exists creature(
        name text primary key,
        description text,
        country text,
        area text,
        aka text
    )
    """
)


def row_to_model(row: tuple) -> Creature:       # Функция преобразования строки из БД в объект модели Creature
    (name, description, country, area, aka) = row
    return Creature(name, description, country, area, aka)


def model_to_dict(creature: Creature) -> dict:      # Функция преобразования объекта Creature в словарь
    return creature.dict()


def get_one(name: str) -> Creature:
    qry = "select * from creature where name=:name"
    params = {"name": name}     # Параметры для запроса (словарь с именем)
    curs.execute(qry, params)
    return row_to_model(curs.fetchone())    # Преобразование результата в объект Creature и возврат


def get_all() -> list[Creature]:
    qry = "select * from creature"
    curs.execute(qry)
    return [row_to_model(row) for row in curs.fetchall()]       # Преобразование всех строк в список объектов Creature


def create(creature: Creature) -> Creature:
    qry = (
        "insert into creature values "
        "(:name, :description, :country, :area, :aka)"
    )
    params = model_to_dict(creature)        # Преобразование объекта Creature в словарь параметров
    curs.execute(qry, params)       # Выполнение запроса на вставку
    return get_one(creature.name)       # Возврат созданного существа (читаем из БД для проверки)


def modify(creature: Creature) -> Creature:
    qry = """
    update creature
    set country=:country,
        name=:name,
        description=:description,
        area=:area,
        aka=:aka
    where name=:name_orig
    """
    params = model_to_dict(creature)        # Преобразование объекта в словарь параметров
    params["name_orig"] = creature.name     # Добавляем оригинальное имя для условия WHERE
    curs.execute(qry, params)          # Выполнение запроса на обновление
    return get_one(creature.name)       # Возврат обновленного существа


def delete(creature: Creature) -> bool:
    qry = "delete from creature where name = :name"
    params = {"name": creature.name}        # Параметры запроса (только имя)
    res = curs.execute(qry, params)     # Выполнение запроса и получение результата
    return bool(res)        # Возвращаем True если удаление прошло успешно, иначе False
