# Architecture

## Общее описание

Проект представляет собой **backend-видеоплатформу** на FastAPI с микросервисной архитектурой.

Система поддерживает:

* VOD upload (загрузка видео);
* асинхронную обработку видео;
* HLS playback;
* live streaming;
* event-driven взаимодействие между сервисами;
* monitoring через Prometheus/Grafana/Loki.

Проект реализован как **production-like система**, пригодная для локального и облачного запуска.

---

## High-level архитектура

```text
Clients (Web / Flutter)
        |
        | HTTP API
        v
+-------------------------+
|      API Layer          |
|-------------------------|
| identity-service        |
| video-api               |
| upload-service          |
| live-api                |
| web (compatibility)     |
+-------------------------+
        |
        +----------------------+
        |                      |
        v                      v
   PostgreSQL            RabbitMQ / Redis
   (master / replica)         |
                              v
                      Background services
                      - processing-worker
                      - outbox-publisher
                      - video-events-consumer
                      - live-cleaner
        |
        v
   origin / nginx
   HLS / static delivery
```

---

## Основные сервисы

### identity-service

Отвечает за аутентификацию пользователей.

* проверка логина/пароля
* выдача токенов

---

### video-api

Основной API для клиента.

Функции:

* создание видео
* получение списка видео
* получение карточки видео
* получение playback-данных

Важно:

* не принимает файлы
* не выполняет обработку
* не раздаёт HLS напрямую

---

### upload-service

Сервис загрузки файлов.

Функции:

* init upload
* загрузка файла
* завершение upload
* публикация события

---

### live-api

Сервис live streaming.

Функции:

* создание live session
* получение состояния
* остановка session

---

### web (compatibility layer)

Legacy-слой для:

* старых endpoint’ов
* тестов
* обратной совместимости

---

## Background сервисы

### processing-worker

* обработка видео через ffmpeg
* формирование HLS

---

### outbox-publisher

* публикация событий из PostgreSQL (outbox)
* обеспечивает надёжную доставку в RabbitMQ

---

### video-events-consumer

* обработка доменных событий
* обновление статусов видео

---

### live-cleaner

* очистка live-сессий по TTL

---

## Основные потоки

### 1. VOD upload flow

```text
Client
  -> identity-service (login)
  -> video-api (create video)
  -> upload-service (init/upload/complete)
  -> outbox -> RabbitMQ
  -> processing-worker
  -> video-events-consumer
  -> video-api (status/playback)
```

---

### 2. Playback flow

```text
Client
  -> video-api
  -> origin/nginx (HLS)
```

---

### 3. Live flow

```text
Client
  -> live-api (create session)
  -> ingest (RTMP)
  -> nginx (HLS)
  -> live-api (stop session)
```

---

## Хранилище и данные

### PostgreSQL

Используется для:

* пользователей
* видео
* uploads
* live sessions
* outbox events
* processing metadata

Режим:

* master — запись
* replica — чтение

---

### RabbitMQ

Используется для:

* доменных событий
* асинхронной обработки
* video pipeline

---

### Redis

Используется для:

* lock
* cache
* временные состояния

---

### Storage

Текущая реализация использует абстракцию storage provider.

Поддерживаются:

* локальное файловое хранилище (используется сейчас);
* S3-совместимое хранилище (планируется для cloud deployment).

В локальном профиле используются:

* оригиналы видео;
* HLS output;
* thumbnails;
* live output.

В cloud/demo-профиле предполагается переход на:

* S3-compatible storage (например, Yandex Object Storage / AWS S3);
* генерацию presigned URL для upload/download;
* отделение compute (workers) от storage.

Это позволяет:

* масштабировать обработку;
* упростить Kubernetes deployment;
* избежать привязки к локальному volume.

---

## Event-driven архитектура

Система построена вокруг событий:

* upload завершён
* processing запрошен
* processing завершён / failed

Особенности:

* transactional outbox
* at-least-once delivery
* retry/backoff
* идемпотентные consumer-ы

Подробнее:

```text
docs/events.md
```

---

## Monitoring

В систему встроен observability-стек:

* Prometheus — метрики
* Grafana — визуализация
* Loki — логи
* Alertmanager — алерты

Собираются:

* HTTP метрики
* worker метрики
* очередь
* БД
* инфраструктура

---

## Особенности реализации

### Transactional outbox

* события сначала пишутся в БД
* затем публикуются
* нет потери событий

---

### Idempotency

* upload через `client_upload_id`
* processing через lock token
* защита от повторной доставки

---

### Correlation

Используются:

* `X-Request-ID`
* `X-Trace-Id`

Они проходят через:

* HTTP layer
* outbox
* RabbitMQ
* worker

---

## Вывод

Система представляет собой:

* микросервисную backend-платформу
* с асинхронной обработкой
* event-driven архитектурой
* production-like поведением
* полной поддержкой DevOps/SRE практик

и может использоваться как:

* основа для реального продукта
* демонстрация инженерного уровня
