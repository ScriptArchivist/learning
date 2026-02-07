import time
from service.broker import consume_forever
from service.video_service import set_video_status

def handle(payload: dict):
    video_id = int(payload["video_id"])
    path = payload["path"]

    # 1) отмечаем, что начали
    set_video_status(video_id, "PROCESSING", None)

    try:
        # 2) тут будет реальная обработка (ffmpeg/метаданные/превью)
        # пока заглушка:
        time.sleep(2)

        # 3) успех
        set_video_status(video_id, "READY", None)

    except Exception as e:
        # 4) ошибка
        set_video_status(video_id, "FAILED", str(e))
        raise  # важно: если хочешь ретраи через requeue — дальше усложняется

if __name__ == "__main__":
    consume_forever(handle)
