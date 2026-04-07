# Video Platform DevOps Project

## Описание
Микросервисная видеоплатформа:
upload → queue → processing → storage → delivery

## Цель проекта
Практика DevOps:
- Docker
- Kubernetes
- Terraform
- Helm
- GitLab CI/CD
- Monitoring

## Структура репозитория

- app/ — код приложения
- infra/terraform/ — инфраструктура
- deploy/docker/ — локальный запуск
- deploy/helm/ — Kubernetes deployment
- monitoring/ — Prometheus / alerts
- docs/ — документация

## Локальный запуск

```bash
docker-compose -f deploy/docker/docker-compose.local-full.yml up -d --build

## Local full-profile

На текущем этапе полный локальный стек запускается через:

`deploy/docker/docker-compose.ci.yml`

### Run

```bash
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml up -d --build
Stop
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml down -v

