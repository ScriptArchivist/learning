```md
# Video API

## Service

`video-api`

Base URL example:
- local: `http://localhost:8003`
- home LAN: `http://<LAN_IP>:8003`

Swagger:
- `/docs`

---

## Назначение

Сервис предназначен для Flutter-клиента и отвечает за:

- создание записи видео
- получение списка видео
- получение карточки видео
- получение playback-данных

Сервис не принимает бинарный файл напрямую и не выполняет обработку ffmpeg.

---

## Authentication

Сейчас в коде используется `get_current_user_stub()`, то есть реальная JWT-проверка в `web/video_api.py` пока не подключена.

Для документации Flutter это означает:
- API уже можно интегрировать
- но security layer для `video-api` ещё может быть усилен позже

---

## DTO

Основные схемы:
- `VideoCreate`
- `VideoDetailDTO`
- `VideoListResponse`
- `VideoListItemDTO`

Статусы видео:
- `uploading`
- `uploaded`
- `processing`
- `ready`
- `failed`

Visibility:
- `public`
- `private`
- `unlisted`

---

## Endpoints

## POST `/videos`

Создать запись видео.

### Request

```json
{
  "title": "My video",
  "description": "optional",
  "visibility": "private"
}
Response

VideoDetailDTO

Пример значимых полей:

id

title

description

visibility

status

uploaded_at

hls_ready

hls_url

thumbnail_url

Errors

400 — validation/business error

GET /videos

Получить список видео.

Query params

status — optional

visibility — optional

owner_id — optional

min_duration — optional

max_duration — optional

search — optional

page — default 1

per_page — default 20, max 100

Response
{
  "items": [],
  "page": 1,
  "per_page": 20,
  "total": 0
}

Каждый элемент items — VideoListItemDTO.

Important fields for Flutter list screen

id

title

description

status

thumbnail_url

duration

uploaded_at

hls_ready

GET /videos/{video_id}

Получить карточку видео.

Response

VideoDetailDTO

Полезно для:

экрана видео

polling статуса

отображения metadata

показа ошибок обработки

Errors

404 — video not found

403 — forbidden

GET /videos/{video_id}/playback

Получить playback-информацию.

Response
{
  "video_id": 42,
  "hls_ready": true,
  "hls_url": "http://..."
}
Semantics

hls_ready=false → видео ещё нельзя воспроизводить

hls_ready=true и hls_url != null → можно запускать HLS player

Flutter recommendation

На экране видео:

сначала запросить /videos/{id}

затем, если status == ready, запросить /videos/{id}/playback

либо использовать hls_url из DTO, если он уже заполнен

Typical Flutter usage
List screen

GET /videos?page=1&per_page=20

Video detail

GET /videos/{id}

Playback check

GET /videos/{id}/playback

Polling

Пока статус:

uploading

uploaded

processing

клиент может повторять GET /videos/{id} с интервалом 2–5 секунд.

Notes

Текущий video-api — это именно сервис метаданных и playback, а не upload gateway.

Для upload файла Flutter-клиент должен использовать upload-service.