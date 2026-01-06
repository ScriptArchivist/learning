from .init import curs, conn, IntegrityError        # Импорт соединения и курсора из модуля init (относительный импорт)
from model.explorer import Explorer     # Импорт модели Explorer из модуля explorer в пакете model
from errors import Missing, Duplicate

curs.execute(       # Создание таблицы explorer, если она не существует
    """
    create table if not exists explorer(
        name text primary key,
        country text,
        description text
    )
    """
)


def row_to_model(row: tuple) -> Explorer:       # Функция преобразования строки из БД в объект модели Explorer
    return Explorer(        # Создаем объект Explorer, распаковывая кортеж row по индексам
        name=row[0],        # Первый элемент - имя
        country=row[1],     # Второй элемент - страна
        description=row[2],     # Третий элемент - описание
    )


def model_to_dict(explorer: Explorer) -> dict:      # Функция преобразования объекта Explorer в словарь
    return explorer.dict() if explorer else None        # Если explorer не None, вызываем метод dict(), иначе возвращаем None


def get_one(name: str) -> Explorer:
    qry = "select * from explorer where name=:name"     # SQL-запрос с именованным параметром :name
    params = {"name": name}     # Параметры для запроса (словарь с именем)
    curs.execute(qry, params)       # Выполнение запроса с параметрами
    row = curs.fetchone()
    if row:
        return row_to_model(row)
    else:
        raise Missing(msg=f"Explorer {name} not found")


def get_all() -> list[Explorer]:
    qry = "select * from explorer"
    curs.execute(qry)
    return [row_to_model(row) for row in curs.fetchall()]       # Преобразование всех строк в список объектов Explorer


def create(explorer: Explorer) -> Explorer:
    if not explorer: return None
    qry = """
    insert into explorer (name, country, description)
    values (:name, :country, :description)
    """
    params = model_to_dict(explorer)        # Преобразование объекта Explorer в словарь параметров
    try:
        curs.execute(qry, params)       # Выполнение запроса на вставку
    except IntegrityError:
        raise Duplicate(msg=f"Eplorer {explorer.name} already exists")
    return get_one(explorer.name)       # Возврат созданного исследователя (читаем из БД для проверки)


def modify(name: str, explorer) -> Explorer:
    if not (name and explorer):
        return None
    if hasattr(explorer, "dict"):        # ← ВОТ КЛЮЧЕВОЕ МЕСТО
        explorer = explorer.dict()
    fields = []
    params = {}
    for key, value in explorer.items():
        fields.append(f"{key} = :{key}")
        params[key] = value
    params["name_orig"] = name
    qry = f"UPDATE explorer SET {', '.join(fields)} WHERE name = :name_orig"
    curs.execute(qry, params)
    if curs.rowcount == 1:
        conn.commit()
        return get_one(params.get("name", name))
    else:
        raise Missing(msg=f"Explorer {name} not found")
    

def replace(name: str, explorer) -> Explorer:
    return modify(name, explorer)


def delete(name: str) -> bool:
    if not name: return False
    qry = "delete from explorer where name = :name"
    params = {"name": name}     # Параметры запроса (только имя)
    curs.execute(qry, params)
    conn.commit()       # Явное подтверждение изменений в БД (commit)
    if curs.rowcount != 1:
        raise Missing(msg=f"Explorer {name} not found")