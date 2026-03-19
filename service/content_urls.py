# service/content_urls.py
import os

from src.config import ORIGIN_BASE_URL


def hls_url(hls_master_key: str) -> str:
    key = hls_master_key
    if key.startswith("hls/"):
        key = key[len("hls/"):]
    return f"{ORIGIN_BASE_URL}/hls/{key}"


def thumb_url(thumb_key: str) -> str:
    key = thumb_key.strip("/")

    if key.startswith("thumbnails/"):
        key = key[len("thumbnails/"):]

    return f"{ORIGIN_BASE_URL}/thumb/{key}"


def live_thumb_url(stream_key: str) -> str:
    stream_key = stream_key.strip("/")

    hls_tpl = (os.getenv("LIVE_HLS_URL_TEMPLATE") or "").strip()
    if hls_tpl:
        hls_url_value = hls_tpl.format(stream_key=stream_key)
        base_dir = hls_url_value.rsplit("/", 1)[0]
        return f"{base_dir}/thumb.jpg"

    return f"{ORIGIN_BASE_URL}/live/{stream_key}/thumb.jpg"