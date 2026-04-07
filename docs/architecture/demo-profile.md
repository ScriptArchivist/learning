# Cloud Demo Profile

## Назначение

Cloud demo-profile — это упрощённый профиль системы для облачного развертывания.

Его цель — показать один полный end-to-end сценарий без избыточной инфраструктурной сложности.

## Состав demo-profile

- db-master
- rabbitmq
- redis
- migrate
- web
- upload-service
- processing-worker
- video-api
- origin

## Что исключено из demo-profile

Следующие сервисы оставлены только в full local profile:

- db-replica
- identity-service
- live-api
- video-events-consumer
- ingest
- outbox-publisher
- dlq-replayer
- live-cleaner
- prometheus
- grafana

## Причина упрощения

Для облачной демонстрации не требуется полный контур из всех вспомогательных сервисов.  
Минимальный профиль уменьшает стоимость, упрощает сопровождение и делает архитектуру легче для объяснения.

## Запуск

```bash
docker-compose --env-file deploy/docker/.env.stage -f deploy/docker/docker-compose.demo.yml up -d --build


---

# Шаг 7. Проверить demo-profile

## Сначала проверка конфига

```bash
docker-compose \
  --env-file deploy/docker/.env.stage \
  -f deploy/docker/docker-compose.demo.yml \
  config
Потом запуск
docker-compose \
  --env-file deploy/docker/.env.stage \
  -f deploy/docker/docker-compose.demo.yml \
  up -d --build
Проверить статус
docker-compose \
  --env-file deploy/docker/.env.stage \
  -f deploy/docker/docker-compose.demo.yml \
  ps