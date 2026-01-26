#!/usr/bin/env python3
"""
Тестирование PostgreSQL с SQLAlchemy 2.0.
"""

import pytest
import time
import threading
from sqlalchemy import create_engine, Column, Integer, String, Text, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.exc import OperationalError, IntegrityError
from contextlib import contextmanager
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== КОНФИГУРАЦИЯ ====================

# URL для подключения к PostgreSQL
POSTGRES_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/app"

# Создаем базовый класс моделей (SQLAlchemy 2.0 style)
Base = declarative_base()

# Определяем модель для тестирования
class TestCreature(Base):
    """Тестовая модель для проверки работы с PostgreSQL."""
    __tablename__ = "test_creatures"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    sql_query = Column(Text, nullable=False)
    count = Column(Integer, default=0)

# Создаем движок PostgreSQL
try:
    postgres_engine = create_engine(
        POSTGRES_URL,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        echo=False
    )
    
    # Проверяем подключение (используем text() для SQL запросов)
    with postgres_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.commit()
    
    POSTGRES_AVAILABLE = True
    logger.info("✓ PostgreSQL подключен успешно")
    
except OperationalError as e:
    POSTGRES_AVAILABLE = False
    logger.warning(f"✗ PostgreSQL недоступен: {e}")
    logger.info("Запустите PostgreSQL: docker-compose up db")

# Создаем сессию
PostgresSession = sessionmaker(bind=postgres_engine) if POSTGRES_AVAILABLE else None

# ==================== ФИКСТУРЫ ====================

@contextmanager
def get_postgres_session():
    """Контекстный менеджер для сессии PostgreSQL."""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL не доступен")
    
    session = PostgresSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

@pytest.fixture(scope="function")
def postgres_db():
    """Фикстура для тестов PostgreSQL с очисткой данных."""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL не доступен")
    
    # Создаем таблицы
    Base.metadata.create_all(bind=postgres_engine)
    
    with get_postgres_session() as session:
        yield session
    
    # Очищаем таблицы после теста
    with postgres_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f"DELETE FROM {table.name}"))

# ==================== ТЕСТЫ ПОДКЛЮЧЕНИЯ ====================

def test_postgresql_connection():
    """Тест базового подключения к PostgreSQL."""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL не доступен")
    
    with get_postgres_session() as session:
        # Используем text() для SQL запросов
        result = session.execute(text("SELECT version()")).fetchone()
        logger.info(f"Версия PostgreSQL: {result[0]}")
        
        # Проверяем простой запрос
        test_result = session.execute(text("SELECT 1 + 1")).scalar()
        assert test_result == 2
        logger.info("✓ Базовое подключение к PostgreSQL работает")

def test_postgresql_ping():
    """Тест ping-запросов к PostgreSQL."""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL не доступен")
    
    start_time = time.time()
    
    # Выполняем несколько быстрых запросов
    with get_postgres_session() as session:
        for i in range(10):
            result = session.execute(text(f"SELECT {i}")).scalar()
            assert result == i
    
    elapsed = time.time() - start_time
    logger.info(f"✓ 10 ping-запросов выполнены за {elapsed:.3f} секунд")
    assert elapsed < 1.0

# ==================== ТЕСТЫ CRUD ====================

def test_create_record(postgres_db):
    """Тест создания записи в PostgreSQL."""
    # Создаем запись
    creature = TestCreature(
        name="Test Dragon",
        description="A mythical creature for testing",
        sql_query="SELECT * FROM mythical_creatures",
        count=42
    )
    
    postgres_db.add(creature)
    postgres_db.commit()
    
    # Проверяем, что запись сохранена
    saved = postgres_db.query(TestCreature).filter_by(name="Test Dragon").first()
    
    assert saved is not None
    assert saved.name == "Test Dragon"
    assert saved.description == "A mythical creature for testing"
    assert saved.count == 42
    logger.info("✓ Создание записи в PostgreSQL работает")

def test_read_record(postgres_db):
    """Тест чтения записей из PostgreSQL."""
    # Создаем несколько записей
    creatures = [
        TestCreature(name=f"Creature_{i}", sql_query=f"SELECT {i}", count=i)
        for i in range(5)
    ]
    
    postgres_db.add_all(creatures)
    postgres_db.commit()
    
    # Читаем все записи
    all_creatures = postgres_db.query(TestCreature).all()
    assert len(all_creatures) == 5
    
    # Фильтрация
    filtered = postgres_db.query(TestCreature).filter(TestCreature.count > 2).all()
    assert len(filtered) == 2
    
    # Поиск по имени
    found = postgres_db.query(TestCreature).filter_by(name="Creature_3").first()
    assert found.count == 3
    
    logger.info("✓ Чтение записей из PostgreSQL работает")

def test_update_record(postgres_db):
    """Тест обновления записи в PostgreSQL."""
    # Создаем запись
    creature = TestCreature(name="Old Name", sql_query="SELECT 1", count=10)
    postgres_db.add(creature)
    postgres_db.commit()
    
    # Обновляем
    creature.name = "New Name"
    creature.count = 20
    postgres_db.commit()
    
    # Проверяем обновление
    updated = postgres_db.query(TestCreature).filter_by(name="New Name").first()
    assert updated is not None
    assert updated.count == 20
    
    logger.info("✓ Обновление записи в PostgreSQL работает")

def test_delete_record(postgres_db):
    """Тест удаления записи из PostgreSQL."""
    # Создаем запись
    creature = TestCreature(name="To Delete", sql_query="SELECT 1")
    postgres_db.add(creature)
    postgres_db.commit()
    
    # Удаляем
    postgres_db.delete(creature)
    postgres_db.commit()
    
    # Проверяем удаление
    deleted = postgres_db.query(TestCreature).filter_by(name="To Delete").first()
    assert deleted is None
    
    logger.info("✓ Удаление записи из PostgreSQL работает")

