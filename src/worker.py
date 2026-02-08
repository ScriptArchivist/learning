import os
from datetime import datetime

from service.broker import consume_forever
from service.video_service import set_video_status, set_video_processed_info

# Корень хранилища внутри контейнеров (web и worker должны видеть один и тот же /app/uploads)
STORAGE_ROOT = "/app/uploads"


def handle(payload: dict):
    """
    Получаем задачу из Rabbit:
    payload = {"video_id": int, "path": "original/1/1/....mp4"}

    Делаем минимальную реальную работу:
    - проверяем что файл существует
    - считаем размер
    - пишем processed_at и file_size
    - меняем статусы PROCESSING -> READY/FAILED
    """
    video_id = int(payload["video_id"])
    rel_path = payload["path"]  # относительный путь из БД/сообщения
    full_path = os.path.join(STORAGE_ROOT, rel_path)  # абсолютный путь в контейнере

    print(f"[worker] start video_id={video_id} path={rel_path}")

    set_video_status(video_id, "PROCESSING", None)

    try:
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"file not found: {full_path}")

        size = os.path.getsize(full_path)

        set_video_processed_info(
            video_id=video_id,
            processed_at=datetime.utcnow(),
            file_size=size,
        )

        set_video_status(video_id, "READY", None)
        print(f"[worker] done video_id={video_id}, size={size}")

    except Exception as e:
        set_video_status(video_id, "FAILED", str(e))
        print(f"[worker] failed video_id={video_id}: {e}")


if __name__ == "__main__":
    consume_forever(handle)
