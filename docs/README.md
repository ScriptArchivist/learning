src/ # service entrypoints
service/ # бизнес логика
web/ # HTTP API handlers
db/ # database models
model/ # domain models
identity/ # authentication service
ingest/ # streaming ingest + transcoding
alembic/ # database migrations
docs/ # project documentation
tests/ # tests and scripts


---

# Services

| Service | Description |
|------|-------------|
| video-api | API для работы с видео |
| upload-service | загрузка видео |
| live-service | управление live streams |
| worker | background processing |
| outbox publisher | event publishing |
| video events consumer | обработка событий |

---

# Quick Start

## Requirements

- Docker
- Docker Compose
- Python 3.11+

---

## Run locally

```bash
docker compose up --build

Запустятся:

API сервисы

PostgreSQL

ingest nginx

workers

monitoring

Environment

Основные переменные .env:

DATABASE_URL=
JWT_SECRET=
STORAGE_BUCKET=
BROKER_URL=
Database

Используется PostgreSQL.

Миграции управляются через Alembic.

Apply migrations
alembic upgrade head
Create migration
alembic revision --autogenerate -m "message"
API

Основные API:

API	Docs
Auth	docs/api/auth.md
Video	docs/api/video_api.md
Upload	docs/api/upload_service.md
Live	docs/api/live_api.md
Video Pipeline

Видео проходит следующие стадии:

upload
   ↓
queued
   ↓
processing
   ↓
ready

Pipeline:

upload -> storage -> event -> worker -> ffmpeg -> storage -> ready
Live Streaming

Live поток обрабатывается через nginx-rtmp ingest.

Scripts:

ingest/scripts/on_publish.sh
ingest/scripts/on_publish_done.sh

Транскодинг:

ingest/transcode.sh
Events

Используется event-driven architecture.

Основные события:

video_uploaded

video_processing_started

video_ready

video_failed

Документация:

docs/events.md
Monitoring

Метрики:

Prometheus

Конфиги:

prometheus.yml
alerts.yml

Метрики сервисов:

src/metrics.py
Testing

Unit tests:

pytest

Smoke tests:

tests/live_smoke.sh
tests/e2e_video_pipeline.sh
CI/CD

GitLab CI pipeline:

.gitlab-ci.yml

Stages:

lint
test
build
deploy

CI использует:

docker-compose.ci.yml
Workers

Фоновые задачи:

src/worker.py
src/outbox_publisher.py
src/video_events_consumer.py
Useful Scripts

Replay DLQ:

src/dlq_replayer.py

TTL cleaner:

src/live_ttl_cleaner.py
Documentation

Полная документация:

docs/

Основные файлы:

architecture.md

runtime.md

events.md

api_frontend.md

flutter_integration.md