# ==================== ТЕСТЫ ТРАНЗАКЦИЙ ====================

def test_transaction_rollback(postgres_db):
    """Тест отката транзакции в PostgreSQL."""
    # Начинаем транзакцию
    creature = TestCreature(name="Will Rollback", sql_query="SELECT 1")
    postgres_db.add(creature)
    postgres_db.flush()  # Сохраняем, но не коммитим
    
    # В текущей сессии видим запись
    in_session = postgres_db.query(TestCreature).filter_by(name="Will Rollback").first()
    assert in_session is not None
    
    # Откатываем
    postgres_db.rollback()
    
    # После отката записи нет
    after_rollback = postgres_db.query(TestCreature).filter_by(name="Will Rollback").first()
    assert after_rollback is None
    
    logger.info("✓ Откат транзакции в PostgreSQL работает")

# ==================== ТЕСТЫ ОГРАНИЧЕНИЙ ====================

def test_unique_constraint(postgres_db):
    """Тест ограничения уникальности в PostgreSQL."""
    # Создаем первую запись
    creature1 = TestCreature(name="Unique Name", sql_query="SELECT 1")
    postgres_db.add(creature1)
    postgres_db.commit()
    
    # Пытаемся создать вторую с таким же именем
    creature2 = TestCreature(name="Unique Name", sql_query="SELECT 2")
    postgres_db.add(creature2)
    
    # Должно вызвать исключение
    with pytest.raises(IntegrityError):
        postgres_db.commit()
    
    postgres_db.rollback()
    logger.info("✓ Ограничение уникальности в PostgreSQL работает")

# ==================== ТЕСТЫ ПРОИЗВОДИТЕЛЬНОСТИ ====================

def test_bulk_insert_performance(postgres_db):
    """Тест производительности массовой вставки в PostgreSQL."""
    import time
    
    # Тест массовой вставки
    start_time = time.time()
    
    batch_size = 100
    creatures = [
        TestCreature(
            name=f"Bulk_{i}",
            description=f"Description for bulk item {i}",
            sql_query=f"SELECT {i % 10}",
            count=i
        )
        for i in range(batch_size)
    ]
    
    # Используем bulk_save_objects для массовой вставки
    postgres_db.bulk_save_objects(creatures)
    postgres_db.commit()
    
    elapsed = time.time() - start_time
    
    # Проверяем, что все записи вставлены
    count = postgres_db.query(TestCreature).count()
    assert count == batch_size
    
    logger.info(f"✓ Массовая вставка {batch_size} записей: {elapsed:.3f} секунд")
    logger.info(f"  Скорость: {batch_size/elapsed:.1f} записей/сек")

# ==================== ТЕСТЫ КОНКУРЕНТНОСТИ ====================

def test_concurrent_connections():
    """Тест нескольких одновременных подключений к PostgreSQL."""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL не доступен")
    
    results = []
    errors = []
    
    def query_worker(worker_id):
        """Воркер для выполнения запросов."""
        try:
            with get_postgres_session() as session:
                # Выполняем несколько запросов
                for i in range(3):
                    result = session.execute(text(f"SELECT {worker_id * 10 + i}")).scalar()
                    time.sleep(0.01)  # Имитация работы
                    results.append((worker_id, i, result))
        except Exception as e:
            errors.append((worker_id, str(e)))
    
    # Запускаем 5 воркеров одновременно
    threads = []
    for i in range(5):
        t = threading.Thread(target=query_worker, args=(i,))
        threads.append(t)
        t.start()
    
    # Ждем завершения всех потоков
    for t in threads:
        t.join()
    
    # Проверяем результаты
    assert len(errors) == 0, f"Были ошибки: {errors}"
    assert len(results) == 5 * 3  # 5 воркеров * 3 запроса каждый
    
    logger.info(f"✓ Конкурентные подключения: {len(threads)} потоков выполнены успешно")
    logger.info(f"  Всего выполнено запросов: {len(results)}")

# ==================== ОСНОВНАЯ ФУНКЦИЯ ====================

def test_postgresql_full_cycle():
    """Полный цикл тестирования PostgreSQL в одном тесте."""
    if not POSTGRES_AVAILABLE:
        pytest.skip("PostgreSQL не доступен")
    
    with get_postgres_session() as session:
        # 1. Создание таблиц
        Base.metadata.create_all(bind=postgres_engine)
        
        # 2. Создание записи
        creature = TestCreature(
            name="Full Cycle Test",
            description="Testing full PostgreSQL cycle",
            sql_query="SELECT * FROM test",
            count=100
        )
        session.add(creature)
        session.commit()
        
        # 3. Чтение записи
        saved = session.query(TestCreature).filter_by(name="Full Cycle Test").first()
        assert saved is not None
        assert saved.count == 100
        
        # 4. Обновление записи
        saved.count = 200
        session.commit()
        
        updated = session.query(TestCreature).filter_by(name="Full Cycle Test").first()
        assert updated.count == 200
        
        # 5. Удаление записи
        session.delete(updated)
        session.commit()
        
        # 6. Проверка удаления
        deleted = session.query(TestCreature).filter_by(name="Full Cycle Test").first()
        assert deleted is None
        
        logger.info("✓ Полный цикл CRUD PostgreSQL работает корректно")

if __name__ == "__main__":
    # Запуск тестов
    pytest.main([__file__, "-v"])