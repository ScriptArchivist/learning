# Architecture

## Назначение проекта

Проект представляет собой backend-видеоплатформу на FastAPI с поддержкой:

- VOD upload
- асинхронной обработки видео
- HLS playback
- live streaming
- event-driven взаимодействия между сервисами
- мониторинга через Prometheus/Grafana

Основная цель текущего этапа — предоставить стабильный backend-контракт для клиентского приложения, в первую очередь для Flutter.

---

## High-level схема

```text
Clients (Flutter / Web)
        |
        | HTTP
        v
+-------------------+
|  API services     |
|-------------------|
| identity-service  |
| video-api         |
| upload-service    |
| live-api          |
| web (legacy/compat)
+-------------------+
        |
        +--------------------+
        |                    |
        v                    v
   PostgreSQL           RabbitMQ / Redis
(master + replica)          |
                             v
                    background services
                    - processing-worker
                    - outbox-publisher
                    - video-events-consumer
                    - live-cleaner

        |
        v
   origin / nginx
   HLS / static delivery


Сервисы
1. identity-service

Отвечает за аутентификацию.

Сейчас реализовано:

POST /auth/login

Назначение:

проверить логин/пароль

вернуть токен/данные авторизации (в фактическом формате сервиса)

2. video-api

Сервис для клиента Flutter.

Основные задачи:

создание записи видео

получение списка видео

получение карточки видео

получение playback-данных

Основные endpoints:

POST /videos

GET /videos

GET /videos/{id}

GET /videos/{id}/playback

Важно:

video-api не принимает сам бинарный файл

video-api не делает ffmpeg-обработку

video-api не раздаёт HLS-сегменты

3. upload-service

Отдельный сервис загрузки файлов.

Основные задачи:

инициализировать upload

принять файл

завершить upload и опубликовать событие

Основные endpoints:

POST /uploads/init

POST /uploads/{upload_id}/file

POST /uploads/{upload_id}/complete

4. live-api

Сервис live streaming.

Основные задачи:

создать live session

получить live session

остановить live session

Основные endpoints:

POST /live/sessions

GET /live/sessions/{stream_key}

DELETE /live/sessions/{session_id}

5. web (legacy / compatibility layer)

web содержит совместимые endpoints из монолитного слоя.

Он важен для:

старых тестов

локального режима

обратной совместимости

Пример:

POST /videos/upload/prepare

POST /videos/{id}/upload/direct

POST /videos/{id}/upload/complete

share endpoints

Для нового Flutter-клиента рекомендуется ориентироваться в первую очередь на:

identity-service

video-api

upload-service

live-api

А compatibility endpoints использовать только если это отдельно согласовано.

Основные потоки
1. VOD upload flow
Flutter
  -> identity-service: login
  -> video-api: create metadata or create/list videos
  -> upload-service: init upload
  -> upload-service: upload file
  -> upload-service: complete upload
  -> processing-worker: async processing
  -> video-events-consumer: status update
  -> video-api: poll status / playback
2. VOD playback flow
Flutter
  -> video-api: GET /videos/{id}
  -> video-api: GET /videos/{id}/playback
  -> origin/nginx: HLS playlist + segments
3. Live flow
Flutter
  -> live-api: create session
  -> ingest: RTMP ingest by stream_key
  -> origin/nginx: HLS live playback
  -> live-api: stop session
Хранилище и данные
PostgreSQL

Используется для:

пользователей

видео

uploads

live sessions

outbox events

processing metadata

Схема чтения/записи:

master — write

replica — read

RabbitMQ

Используется для:

событий upload/process/live

асинхронной обработки видео

Redis

Используется для:

вспомогательных механизмов

lock / cache / временных состояний

Storage

Сейчас используется local storage.

В нём хранятся:

оригиналы файлов

HLS output

thumbnails

live HLS output

Переход на S3 planned, но не является обязательным для Flutter MVP в домашней сети.

Monitoring

Добавлены:

Prometheus

Grafana

/metrics endpoints

метрики API / worker / DB / outbox / live

Это важно для эксплуатации и диагностики, но Flutter-клиент напрямую с monitoring не взаимодействует.

Что важно для Flutter

Flutter-клиент должен быть построен так, чтобы не зависеть от внутренней docker-сети.

Рекомендуемый подход:

настраиваемый baseUrl

отдельный конфиг окружений:

local emulator

home LAN

public URL

клиент использует только публичные HTTP endpoints

клиент не должен знать адреса контейнеров вроде video-api:8000

Вывод

На текущем этапе backend уже позволяет реализовать Android Flutter MVP для сценариев:

login

список видео

карточка видео

upload файла

ожидание обработки

playback HLS

start/stop live

playback live HLS




