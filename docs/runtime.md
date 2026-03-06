```md
# Runtime

## Назначение

Документ описывает, как запускать проект в текущем виде и какие адреса/переменные окружения важны для клиентской интеграции.

---

## Основной compose

Для локальной/домашней интеграции используется:

```bash
docker-compose -f docker-compose.ci.yml up --build

Именно docker-compose.ci.yml является основным рабочим compose в текущем проекте.

Основные сервисы и порты

web → http://localhost:8000

identity-service → http://localhost:8001

upload-service → http://localhost:8002

video-api → http://localhost:8003

live-api → http://localhost:8004

origin → http://localhost:8080

prometheus → http://localhost:9090

grafana → http://localhost:3000

Внутренние зависимости

Инфраструктурные контейнеры:

PostgreSQL master

PostgreSQL replica

RabbitMQ

Redis

Background services:

processing-worker

outbox-publisher

video-events-consumer

live-cleaner

dlq-replayer

Что важно для Flutter

Flutter-клиент должен обращаться не к внутренним именам контейнеров, а к доступным извне адресам.

Например, для домашней сети:

http://192.168.1.10:8001 — identity-service

http://192.168.1.10:8002 — upload-service

http://192.168.1.10:8003 — video-api

http://192.168.1.10:8004 — live-api

http://192.168.1.10:8080 — origin/HLS

Где 192.168.1.10 — IP машины, на которой запущен backend.

Режимы адресации для Flutter

Рекомендуется поддерживать 3 конфигурации:

1. Emulator / local dev

Пример:

10.0.2.2:8001

10.0.2.2:8002

10.0.2.2:8003

10.0.2.2:8004

10.0.2.2:8080

2. Домашняя сеть

Пример:

192.168.x.x:8001

192.168.x.x:8002

192.168.x.x:8003

192.168.x.x:8004

192.168.x.x:8080

3. Публичный контур

Пример:

https://auth.example.com

https://upload.example.com

https://video.example.com

https://live.example.com

https://cdn.example.com

Рекомендуемая конфигурация клиента

В Flutter желательно вынести в конфиг:

identityBaseUrl

videoBaseUrl

uploadBaseUrl

liveBaseUrl

originBaseUrl

Это позволит сначала использовать домашнюю сеть, а потом сменить только конфиг.

Важные переменные окружения backend

Ниже перечислены те переменные, которые влияют на клиентское поведение.

Общие

database_write_url

database_read_url

Security / auth

secret_key

access_token_expire_minutes

Delivery / HLS

DELIVERY_MODE

DELIVERY_BASE_URL

DELIVERY_PUBLIC_BASE_URL

LIVE_RTMP_URL_TEMPLATE

LIVE_HLS_URL_TEMPLATE

Upload / storage

STORAGE_PATH

CORS

CORS_ALLOW_ORIGINS

CORS_ALLOW_ORIGIN_REGEX

Проверка запуска

После старта контейнеров:

docker-compose -f docker-compose.ci.yml ps

Ожидается, что основные сервисы находятся в состоянии Up.

Health endpoints

Проверка доступности сервисов:

curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
curl http://localhost:8004/health

Если у сервиса нет явного /health, нужно ориентироваться на успешный ответ корневого API или /docs.

OpenAPI / Swagger

Доступно у FastAPI сервисов по стандартным адресам:

http://localhost:8001/docs

http://localhost:8002/docs

http://localhost:8003/docs

http://localhost:8004/docs

Эти страницы полезны Flutter-разработчику как источник актуальной схемы запросов/ответов.

Monitoring

Prometheus: http://localhost:9090

Grafana: http://localhost:3000

Практический вывод для Flutter

Для Flutter MVP в домашней сети нет необходимости подключать S3.

Достаточно:

поднять backend через docker-compose.ci.yml

использовать IP машины в локальной сети

хранить адреса сервисов в конфиге

later заменить base URLs на публичные без изменения бизнес-логики клиента