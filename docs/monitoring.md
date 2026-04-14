# Monitoring

## Что добавлено

В локальный production-like стенд добавлен monitoring stack со следующими источниками наблюдаемости.

### Мониторятся HTTP-сервисы
- `web`
- `identity-service`
- `upload-service`
- `video-api`
- `live-api`

Для них Prometheus собирает `/metrics`.

### Мониторятся background-сервисы
- `processing-worker`
- `outbox-publisher`
- `video-events-consumer`
- `live-cleaner`

Для них Prometheus собирает metrics endpoint на `:9100/metrics`.

### Мониторятся инфраструктурные и supporting-компоненты
- `rabbitmq`
- `node-exporter`
- `cadvisor`
- `postgres-exporter-master`
- `postgres-exporter-replica`
- `prometheus`
- `grafana`
- `loki`
- `alertmanager`
- `promtail`
- `frontend`

### Исключено из мониторинга
- `redis` — в текущем контуре не мониторится и не рассматривается как источник метрик/алертов.
- `ingest` — отдельный Prometheus scrape target для него не настроен.
- `origin` — отдельный Prometheus scrape target для него не настроен.
- `migrate` — служебный one-shot контейнер, отдельный мониторинг не ведётся.
- `dlq-replayer` — отдельный Prometheus scrape target не настроен.

---

## Основные метрики

Ключевыми в текущем контуре считаются следующие группы метрик.

### HTTP/API
- `app_http_requests_total`
- `app_http_request_duration_seconds`
- `app_http_requests_in_progress`
- `app_http_5xx_total`
- `app_http_exceptions_total`

Используются для контроля:
- доступности API;
- интенсивности трафика;
- p95 latency;
- доли 5xx;
- необработанных исключений.

### Worker / pipeline
- `app_worker_jobs_in_progress`
- `app_worker_job_duration_seconds`
- `app_worker_job_failures_total`
- `app_worker_jobs_total`
- `app_video_processing_total`

Используются для контроля:
- наличия выполняющихся задач;
- длительности обработки;
- количества ошибок;
- факта успешного завершения обработки;
- событий пайплайна обработки видео.

### Outbox / broker / queue
- `app_outbox_backlog`
- `app_outbox_failed`
- `app_broker_consumer_errors_total`
- `rabbitmq_queue_messages_ready`

Используются для контроля:
- накопления backlog в outbox;
- появления failed-событий в outbox;
- ошибок consumer-ов;
- накопления очереди в RabbitMQ.

### Live
- `app_live_active_sessions`

Используется для контроля количества активных live-сессий.

### Database
- `app_db_pool_checked_out`
- `app_db_pool_connects_total`
- `app_db_errors_total`
- `app_db_replica_row_count`
- `app_db_replica_row_count_difference`

Используются для контроля:
- состояния использования DB pool;
- количества подключений;
- ошибок работы с БД;
- расхождения master/replica по контрольной выборке.

### Infra
- `node_cpu_seconds_total`
- `node_memory_MemAvailable_bytes`
- `node_memory_MemTotal_bytes`
- `node_filesystem_avail_bytes`
- `node_filesystem_size_bytes`

Используются для контроля CPU, памяти и диска хоста.

---

## Alerts

В текущем контуре настроены базовые alert rules по следующим направлениям:

- **service health** — падение критичных и supporting сервисов;
- **api symptoms** — высокий 5xx rate, высокий p95 latency, необработанные исключения;
- **worker pipeline** — ошибки worker-а, отсутствие успешных завершений при наличии стартов, высокий p95 duration;
- **queue and outbox** — backlog в RabbitMQ, ошибки consumer-ов, backlog/failed в outbox;
- **database** — DB errors и replica drift;
- **infra** — высокая загрузка CPU, памяти и диска.

Критичными в алертах считаются:
- `web`
- `upload-service`
- `video-api`
- `live-api`
- `identity-service`
- `processing-worker`
- `outbox-publisher`
- `video-events-consumer`
- `rabbitmq`
- `prometheus`
- `grafana`
- `loki`
- `alertmanager`

Supporting-уровнем считаются:
- `live-cleaner`
- `promtail`
- `node-exporter`
- `cadvisor`
- `postgres-exporter-master`
- `postgres-exporter-replica`

---

## Логи и корреляция

Во всех сервисах используются:

- `X-Request-ID`
- `X-Trace-Id`

Они попадают:
- в response headers;
- в application logs;
- в worker / broker logs через `contextvars`.

Это позволяет связывать:
- входящий HTTP request;
- outbox event;
- RabbitMQ consumer/worker processing;
- DB/processing ошибки.

Логи сервисов пайплайна также доступны в Grafana через Loki.

---

## Dashboards

В Grafana используются следующие основные dashboards:

- `Video Platform Overview` — общее состояние сервисов, alerts, API RPS, 5xx, очередь, базовые infra-показатели;
- `Video Platform Pipeline` — состояние processing pipeline, worker, outbox, RabbitMQ и pipeline logs;
- `Video Platform SLO` — вспомогательный dashboard со сводными продуктовыми/процессными графиками.

### Статус раздела SLO
Раздел SLO в текущем состоянии **не является полноценным SLO в SRE-смысле**.

Сейчас dashboard `Video Platform SLO` показывает:
- успешные и failed upload-события;
- события processing pipeline;
- ошибки worker-а;
- количество активных live-сессий;
- 5xx по `live-api`;
- 5xx по `video-api`.

То есть он используется как вспомогательная operational-визуализация, а не как формализованный набор SLI/SLO с error budget.

---

## Запуск

```bash
docker-compose -f deploy/docker/docker-compose.ci.yml up -d --build

Prometheus:

http://localhost:9090

Grafana:

http://localhost:3000

Логин:

admin

Пароль:

admin
Проверка
HTTP metrics
curl http://localhost:8000/metrics
curl http://localhost:8001/metrics
curl http://localhost:8002/metrics
curl http://localhost:8003/metrics
curl http://localhost:8004/metrics
Background metrics

Изнутри docker network Prometheus собирает:

processing-worker:9100/metrics
outbox-publisher:9100/metrics
video-events-consumer:9100/metrics
live-cleaner:9100/metrics
Acceptance checklist
Prometheus видит targets в разделе /targets
на HTTP-сервисах доступны /metrics
на background-сервисах доступны metrics endpoints на :9100
есть HTTP requests / latency / 5xx / exceptions
есть worker jobs in progress / duration / failures / totals
есть outbox backlog / failed
есть RabbitMQ queue metrics
есть live active sessions
есть DB pool / DB errors / replica drift
есть базовые alert rules
есть dashboards Overview / Pipeline / SLO
есть сбор логов через Loki/Promtail