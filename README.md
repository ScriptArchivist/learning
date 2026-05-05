# Video Platform DevOps Project

Production-like видеоплатформа на FastAPI с микросервисной backend-архитектурой, асинхронной обработкой видео, очередями, Kubernetes/Helm-деплоем и observability-стеком.

Проект является **реально работающей системой**, поддерживающей web (Next.js) и mobile (Flutter) клиентов, и используется как демонстрация DevOps/SRE-подхода к разработке backend-платформы.

---

## Цель проекта

Показать полный цикл разработки и эксплуатации backend-системы:

* FastAPI backend с разделением на сервисы;
* загрузка и обработка видео;
* event-driven взаимодействие через RabbitMQ;
* transactional outbox pattern;
* идемпотентность и retry-механизмы;
* Docker / Docker Compose для локального полного стенда;
* Kubernetes / Helm для cloud demo-profile;
* Prometheus / Grafana / Loki / Alertmanager для observability;
* GitLab CI/CD pipeline для проверки, сборки и security scan.

---

## Что это за проект

Это не просто pet-проект, а **production-like система**, в которой:

* реализован полный video pipeline (upload → processing → playback);
* система может быть развернута локально полностью;
* есть облачный demo-профиль через Kubernetes/Helm;
* есть наблюдаемость, retry-механизмы и обработка ошибок;
* клиенты (web + mobile) могут реально работать с API.

---

## Cloud-ready design

Архитектура проекта изначально спроектирована с учётом облачного деплоя и масштабирования.

### Stateless сервисы

* API и worker сервисы не хранят состояние локально;
* состояние вынесено в PostgreSQL / RabbitMQ / Redis;
* позволяет масштабировать сервисы горизонтально.

---

### Storage abstraction

* используется абстракция storage provider;
* текущая реализация — локальное файловое хранилище;
* для cloud deployment предусмотрен переход на S3-compatible storage:

  * AWS S3 / Yandex Object Storage;
  * presigned URL для upload/download;
  * отделение compute от storage.

---

### Asynchronous processing

* heavy задачи вынесены в background workers;
* RabbitMQ используется как буфер нагрузки;
* система устойчива к всплескам трафика.

---

### Reliability patterns

В проекте реализованы ключевые паттерны надёжности:

* transactional outbox;
* at-least-once delivery;
* retry/backoff;
* DLQ (dead-letter queue);
* идемпотентные consumer-ы;
* lock + TTL для предотвращения гонок.

---

### Observability

* Prometheus — метрики;
* Grafana — dashboards;
* Loki — централизованные логи;
* Alertmanager — алерты;
* request/trace correlation через headers.

---

### Kubernetes-ready

* deployment через Helm chart;
* разделение environments (dev / stage);
* поддержка cloud demo-profile;
* возможность масштабирования сервисов независимо.

---

### Design goal

Система спроектирована так, чтобы:

* легко переноситься в облако;
* масштабироваться по компонентам;
* выдерживать повторную доставку сообщений;
* быть наблюдаемой и диагностируемой;
* демонстрировать production-подход к backend разработке.

___

## Основной video pipeline

```text
upload-service
  -> PostgreSQL
  -> outbox_events
  -> outbox-publisher
  -> RabbitMQ
  -> processing-worker
  -> ffmpeg
  -> local storage / HLS
  -> video status update
  -> video-api playback
```

---

## Архитектурные особенности

### Transactional outbox

* событие сначала пишется в БД;
* затем публикуется в RabbitMQ;
* при ошибках используется retry/backoff;
* нет потери событий между БД и брокером.

### Idempotency

* upload flow через `client_upload_id`;
* processing через lock token + TTL;
* защита от повторной доставки сообщений;
* атомарные переходы состояний (`READY`, `FAILED`).

### Observability

* Prometheus метрики;
* Grafana dashboards;
* Loki для логов;
* correlation через `X-Request-ID` и `X-Trace-Id`.

---

## Environments

### Full local profile

```bash
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml up -d --build
```

### Cloud demo-profile

* Kubernetes + Helm
* минимальный набор сервисов
* упрощённая демонстрация системы

---

## Kubernetes / Helm

Chart:

```text
deploy/helm/video-platform
```

---

## CI/CD

Pipeline в GitLab:

```text
.gitlab-ci.yml
```

Stages:

* test
* build
* security (Trivy)

---

## Monitoring

* Prometheus
* Grafana
* Loki
* Alertmanager

```text
docs/monitoring.md
```

---

## Project structure

```text
app/backend/
deploy/
docs/
monitoring/
infra/
```

---

## Documentation

* `docs/architecture.md`
* `docs/services/service-map.md`
* `docs/events.md`
* `docs/monitoring.md`

---

## Status

Project status: active portfolio project.

The platform is already working locally as a full production-like system:

* full microservice architecture;
* end-to-end video pipeline (upload → processing → playback);
* event-driven processing with RabbitMQ;
* observability with Prometheus/Grafana/Loki.

Cloud deployment is currently in progress:

* Kubernetes (Helm-based deployment);
* S3-compatible storage for media;
* simplified cloud demo-profile.

The goal of the project is to demonstrate DevOps/SRE practices applied to a real backend system.

