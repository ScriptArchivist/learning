# Flutter Android MVP — Backend Integration Task

## Назначение

Этот документ описывает задачу на создание **Flutter Android MVP-приложения** для интеграции с backend-видеоплатформой.

Цель — получить рабочий мобильный клиент, который проверяет реальные пользовательские сценарии взаимодействия с backend.

Backend реализован на **FastAPI** и состоит из нескольких сервисов.

Приложение должно работать в **домашней сети**, но быть спроектировано так, чтобы в будущем можно было просто заменить base URLs и использовать его во внешнем контуре.

---

# Цель приложения

Создать **Flutter Android MVP**, поддерживающий следующие пользовательские сценарии:

- login
- просмотр списка видео
- просмотр карточки видео
- загрузка видеофайла
- ожидание обработки видео
- воспроизведение HLS видео
- создание live session
- остановка live session
- воспроизведение live HLS

Приложение должно использовать **реальные backend endpoints**.

---

# Важные ограничения

1. Не усложнять проект сверх MVP.
2. Использовать **реальные backend endpoints**, а не придумывать новые.
3. Все backend адреса должны задаваться через конфигурацию.
4. Нельзя хардкодить:
   - `localhost`
   - docker hostnames
   - адреса контейнеров
5. Основная цель — **проверка backend интеграции**, а не идеальная архитектура.

---

# Конфигурация окружения

Приложение должно использовать конфигурационный объект `AppConfig`.

Нужно поддерживать такие base URLs:

- `identityBaseUrl`
- `videoBaseUrl`
- `uploadBaseUrl`
- `liveBaseUrl`
- `originBaseUrl`

---

## Пример конфигурации для реального Android телефона

```text
identityBaseUrl = http://192.168.1.12:8001
videoBaseUrl    = http://192.168.1.12:8003
uploadBaseUrl   = http://192.168.1.12:8002
liveBaseUrl     = http://192.168.1.12:8004
originBaseUrl   = http://192.168.1.12:8080
Пример конфигурации для Android emulator
identityBaseUrl = http://10.0.2.2:8001
videoBaseUrl    = http://10.0.2.2:8003
uploadBaseUrl   = http://10.0.2.2:8002
liveBaseUrl     = http://10.0.2.2:8004
originBaseUrl   = http://10.0.2.2:8080

Важно:

10.0.2.2 используется только Android emulator

реальный телефон должен использовать IP машины в домашней сети

Backend сервисы
Identity service

Base URL:

{identityBaseUrl}

Endpoint:

POST /auth/login

Request:

{
  "username": "user",
  "password": "password"
}

Клиент должен:

отправить логин/пароль

сохранить токен

использовать Authorization: Bearer <token> в запросах

Video API

Base URL:

{videoBaseUrl}

Endpoints:

GET /videos
GET /videos/{id}
GET /videos/{id}/playback

Статусы видео:

uploading

uploaded

processing

ready

failed

Если статус failed, API возвращает error_message.

Playback response:

{
  "video_id": 42,
  "hls_ready": true,
  "hls_url": "http://..."
}
Upload Service

Base URL:

{uploadBaseUrl}

Endpoints:

POST /uploads/init
POST /uploads/{upload_id}/file
POST /uploads/{upload_id}/complete
POST /uploads/init

Параметры:

video_id

filename

Response:

{
  "upload_id": "uuid",
  "object_key": "..."
}
POST /uploads/{upload_id}/file

Multipart upload.

Field:

file
POST /uploads/{upload_id}/complete

Параметры:

size

checksum (optional)

content_type (optional)

Live API

Base URL:

{liveBaseUrl}

Endpoints:

POST /live/sessions
GET /live/sessions/{stream_key}
DELETE /live/sessions/{session_id}
Create live session

Request:

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
Flutter приложение должно реализовать
Экраны

Минимальный набор экранов:

LoginScreen

VideoListScreen

VideoDetailScreen

UploadScreen

LiveScreen

Структура проекта

Нужно разделить проект минимум на:

config
core/network
repositories
models
screens
widgets
Слои приложения

Должны быть реализованы:

AppConfig

AuthRepository

VideoRepository

UploadRepository

LiveRepository

Network layer

Нужно реализовать:

HTTP client

interceptor для Authorization

логирование запросов

обработку ошибок

Login flow

Нужно:

экран логина

отправка POST /auth/login

сохранение токена

использование токена в API запросах

Video list flow

Экран должен получать:

GET /videos

Отображать:

title

description

status

duration

thumbnail

uploaded_at

Video detail flow

Экран должен использовать:

GET /videos/{id}

Показывать:

metadata

status

error_message

hls_ready

hls_url

Upload flow

Нужно реализовать:

POST /uploads/init

загрузку файла

POST /uploads/{upload_id}/file

POST /uploads/{upload_id}/complete

polling статуса через GET /videos/{id}

Polling

Пока статус:

uploading

uploaded

processing

нужно повторять запрос:

GET /videos/{id}

Интервал:

2–5 секунд

Остановить polling если:

ready

failed

HLS playback

Нужно воспроизводить:

VOD HLS

live HLS

Можно использовать любой стабильный Flutter player.

Live flow
Start live
POST /live/sessions

Сохранить:

session.id

stream_key

rtmp_url

hls_url

Poll session
GET /live/sessions/{stream_key}
Stop live
DELETE /live/sessions/{session_id}
Error handling

Backend может возвращать:

JSON error format
{
  "error": {
    "code": "not_found",
    "message": "Video not found",
    "details": null
  }
}

Или обычные FastAPI ошибки.

Клиент должен:

сначала проверять error.code

если нет — использовать HTTP status/message

Требуемый результат

Нужно выдать готовый Flutter проект, включающий:

структуру проекта

pubspec

конфиг

сетевой слой

модели

repositories

экраны

HLS playback

README по запуску

Формат ответа

Очень важно:

короткие файлы — давать целиком

длинные файлы — давать классами или виджетами

не использовать diff

код должен быть пригоден для копирования

Acceptance criteria

Приложение считается готовым если:

можно залогиниться

можно получить список видео

можно открыть карточку видео

можно загрузить видео

можно дождаться статуса ready

можно воспроизвести HLS видео

можно создать live session

можно остановить live session

можно воспроизвести live HLS

backend адреса меняются через конфиг

Backend файлы (source of truth)

При реализации использовать следующие backend файлы:

web/video_api.py
web/upload.py
web/live.py
identity/web/auth.py
identity/src/main.py
model/video.py
model/video_contract.py
model/live.py
model/api_error.py
Backend documentation

Также использовать документацию:

docs/architecture.md
docs/runtime.md
docs/api/auth.md
docs/api/video_api.md
docs/api/upload_service.md
docs/api/live_api.md
docs/events.md
docs/flutter_integration.md
Важное замечание

Сейчас не нужно внедрять:

S3

production auth

сложные offline сценарии

сложные state management решения

Главная цель — получить Flutter Android MVP для проверки backend интеграции в домашней сети.


---

## Итог

Теперь у тебя есть:

- **единая постановка задачи**
- **готовый markdown-файл**
- **список backend-файлов**
- **реальные endpoints**
- **конфиг для LAN и emulator**

Это именно тот формат, который **очень хорошо работает для ИИ**.

---

Если хочешь, я ещё покажу **одну очень полезную вещь**:  
как **из этого задания сделать “идеальный prompt для ИИ”**, чтобы он генерировал Flutter-проект **почти без ошибок и выдуманных API**.