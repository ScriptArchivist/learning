```md
# Upload Service API

## Service

`upload-service`

Base URL example:
- local: `http://localhost:8002`
- home LAN: `http://<LAN_IP>:8002`

Swagger:
- `/docs`

---

## Назначение

Сервис отвечает за upload flow:

1. инициализация upload
2. загрузка файла
3. завершение upload
4. публикация события `upload.completed`

---

## Authentication

В `web/upload.py` используется dependency `service.security.get_current_user`.

Для Flutter это означает, что upload flow следует считать приватным и вызывать с авторизацией.

---

## Endpoints

## POST `/uploads/init`

Инициализация upload.

### Parameters

Endpoint принимает параметры:
- `video_id`
- `filename`

Они объявлены как function arguments, поэтому фактически передаются как query/form parameters в зависимости от вызова клиента.

Практически рекомендуется вызывать как query params.

### Example

```http
POST /uploads/init?video_id=42&filename=clip.mp4
Authorization: Bearer <token>
Response
{
  "upload_id": "uuid",
  "object_key": "original/u1/v42/clip.mp4"
}
Meaning

upload_id — идентификатор upload-сессии

object_key — путь объекта в storage

POST /uploads/{upload_id}/file

Загрузка бинарного файла.

Content type

multipart/form-data

Form field

file

Response
{
  "ok": true
}
Meaning

Файл сохранён в storage по object_key, связанному с upload.

POST /uploads/{upload_id}/complete

Подтверждение завершения upload.

Parameters

size

checksum — optional

content_type — optional

Текущая реализация принимает их как function arguments, поэтому practically это query/form style endpoint.

Example
POST /uploads/{upload_id}/complete?size=123456&content_type=video/mp4
Authorization: Bearer <token>
Response
{
  "status": "completed"
}
Side effect

После успешного завершения:

upload помечается как completed

публикуется событие upload.completed

Recommended Flutter flow
Step 1

Создать запись видео через video-api или получить video_id в рамках клиентского сценария.

Step 2

Вызвать:

POST /uploads/init

Step 3

Получить upload_id

Step 4

Загрузить файл на:

POST /uploads/{upload_id}/file

Step 5

Вызвать:

POST /uploads/{upload_id}/complete

Step 6

Дальше опрашивать video status через video-api

Notes

Сейчас upload-service реализует local upload flow, а не presigned S3 upload.

Для Flutter MVP в домашней сети этого достаточно.