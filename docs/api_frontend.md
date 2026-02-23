Video Platform API — Frontend Documentation (v1)

Base URL: /api/v1
Content-Type: application/json
Versioning: /api/v1 — breaking changes возможны только в /api/v2.

1. Аутентификация

Все приватные эндпоинты требуют:

Authorization: Bearer <JWT>

Пример:

curl -s "http://localhost:8000/api/v1/videos/?page=1&per_page=20" \
  -H "Authorization: Bearer $TOKEN"
2. Единый формат ошибок (FE-BE2)

Любая ошибка возвращается в едином формате:

{
  "error": {
    "code": "not_found",
    "message": "Video 123 not found",
    "details": null
  }
}
error.code
HTTP	code	Когда используется
400	validation_error	Бизнес-валидация
401	unauthorized	Нет/неверный JWT
403	forbidden	Нет прав доступа
404	not_found	Ресурс не найден
409	conflict	Конфликт статусов
422	validation_error	Pydantic validation
500	internal	Неожиданная ошибка

Frontend должен ориентироваться на error.code, а не на HTTP-текст.

3. Статусы видео

Поле status:

Статус	Значение для UI
uploading	Идёт загрузка
uploaded	Загружено, ждёт обработки
processing	В обработке
ready	Можно смотреть
failed	Ошибка обработки

Если status = failed → в error_message будет причина.

4. Модель VideoResponse

Основные поля:

{
  "id": 1,
  "owner_id": 1,
  "title": "My video",
  "description": null,
  "visibility": "private",
  "status": "ready",
  "is_blocked": false,

  "duration": 12.34,
  "width": 1920,
  "height": 1080,
  "size_bytes": 1234567,
  "mime_type": "video/mp4",

  "uploaded_at": "2026-02-23T16:06:42Z",
  "processed_at": "2026-02-23T16:07:10Z",

  "error_message": null,

  "hls_ready": true,
  "hls_url": "/api/v1/videos/1/hls/master.m3u8",

  "watch_url": "/api/v1/videos/1/watch",
  "file_url": "/api/v1/videos/1/file",
  "thumbnail_url": "/api/v1/videos/1/thumbnail",

  "is_shared": true,
  "share_url": "/api/v1/videos/shared/abc123"
}
Важные поля для UI

status

error_message

hls_ready

hls_url

thumbnail_url

file_url

watch_url

is_shared

share_url

Frontend не должен вычислять доступность — ориентироваться на status и hls_ready.

5. Endpoints
5.1 GET /videos

Список видео пользователя.

Query параметры
Параметр	Тип	По умолчанию
page	int	1
per_page	int	20 (max 100)
status	str	optional
visibility	str	optional
search	str	optional
Response
{
  "items": [VideoResponse],
  "page": 1,
  "per_page": 20,
  "total": 42
}
5.2 GET /videos/{id}

Возвращает VideoResponse.

curl -H "Authorization: Bearer $TOKEN" \
http://localhost:8000/api/v1/videos/1
5.3 POST /videos/upload/prepare

Создаёт запись видео.

Request
{
  "title": "My video",
  "description": null,
  "visibility": "private",
  "filename": "clip.mp4",
  "file_size": 123456,
  "client_upload_id": "uuid-string"
}
Response
{
  "upload_id": "uuid",
  "upload_url": "/api/v1/videos/42/upload/direct",
  "video_id": 42,
  "expires_at": "2026-02-23T16:06:00Z",
  "object_key": "original/u1/v42/uuid.mp4"
}

Повторный вызов с тем же client_upload_id — идемпотентен.

5.4 POST /videos/{id}/upload/direct

Multipart upload (local режим).

Content-Type: multipart/form-data

Поле: file.

5.5 POST /videos/{id}/upload/complete

Подтверждение завершения загрузки.

Request
{
  "upload_id": "uuid",
  "size_bytes": 123456,
  "etag": "optional",
  "parts": null
}
Response

VideoResponse (status → uploaded).

6. Просмотр видео (AUTH)
GET /videos/{id}/file

MP4 с поддержкой Range.

GET /videos/{id}/thumbnail

JPEG thumbnail.

GET /videos/{id}/hls/master.m3u8

HLS playlist.
Сегменты .ts требуют query ?token=.

7. Share / Unlisted
POST /videos/{id}/share
{
  "video_id": 1,
  "share_url": "/api/v1/videos/shared/<token>"
}
POST /videos/{id}/share/revoke
{
  "video_id": 1,
  "revoked": true
}
GET /videos/shared/{token}

VideoResponse без авторизации.

GET /videos/shared/{token}/file

MP4 без авторизации.

GET /videos/shared/{token}/thumbnail

JPEG без авторизации.

GET /videos/shared/{token}/hls/master.m3u8

Shared HLS playlist.
Сегменты защищены TTL токеном.

8. CORS (FE-BE4)

Dev-режим:

Разрешены localhost и 127.0.0.1 на любом порту.

allow_credentials = true.

ENV:

CORS_ALLOW_ORIGINS=http://localhost:5173,http://localhost:3000
CORS_ALLOW_ORIGIN_REGEX=^https?://(localhost|127\.0\.0\.1)(:\d+)?$
9. Гарантии стабильности

Новые поля добавляются только расширением DTO.

Старые поля не переименовываются в рамках v1.

Ошибки всегда возвращаются в формате { error: {...} }.

Пагинация всегда { items, page, per_page, total }.

10. Минимальный UI-поток
Upload flow

POST /videos/upload/prepare

POST /videos/{id}/upload/direct

POST /videos/{id}/upload/complete

Poll GET /videos/{id} пока status = ready

Share flow

POST /videos/{id}/share

Использовать share_url

При необходимости revoke

Документ соответствует состоянию API версии v1.