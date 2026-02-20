# service/content_urls.py
from src.config import ORIGIN_BASE_URL

def hls_url(hls_master_key: str) -> str:
    # hls_master_key у тебя вида "hls/u1/v2/master.m3u8" или похожий
    # nginx отдает /hls/... относительно /app/uploads/hls
    # поэтому надо отрезать префикс "hls/" если он есть
    key = hls_master_key
    if key.startswith("hls/"):
        key = key[len("hls/"):]
    return f"{ORIGIN_BASE_URL}/hls/{key}"

def thumb_url(thumb_key: str) -> str:
    # аналогично, зависит от реального пути thumbnails
    key = thumb_key
    if key.startswith("thumbs/"):
        key = key[len("thumbs/"):]
    return f"{ORIGIN_BASE_URL}/thumb/{key}"