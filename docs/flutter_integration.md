# Flutter Integration Guide

## Цель

Документ предназначен для Flutter-разработчика, который должен реализовать Android-клиент без чтения backend-кода.

---

## Общая идея

Flutter-клиент должен быть построен вокруг конфигурации окружения.

Рекомендуется вынести в конфиг:

- `identityBaseUrl`
- `videoBaseUrl`
- `uploadBaseUrl`
- `liveBaseUrl`
- `originBaseUrl`

Это позволит сначала работать в домашней сети, а потом просто заменить адреса на публичные.

---

## Recommended client architecture

Минимально:

- `AuthRepository`
- `VideoRepository`
- `UploadRepository`
- `LiveRepository`
- `AppConfig`

Также желательно:
- JWT storage
- interceptors for auth headers
- error mapping
- debug logging for requests

---

## Network configuration examples

## Home LAN example

```text
identityBaseUrl = http://192.168.1.12:8001
videoBaseUrl    = http://192.168.1.12:8003
uploadBaseUrl   = http://192.168.1.12:8002
liveBaseUrl     = http://192.168.1.12:8004
originBaseUrl   = http://192.168.1.12:8080


Android emulator example
identityBaseUrl = http://10.0.2.2:8001
videoBaseUrl    = http://10.0.2.2:8003
uploadBaseUrl   = http://10.0.2.2:8002
liveBaseUrl     = http://10.0.2.2:8004
originBaseUrl   = http://10.0.2.2:8080
1. Auth flow
Login request

POST {identityBaseUrl}/auth/login

Request:

{
  "username": "user",
  "password": "password"
}

Client actions:

отправить логин/пароль

получить token/response auth service

сохранить token

подставлять в Authorization: Bearer ...

2. Video list flow
Get videos

GET {videoBaseUrl}/videos?page=1&per_page=20

Экран списка использует:

id

title

description

status

thumbnail_url

duration

uploaded_at

3. Video detail flow
Get video by id

GET {videoBaseUrl}/videos/{id}

Полезные поля:

status

error_message

hls_ready

hls_url

thumbnail_url

uploaded_at

processed_at

4. Upload video flow

В текущей архитектуре рекомендуется использовать upload-service.

Step 1. Получить или создать metadata/video_id

В проекте возможны разные UX-варианты:

сначала создать metadata через video-api

либо использовать существующий video entry

Step 2. Init upload

POST {uploadBaseUrl}/uploads/init?video_id={id}&filename={filename}

Response:

{
  "upload_id": "uuid",
  "object_key": "..."
}
Step 3. Upload file

POST {uploadBaseUrl}/uploads/{upload_id}/file

Multipart:

field file

Step 4. Complete upload

POST {uploadBaseUrl}/uploads/{upload_id}/complete?size={size}&content_type=video/mp4

Step 5. Poll status

GET {videoBaseUrl}/videos/{id}

Пока статус не станет:

ready
или

failed

5. Polling strategy
Video processing

Повторять запрос каждые 2–5 секунд.

Стоп polling при:

ready

failed

UI mapping

uploading → uploading

uploaded → queued

processing → processing

ready → ready

failed → failed

Если failed, показывать error_message.

6. Playback flow
Playback info

GET {videoBaseUrl}/videos/{id}/playback

Response:

{
  "video_id": 42,
  "hls_ready": true,
  "hls_url": "http://..."
}

Если hls_ready = true, Flutter player может открывать hls_url.

Для Android обычно подойдёт:

video_player

или better_player / media_kit / другой HLS-capable player

7. Live flow
Start live session

POST {liveBaseUrl}/live/sessions

Body:

{
  "stream_key": null,
  "ttl_seconds": 1800
}

Response:

{
  "session": {
    "id": 1,
    "stream_key": "abc",
    "status": "started"
  },
  "rtmp_url": "rtmp://...",
  "hls_url": "http://..."
}

Сохранить:

session.id

session.stream_key

rtmp_url

hls_url

Get live session

GET {liveBaseUrl}/live/sessions/{stream_key}

Stop live session

DELETE {liveBaseUrl}/live/sessions/{session_id}

Live playback

Использовать hls_url из create response.

8. Error handling

У части API уже есть единый error format:

{
  "error": {
    "code": "not_found",
    "message": "Video not found",
    "details": null
  }
}

Но часть сервисов может возвращать обычные FastAPI errors.

Поэтому Flutter-клиенту рекомендуется:

сначала пытаться читать error.code и error.message

если такого формата нет — fallback на HTTP status/message

9. Recommended Flutter screens

Минимальный MVP:

LoginScreen

VideoListScreen

VideoDetailScreen

UploadScreen

LiveScreen

10. MVP acceptance for Flutter

Клиент считается готовым к первичной проверке, если он умеет:

login

получить список видео

открыть карточку видео

загрузить файл

дождаться статуса ready

воспроизвести HLS

создать live session

остановить live session

воспроизвести live HLS

11. Important implementation note

Так как сначала приложение будет работать в домашней сети, а затем может быть вынесено во внешний контур, клиент должен быть спроектирован так, чтобы замена окружения сводилась к изменению конфигурации base URLs.

Именно поэтому нельзя хардкодить:

localhost

адреса docker контейнеров

внутренние имена сервисов

Следует использовать только конфиг приложения.