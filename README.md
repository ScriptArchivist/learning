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
docker compose -f deploy/docker/docker-compose.local-full.yml up -d --build