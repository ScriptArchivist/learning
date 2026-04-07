# Service Map

## Текущий full local profile

На текущем этапе полный локальный контур проекта запускается через:

`deploy/docker/docker-compose.ci.yml`

Ниже перечислены сервисы, входящие в полный локальный профиль.

| Сервис | Назначение | Обязателен для full local | Комментарий |
|--------|------------|---------------------------|-------------|
| db-master | основная PostgreSQL БД | да | primary database |
| db-replica | read replica PostgreSQL | да | используется для read/write split |
| rabbitmq | очередь сообщений | да | нужна для event-driven flow |
| redis | кеш / блокировки | да | используется worker'ом |
| migrate | применение миграций Alembic | да | one-shot сервис перед запуском приложения |
| identity-service | сервис аутентификации | да | auth / identity |
| web | основной API | да | основная точка входа |
| live-api | API для live-сценариев | да | live endpoints |
| video-api | API для чтения/получения видео | да | video read API |
| upload-service | загрузка файлов | да | e2e upload flow |
| video-events-consumer | consumer событий | да | обработка video events |
| ingest | RTMP ingest / live intake | да | live video ingest |
| processing-worker | обработка видео | да | ffmpeg / processing |
| outbox-publisher | публикация outbox-событий | да | event publishing |
| dlq-replayer | переотправка DLQ | да | вспомогательный recovery-сервис |
| live-cleaner | очистка live TTL | да | housekeeping для live |
| origin | nginx раздача видео/медиа | да | delivery layer |
| prometheus | сбор метрик | да | monitoring |
| grafana | визуализация метрик | да | dashboards |