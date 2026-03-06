# Monitoring

## Что добавлено

В проект добавлен базовый monitoring stack для production-like эксплуатации:

- `/metrics` на HTTP-сервисах:
  - `web`
  - `upload-service`
  - `video-api`
  - `live-api`
  - `identity-service` (после аналогичного патча в `identity/src/main.py`)

- Prometheus metrics endpoint на background-сервисах:
  - `processing-worker`
  - `outbox-publisher`
  - `video-events-consumer`
  - `live-cleaner`

- Prometheus
- Grafana
- базовые alert rules

---

## Основные метрики

### HTTP
- `app_http_requests_total`
- `app_http_request_duration_seconds`
- `app_http_5xx_total`

### Worker
- `app_worker_jobs_in_progress`
- `app_worker_job_duration_seconds`
- `app_worker_job_failures_total`

### Outbox
- `app_outbox_backlog`
- `app_outbox_failed`

### Live
- `app_live_active_sessions`

### Database
- `app_db_pool_checked_out`
- `app_db_pool_connects_total`
- `app_db_errors_total`

---

## Логи и корреляция

Во всех сервисах используются:

- `X-Request-ID`
- `X-Trace-Id`

Они попадают:
- в response headers,
- в application logs,
- в worker / broker logs через contextvars.

Это позволяет связывать:
- входящий HTTP request,
- outbox event,
- RabbitMQ consumer/worker processing,
- DB/processing ошибки.

---

## Запуск

```bash
docker-compose -f docker-compose.ci.yml up -d --build

Prometheus:

http://localhost:9090

Grafana:

http://localhost:3000

login: admin

password: admin

Проверка
HTTP metrics
curl http://localhost:8000/metrics
curl http://localhost:8002/metrics
curl http://localhost:8003/metrics
curl http://localhost:8004/metrics
Worker metrics

Изнутри docker network Prometheus собирает:

processing-worker:9100/metrics

outbox-publisher:9100/metrics

video-events-consumer:9100/metrics

live-cleaner:9100/metrics

Acceptance checklist

Prometheus видит targets в разделе /targets

На HTTP-сервисах доступны /metrics

На background-сервисах доступны metrics endpoints на :9100

Есть HTTP latency / requests / 5xx

Есть outbox backlog

Есть worker jobs in progress / duration / failures

Есть live active sessions

Есть DB pool / DB errors

Есть базовые alert rules


---

# 16. Что нужно сделать в `identity/src/main.py`

Так как файл ты не присылал, даю точный минимум:

1. добавить импорт:

```python
from src.metrics import install_http_metrics

после создания app = FastAPI(...) вызвать:

install_http_metrics(app, "identity-service")

в docker-compose.ci.yml для identity-service уже добавить:

      SERVICE_NAME: identity-service
17. Что в итоге будет покрыто по acceptance

После этих изменений у тебя будет:

/metrics на HTTP сервисах;

Prometheus metrics endpoint на background сервисах;

HTTP latency / requests / 5xx;

outbox backlog;

worker jobs in progress / duration / failures;

live active sessions;

DB pool / errors;

сохранена и использована корреляция логов request_id/trace_id;

prometheus.yml;

compose-блоки prometheus/grafana;

docs/monitoring.md;

базовые alert rules.