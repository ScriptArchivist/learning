import os       # Импорт модуля для работы с операционной системой (переменные окружения, пути)
from pathlib import Path        # Импорт класса Path для удобной работы с файловыми путями
from sqlite3 import connect, Connection, Cursor, IntegrityError     # Импорт необходимых компонентов из модуля SQLite3

conn: Connection | None = None      # Глобальная переменная для хранения соединения с БД
curs: Cursor | None = None      # Глобальная переменная для хранения курсора БД


def get_db(name: str | None = None, reset: bool = False):       # Функция для инициализации подключения к базе данных, name: опциональный путь к файлу БД (строка или None), reset: флаг принудительного переподключения (по умолчанию False)
    global conn, curs

    if conn:        # Если соединение уже существует...
        if not reset:       # И НЕ запрошен сброс соединения...
            return
        conn = None     # Если запрошен сброс - обнуляем переменную соединения

    if not name:        # Если имя БД не передано в параметрах...
        name = os.getenv("CRYPTID_SQLITE_DB")       # Пытаемся получить путь к БД из переменной окружения
        top_dir = Path(__file__).resolve().parents[1]   # repo top
        db_dir = top_dir / "db"     # Создаем путь к директории с БД (корень_репозитория/db)
        db_name = "cryptid.db"      # Имя файла базы данных
        db_path = str(db_dir / db_name)     # Полный путь к файлу БД (преобразуем в строку)
        name = os.getenv("CRYPTID_SQLITE_DB", db_path)      # Снова проверяем переменную окружения, используя путь по умолчанию

    conn = connect(name, check_same_thread=False)       # Создаем новое соединение с БД SQLite, check_same_thread=False - отключает проверку многопоточности
    curs = conn.cursor()        # Создаем курсор для выполнения SQL-запросов


get_db()        # Вызываем функцию для инициализации подключения к БД
