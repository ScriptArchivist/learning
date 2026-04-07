# service/video_status.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Set, Tuple

from db.models import Video, VideoStatus


class VideoStatusTransitionError(Exception):
    """Неверный переход статуса или нет прав у actor."""
    pass


# ====== Разрешённые переходы (state machine) ======
_ALLOWED_TRANSITIONS: Dict[VideoStatus, Set[VideoStatus]] = {
    VideoStatus.UPLOADING: {VideoStatus.UPLOADED},
    VideoStatus.UPLOADED: {VideoStatus.PROCESSING},
    VideoStatus.PROCESSING: {VideoStatus.READY, VideoStatus.FAILED},
    VideoStatus.READY: set(),
    VideoStatus.FAILED: set(),
}

# ====== Права actor на конкретные переходы ======
_ALLOWED_BY_ACTOR: Dict[str, Set[Tuple[VideoStatus, VideoStatus]]] = {
    "api": {
        (VideoStatus.UPLOADING, VideoStatus.UPLOADED),
    },
    "worker": {
        (VideoStatus.UPLOADED, VideoStatus.PROCESSING),
        (VideoStatus.PROCESSING, VideoStatus.READY),
        (VideoStatus.PROCESSING, VideoStatus.FAILED),
    },
}


def transition_video_status(
    video: Video,
    target_status: VideoStatus,
    actor: str,
    *,
    error_message: Optional[str] = None,
    processed_at: Optional[datetime] = None,
) -> None:
    """
    Единый способ менять статус видео.

    Правила:
    - Строгие разрешённые переходы:
        UPLOADING -> UPLOADED -> PROCESSING -> READY
        PROCESSING -> FAILED
    - Права:
        api НЕ может ставить READY/PROCESSING/FAILED
        worker НЕ может ставить UPLOADED
    - При FAILED: обязателен error_message
    """

    current = video.status

    # 1) Проверка перехода
    allowed_targets = _ALLOWED_TRANSITIONS.get(current, set())
    if target_status not in allowed_targets:
        raise VideoStatusTransitionError(
            f"Invalid status transition: {current.value} -> {target_status.value}"
        )

    # 2) Проверка actor
    actor_rules = _ALLOWED_BY_ACTOR.get(actor)
    if not actor_rules:
        raise VideoStatusTransitionError(f"Unknown actor: {actor!r}")

    if (current, target_status) not in actor_rules:
        raise VideoStatusTransitionError(
            f"Actor '{actor}' is not allowed: {current.value} -> {target_status.value}"
        )

    # 3) Спец-правила FAILED/READY
    if target_status == VideoStatus.FAILED:
        if not error_message:
            raise VideoStatusTransitionError("FAILED transition requires error_message")
        video.error_message = error_message

    if target_status == VideoStatus.READY:
        # READY = успешно обработано -> ошибку чистим
        video.error_message = None
        video.processed_at = processed_at or datetime.utcnow()

    # 4) Применяем
    video.status = target_status