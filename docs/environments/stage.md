# Stage environment

## Назначение

Stage — это упрощённое demo-окружение для облака и финальной демонстрации проекта.

## Где используется

- Yandex Cloud
- k3s / минимальный Kubernetes
- локально для проверки demo-профиля перед деплоем

## Цель

Показать работающий end-to-end сценарий без запуска полного контура из всех микросервисов.

Основной сценарий:
- загрузка видео
- обработка
- публикация результата
- доступ через API / playback

## Состав

Stage = минимально достаточный demo-profile.

Рекомендуемый набор:
- backend/api
- upload service
- worker / processing
- PostgreSQL
- RabbitMQ
- origin / nginx
- при необходимости frontend

Без второстепенных и тяжёлых сервисов, если они не нужны для demo.

## Основные настройки

- профиль: demo
- логирование: info
- live: disabled
- replicas: 1
- ресурсы: минимальные, но стабильные
- конфигурация ближе к production, чем в dev

## Что важно

Stage должен быть:
- дешёвым
- понятным
- воспроизводимым
- легко объяснимым на собеседовании

Это не production, а демонстрационный срез системы.

## Команды запуска локально

```bash
docker-compose --env-file deploy/docker/.env.stage -f deploy/docker/docker-compose.demo.yml up -d


Проверки

Проверка контейнеров:

docker-compose --env-file deploy/docker/.env.stage -f deploy/docker/docker-compose.demo.yml ps

Проверка логов:

docker-compose --env-file deploy/docker/.env.stage -f deploy/docker/docker-compose.demo.yml logs -f

Smoke-проверка API:

curl http://localhost:8000/health

Проверка end-to-end сценария:

загрузить тестовый файл
убедиться, что задача ушла в очередь
убедиться, что processing завершился
проверить конечный статус видео
Ограничения

Stage не равен production:

нет полноценной отказоустойчивости
нет autoscaling
нет сложной observability-платформы
могут отсутствовать дополнительные security-hardening меры

---

## `docs/environments/README.md`

```md
# Environments overview

| Параметр | dev | stage |
|---|---|---|
| назначение | локальная разработка | demo / предрелизная проверка |
| сервисы | все | demo-profile |
| логирование | debug | info |
| live | да | нет |
| hot reload | да | нет |
| bind mounts | да | минимально |
| ресурсы | без жёсткой экономии | ограниченные |
| replicas | может быть произвольно | 1 |
| мониторинг | расширенный / удобный для отладки | минимально достаточный |
| секреты | локальные упрощённые | ближе к боевым |
| деплой | docker-compose | docker-compose / Helm / k3s |