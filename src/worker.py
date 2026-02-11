import json
import os
import subprocess
from datetime import datetime

from service.ffmpeg_utils import make_hls
from db.models import VideoStatus

from service.broker import consume_forever
from service.video_service import set_video_status, set_video_processed_info

# Корень хранилища внутри контейнеров (web и worker должны видеть один и тот же /app/uploads)
STORAGE_ROOT = "/app/uploads"


def ffprobe_metadata(full_path: str) -> dict:
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-show_entries", "format=duration",
        "-of", "json",
        full_path,
    ]
    out = subprocess.check_output(cmd)
    data = json.loads(out.decode("utf-8"))

    duration_raw = (data.get("format") or {}).get("duration")
    duration = float(duration_raw) if duration_raw else None

    streams = data.get("streams") or []
    stream0 = streams[0] if streams else {}
    width = stream0.get("width")
    height = stream0.get("height")

    return {"duration": duration, "width": width, "height": height}


def make_thumbnail(full_path: str, out_path: str, at_seconds: float = 1.0) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(at_seconds),
        "-i", full_path,
        "-frames:v", "1",
        "-update", "1",          # ✅ чтобы писать один файл без warning
        "-q:v", "3",
        out_path,
    ]
    subprocess.check_call(cmd)


def handle(payload: dict):
    video_id = int(payload["video_id"])
    rel_path = payload["path"]
    full_path = os.path.join(STORAGE_ROOT, rel_path)

    print(f"[worker] start video_id={video_id} path={rel_path}")

    try:
        # 0) Файл должен существовать — иначе сразу FAILED (без PROCESSING)
        if not os.path.exists(full_path):
            raise FileNotFoundError(f"file not found: {full_path}")

        # Теперь уже честно ставим PROCESSING
        set_video_status(video_id, VideoStatus.PROCESSING, None)

        size = os.path.getsize(full_path)

        # 1) Метаданные
        meta = ffprobe_metadata(full_path)
        duration = meta["duration"]
        width = meta["width"]
        height = meta["height"]

        # 2) Thumbnail
        thumb_rel = f"thumbnails/{video_id}/thumb.jpg"
        thumb_full = os.path.join(STORAGE_ROOT, thumb_rel)
        make_thumbnail(full_path, thumb_full, at_seconds=1.0)

        # 3) HLS
        hls_rel_dir = f"hls/{video_id}"
        hls_full_dir = os.path.join(STORAGE_ROOT, hls_rel_dir)
        make_hls(full_path, hls_full_dir)

        # ✅ Проверяем, что артефакты реально создались (иначе FAILED)
        if not os.path.exists(thumb_full):
            raise RuntimeError(f"thumbnail was not created: {thumb_full}")

        hls_playlist_full = os.path.join(hls_full_dir, "index.m3u8")
        if not os.path.exists(hls_playlist_full):
            raise RuntimeError(f"hls playlist was not created: {hls_playlist_full}")

        print(f"[worker] hls ready: /hls/{video_id}/index.m3u8")

        processed_at = datetime.utcnow()

        # 4) Пишем инфо в БД
        set_video_processed_info(
            video_id=video_id,
            processed_at=processed_at,
            file_size=size,
            duration=duration,
            width=width,
            height=height,
            thumbnail_path=thumb_rel,
            mime_type="video/mp4",
        )

        # ✅ READY только после успешного создания thumbnail + HLS + записи в БД
        set_video_status(video_id, VideoStatus.READY, None)

        print(
            f"[worker] done video_id={video_id}, size={size}, "
            f"duration={duration}, w={width}, h={height}, thumb={thumb_rel}"
        )

    except Exception as e:
        set_video_status(video_id, VideoStatus.FAILED, str(e))
        print(f"[worker] failed video_id={video_id}: {e}")


if __name__ == "__main__":
    consume_forever(handle)
