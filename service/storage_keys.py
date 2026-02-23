# service/storage_keys.py
"""
Backward-compatible module.

Единый источник правды для storage keys: service.paths
Этот файл оставлен для совместимости со старым кодом (worker и т.п.).
"""

from __future__ import annotations

from service.paths import (
    original_path as original_key,
    thumbnail_path as thumbnail_key,
    thumbnail_dir,
    hls_dir,
    hls_master as hls_master_key,
    hls_variant_playlist as hls_variant_playlist_key,
    hls_variant_segment as hls_variant_segment_key,
)