# Video API — обновление и удаление видео

## Назначение

API предоставляет владельцу видео возможность:

- изменить метаданные видео
- удалить видео

Функции доступны только авторизованному пользователю.

## Base URL


http://localhost:8003/api/v1


## Аутентификация

Все запросы требуют JWT.


Authorization: Bearer <access_token>


Изменять и удалять видео может **только владелец**.

Наличие публичного доступа или share-link не даёт права на изменение или удаление.

---

# 1. Обновление видео

## Endpoint


PATCH /videos/{video_id}


## Назначение

Обновляет метаданные видео.

## Кто может использовать

Только владелец видео.

## Разрешённые поля

Можно изменять только:


title
description
visibility


## Request

```json
{
  "title": "New title",
  "description": "Updated description",
  "visibility": "public"
}

Все поля опциональны.

Можно передать только одно поле.

Пример
{
  "title": "Updated video title"
}
Допустимые значения visibility
public
private
unlisted
Response
200 OK

Возвращается полный DTO видео.

Пример ответа
{
  "id": 1,
  "owner_id": 1,
  "title": "Updated video title",
  "description": "Updated description",
  "visibility": "public",
  "status": "ready",
  "hls_ready": true,
  "hls_url": "http://localhost:8080/hls/v1/master.m3u8"
}
Возможные ошибки
400 Bad Request

Некорректные поля.

403 Forbidden

Пользователь не является владельцем видео.

404 Not Found

Видео не найдено.

2. Удаление видео
Endpoint
DELETE /videos/{video_id}
Назначение

Полностью удаляет видео из системы.

Что происходит при удалении

Удаляются:

video запись из БД
оригинальный файл
HLS директория
thumbnail директория
video_formats
processing_tasks

Также уменьшается used_storage пользователя.

Response
204 No Content

Ответ не содержит тела.

Это стандартное REST-поведение.

Возможные ошибки
403 Forbidden

Пользователь не владелец видео.

404 Not Found

Видео не найдено.

Примеры curl
Обновление видео
curl -X PATCH "http://localhost:8003/api/v1/videos/1" \
  -H "Authorization: Bearer <JWT>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "New video title",
    "visibility": "public"
  }'
Удаление видео
curl -X DELETE "http://localhost:8003/api/v1/videos/1" \
  -H "Authorization: Bearer <JWT>"

Ожидаемый ответ:

204
Рекомендации для клиентских приложений
Update

отправлять PATCH

передавать только изменённые поля

ожидать HTTP 200

Delete

отправлять DELETE

считать успешным HTTP 204

после 204 удалять объект из UI

Python пример клиента
Update
import requests

def update_video(base_url, token, video_id, payload):
    r = requests.patch(
        f"{base_url}/api/v1/videos/{video_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json=payload
    )
    r.raise_for_status()
    return r.json()
Delete
import requests

def delete_video(base_url, token, video_id):
    r = requests.delete(
        f"{base_url}/api/v1/videos/{video_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    if r.status_code == 204:
        return True
    r.raise_for_status()
Ограничения

Visibility не влияет на право изменения.

Только владелец может обновлять и удалять видео.

Share-link не даёт прав на изменение.

DELETE возвращает 204 без тела ответа.


---

💡 Если хочешь, я ещё могу дать **третью очень полезную вещь**:  

**`docs/video_api_flow.md` — архитектурную схему всего pipeline**


video-api
↓
upload-service
↓
outbox
↓
rabbitmq
↓
processing-worker
↓
origin/hls