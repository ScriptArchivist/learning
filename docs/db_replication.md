# DB replication: master/replica + read/write splitting

## Цель

На этом этапе добавлена репликация PostgreSQL и разделение read/write нагрузки:

- **master** — все записи и consistency-critical чтения
- **replica** — обычные read-запросы `video-api`

Это снижает нагрузку на master и подготавливает систему к read-heavy сценарию для video-api.

---

## Архитектура

### Роли БД

- `db-master`
  - source of truth
  - все `INSERT/UPDATE/DELETE`
  - миграции Alembic
  - outbox publisher
  - consistent reads

- `db-replica`
  - read-only источник для `video-api`
  - используется для обычных GET-запросов

---

## Конфигурация приложения

Используются два DSN:

- `database_write_url` — master
- `database_read_url` — replica

Если `database_read_url` не задан, приложение читает из master.

---

## SQLAlchemy session routing

В `db/database.py` определены:

- `engine_write`
- `engine_read`
- `SessionLocalWrite`
- `SessionLocalRead`

Dependencies:

- `get_db_write()` — session на master
- `get_db_read()` — session на replica

---

## Read/write splitting в video-api

### Запись
Следующие операции используют **master**:

- `POST /api/v1/videos`

### Чтение
Следующие операции по умолчанию используют **replica**:

- `GET /api/v1/videos`
- `GET /api/v1/videos/{id}`
- `GET /api/v1/videos/{id}/playback`

### Consistent read
Если нужен read-your-write сценарий, используется query-параметр:

- `?consistent=1`

Примеры:

- `GET /api/v1/videos/123?consistent=1`
- `GET /api/v1/videos?consistent=1`

В этом режиме чтение идёт из **master**.

---

## Consistency strategy

Replica может отставать от master.

Поэтому используется следующая стратегия:

- обычные GET → replica
- GET с `consistent=1` → master
- write operations и критичные post-write reads → master

Это позволяет сохранить масштабируемость чтения и при этом избежать проблем "только что создал, но не вижу объект".

---

## Outbox publisher

`outbox-publisher` работает только с **master**:

- выбирает pending events из master
- ставит advisory lock на master
- обновляет статусы outbox events только в master

Использование replica для outbox запрещено.

---

## Compose / local environment

В docker compose поднимаются:

- `db-master`
- `db-replica`

Replica подключается к master и используется только для чтения.

---

## Проверка работы

### 1. Убедиться, что replica поднята

```bash
docker compose -f docker-compose.ci.yml ps