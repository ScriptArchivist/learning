from __future__ import annotations

import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("live_ttl_cleaner")


def _live_root() -> Path:
    storage_path = os.getenv("STORAGE_PATH", "/app/uploads")
    return Path(storage_path) / "live"


def _ttl_seconds() -> int:
    minutes = int(os.getenv("LIVE_TTL_MINUTES", "30"))
    return max(60, minutes * 60)


def _interval_seconds() -> int:
    return max(10, int(os.getenv("LIVE_TTL_INTERVAL_SECONDS", "60")))


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _dir_last_activity_ts(d: Path) -> float | None:
    """
    Надёжнее, чем d.stat().st_mtime:
    берём max(mtime) по файлам внутри, чтобы TTL работал на overlayfs.
    """
    try:
        # ищем любые файлы внутри (включая сегменты)
        mtimes = []
        for p in d.rglob("*"):
            if p.is_file():
                try:
                    mtimes.append(p.stat().st_mtime)
                except FileNotFoundError:
                    continue
        if mtimes:
            return max(mtimes)
        # если файлов нет — fallback на mtime самой директории
        return d.stat().st_mtime
    except FileNotFoundError:
        return None


def cleanup_once() -> None:
    root = _live_root()
    if not root.exists():
        return

    root_resolved = root.resolve()
    ttl = _ttl_seconds()
    now = _now_ts()

    for d in root.iterdir():
        if not d.is_dir():
            continue

        # safety: must be inside root
        try:
            dr = d.resolve()
            dr.relative_to(root_resolved)
        except Exception:
            logger.error("skip suspicious path: %s", d)
            continue

        last_ts = _dir_last_activity_ts(dr)
        if last_ts is None:
            continue

        age = now - last_ts
        if age < ttl:
            continue

        try:
            shutil.rmtree(dr)
            logger.info("TTL cleanup removed: %s (age=%ss)", dr, int(age))
        except Exception:
            logger.exception("TTL cleanup failed for: %s", dr)


def main() -> None:
    root = _live_root()
    logger.info(
        "live TTL cleaner started: root=%s ttl=%ss interval=%ss",
        root,
        _ttl_seconds(),
        _interval_seconds(),
    )

    while True:
        cleanup_once()
        time.sleep(_interval_seconds())


if __name__ == "__main__":
    main()