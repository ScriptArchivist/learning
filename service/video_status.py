# service/video_status.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Set, Tuple

from db.models import Video, VideoStatus


Actor = Literal["api", "worker"]


class VideoStatusTransitionError(ValueError):
    pass


@dataclass(frozen=True)
class TransitionRule:
    actor: Actor
    from_status: VideoStatus
    to_status: VideoStatus


# Допустимые переходы + кто имеет право
_ALLOWED: Set[TransitionRule] = {
    # API
    TransitionRule("api", VideoStatus.UPLOADING, VideoStatus.UPLOADED),

    # Worker
    TransitionRule("worker", VideoStatus.UPLOADED, VideoStatus.PROCESSING),
    TransitionRule("worker", VideoStatus.PROCESSING, VideoStatus.READY),
    TransitionRule("worker", VideoStatus.PROCESSING, VideoStatus.FAILED),
}


def transition_video_status(
    video: Video,
    target_status: VideoStatus,
    *,
    actor: Actor,
    error_message: str | None = None,
) -> None:
    """
    Единый метод смены статуса.

    - проверяет допустимость перехода
    - проверяет права actor (api/worker)
    - при FAILED выставляет error_message (если передали)
    """
    current = video.status

    if current == target_status:
        # идемпотентно: повторная установка того же статуса допустима
        return

    rule = TransitionRule(actor, current, target_status)
    if rule not in _ALLOWED:
        raise VideoStatusTransitionError(
            f"Forbidden transition: actor={actor} {current.value} -> {target_status.value}"
        )

    video.status = target_status

    if target_status == VideoStatus.FAILED:
        video.error_message = error_message or video.error_message
    else:
        # при успешных переходах очищаем ошибку
        video.error_message = None