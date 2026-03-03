# video-api (metadata & playback)

Сервис `video-api` предназначен для фронтенда (Flutter) и отвечает только за:
- каталог видео (листинг + фильтры)
- карточку видео
- выдачу playback URL (HLS)

`video-api` **не** занимается:
- загрузкой файлов (upload-service)
- обработкой ffmpeg (processing-worker)
- раздачей HLS сегментов / mp4 / thumbnail (origin/CDN)

---

## База данных

`video-api` использует общую Postgres БД и читает/пишет таблицу:
- `videos`
- (read-only для UI) `video_formats`, `processing_tasks` (если они нужны в detail)

---

## API

Базовый префикс: `/api/v1`

### POST `/videos`
Создать запись видео (metadata).

**Request**
```json
{
  "title": "My video",
  "description": "optional",
  "visibility": "private"
}