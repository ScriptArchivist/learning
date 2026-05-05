# Project documentation

Документация по backend-видеоплатформе, архитектуре, окружениям, событиям и мониторингу.

---

## Архитектура

* `architecture.md`
* `architecture/demo-profile.md`
* `services/service-map.md`

---

## Окружения

* `environments/dev.md`
* `environments/stage.md`
* `environments/vps-helm-deploy.md`

---

## Runtime и события

* `events.md`
* `monitoring.md`

---

## API

* `api/`

---

## Сервисы

* identity-service
* web
* video-api
* upload-service
* live-api
* processing-worker
* outbox-publisher
* video-events-consumer
* dlq-replayer
* live-cleaner

---

## Local full-profile

```bash
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml up -d --build
```

---

## Cloud demo-profile

* Kubernetes
* Helm
* упрощённый набор сервисов

---

## Video pipeline

```text
upload → outbox → RabbitMQ → worker → ffmpeg → storage → playback
```

---

## Events

Система использует event-driven подход:

* upload.completed
* video.process.requested
* video.process.completed
* video.process.failed

Подробнее:

```text
docs/events.md
```

---

## Monitoring

* Prometheus
* Grafana
* Loki
* Alertmanager

Подробнее:

```text
docs/monitoring.md
```

---

## CI/CD

```text
.gitlab-ci.yml
```
