# Local Development Environment

## Назначение

На текущем этапе проект использует единый docker-compose файл:

`deploy/docker/docker-compose.ci.yml`

как основной full-profile для локального запуска всей системы.

Это осознанное решение: один compose-файл используется как единый источник истины для полного локального контура.

## Env file

Для локального запуска используется:

`deploy/docker/.env.dev`

## Запуск

```bash
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml up -d --build


Остановка
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml down -v
Отдельный запуск миграций
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml up --build migrate


Что входит в full-profile

Полный список сервисов описан в:

docs/services/service-map.md


---

# Шаг 4. Проверить, что `docker-compose.ci.yml` остаётся источником истины

## Что это значит

Ничего нового не создаём. Просто убеждаемся, что именно этот файл:

- реально рабочий
- используется для локального запуска
- описан в документации как основной

## Проверки

### Проверка конфига
```bash
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml config
Проверка запуска
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml up -d --build
Проверка статуса
docker-compose --env-file deploy/docker/.env.dev -f deploy/docker/docker-compose.ci.yml ps