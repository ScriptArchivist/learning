# Service Map

## Назначение

Документ описывает **полный набор сервисов системы** и их роль в runtime.

Используется как:

* карта системы для разработки;
* карта для DevOps/SRE понимания;
* основа для отладки и эксплуатации.

---

## Full local profile

Полный локальный контур запускается через:

```bash
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml up -d --build
```

Это **production-like окружение**, включающее:

* все API сервисы;
* очередь;
* БД;
* workers;
* ingest;
* monitoring;
* вспомогательные сервисы.

---

## Категории сервисов

### API layer

| Сервис           | Назначение                        |
| ---------------- | --------------------------------- |
| identity-service | аутентификация                    |
| web              | основной API (compatibility слой) |
| video-api        | API для чтения видео и playback   |
| upload-service   | загрузка файлов                   |
| live-api         | управление live streaming         |

👉 Отвечают за входящий HTTP-трафик и контракт с клиентами.

---

### Processing / background

| Сервис                | Назначение                          |
| --------------------- | ----------------------------------- |
| processing-worker     | обработка видео (ffmpeg)            |
| video-events-consumer | обработка доменных событий          |
| outbox-publisher      | публикация событий из БД            |
| live-cleaner          | очистка live TTL                    |
| dlq-replayer          | повторная отправка сообщений из DLQ |

👉 Отвечают за асинхронную обработку и надёжность системы.

---

### Infrastructure

| Сервис     | Назначение             |
| ---------- | ---------------------- |
| db-master  | основная PostgreSQL БД |
| db-replica | read replica           |
| rabbitmq   | очередь сообщений      |
| redis      | cache / locks          |
| migrate    | применение миграций    |

👉 Базовый слой хранения и коммуникации.

---

### Delivery layer

| Сервис | Назначение                |
| ------ | ------------------------- |
| origin | nginx раздача HLS и медиа |
| ingest | RTMP ingest для live      |

👉 Отвечают за доставку контента пользователю.

---

### Observability

| Сервис       | Назначение   |
| ------------ | ------------ |
| prometheus   | сбор метрик  |
| grafana      | визуализация |
| loki         | логирование  |
| promtail     | сбор логов   |
| alertmanager | алерты       |

👉 Обеспечивают наблюдаемость системы.

---

## Полный список сервисов

| Сервис                | Назначение         | Обязателен |
| --------------------- | ------------------ | ---------- |
| db-master             | PostgreSQL primary | да         |
| db-replica            | PostgreSQL replica | да         |
| rabbitmq              | очередь            | да         |
| redis                 | cache/lock         | да         |
| migrate               | миграции           | да         |
| identity-service      | auth               | да         |
| web                   | основной API       | да         |
| live-api              | live API           | да         |
| video-api             | video API          | да         |
| upload-service        | upload flow        | да         |
| video-events-consumer | event processing   | да         |
| ingest                | RTMP ingest        | да         |
| processing-worker     | video processing   | да         |
| outbox-publisher      | event publishing   | да         |
| dlq-replayer          | DLQ recovery       | да         |
| live-cleaner          | housekeeping       | да         |
| origin                | media delivery     | да         |
| prometheus            | metrics            | да         |
| grafana               | dashboards         | да         |

---

## Как это работает вместе

### Upload pipeline

```text
upload-service
  -> PostgreSQL
  -> outbox_events
  -> outbox-publisher
  -> RabbitMQ
  -> processing-worker
  -> storage
  -> video-events-consumer
  -> video-api
```

---

### Live pipeline

```text
live-api
  -> ingest (RTMP)
  -> nginx/origin
  -> HLS playback
```

---

## Надёжность

Система построена с учётом отказов:

* at-least-once delivery;
* retry через RabbitMQ + DLQ;
* outbox pattern;
* lock TTL для worker;
* идемпотентные операции;
* разделение sync и async логики.

---

## Масштабирование

Архитектура допускает масштабирование:

* API сервисы — горизонтально;
* workers — независимо;
* RabbitMQ — буфер нагрузки;
* storage — может быть вынесен в S3;
* Kubernetes deployment через Helm.

---

## Вывод

Service map отражает:

* реальный runtime системы;
* разделение ответственности;
* event-driven архитектуру;
* готовность к облачному деплою;
* ориентацию на DevOps/SRE практики.
