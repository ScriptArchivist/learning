(venv) vadim@desktop:~/projects/learning_app$ cat ./last_jwt.txt
cat: ./last_jwt.txt: Нет такого файла или каталога
(venv) vadim@desktop:~/projects/learning_app$ TOKEN="$(cat ./logs/last_jwt.txt)"
curl -s "http://localhost:8000/api/v1/videos/2" -H "Authorization: Bearer ${TOKEN}" | python -m json.tool
{
    "title": "test video",
    "description": null,
    "visibility": "unlisted",
    "id": 2,
    "owner_id": 1,
    "original_filename": "video5204062485010747752.mp4",
    "duration": 2.858667,
    "width": 384,
    "height": 384,
    "size_bytes": 368306,
    "mime_type": "video/mp4",
    "status": "ready",
    "is_blocked": false,
    "original_path": "original/u1/v2/3246b687-3e47-4845-adb1-d8cd9419a50f.mp4",
    "thumbnail_path": "thumbnails/v2/thumb.jpg",
    "hls_url": "/api/v1/videos/2/hls/master.m3u8",
    "hls_ready": true,
    "uploaded_at": "2026-02-23T14:11:16.270223Z",
    "processed_at": "2026-02-23T14:11:18.455451Z",
    "error_message": null,
    "owner": {
        "id": 1,
        "username": "vadim",
        "email": "vadim@example.com",
        "is_active": true,
        "created_at": "2026-02-23T14:04:08.748886Z",
        "storage_limit": 10737418240,
        "used_storage": 1473224
    },
    "formats": [],
    "processing_tasks": []
}