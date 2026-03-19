# service/content_urls.py
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