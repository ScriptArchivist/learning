import pytest
from datetime import datetime

from db.models import Video, VideoStatus
from service.video_status import transition_video_status, VideoStatusTransitionError


def make_video(status: VideoStatus) -> Video:
    v = Video()
    v.status = status
    v.error_message = None
    v.processed_at = None
    return v


def test_api_can_uploading_to_uploaded():
    v = make_video(VideoStatus.UPLOADING)
    transition_video_status(v, VideoStatus.UPLOADED, actor="api")
    assert v.status == VideoStatus.UPLOADED


def test_api_cannot_set_ready():
    v = make_video(VideoStatus.PROCESSING)
    with pytest.raises(VideoStatusTransitionError):
        transition_video_status(v, VideoStatus.READY, actor="api")


def test_worker_cannot_set_uploaded():
    v = make_video(VideoStatus.UPLOADING)
    with pytest.raises(VideoStatusTransitionError):
        transition_video_status(v, VideoStatus.UPLOADED, actor="worker")


def test_allowed_worker_flow():
    v = make_video(VideoStatus.UPLOADED)
    transition_video_status(v, VideoStatus.PROCESSING, actor="worker")
    assert v.status == VideoStatus.PROCESSING

    transition_video_status(v, VideoStatus.READY, actor="worker", processed_at=datetime(2020, 1, 1))
    assert v.status == VideoStatus.READY
    assert v.processed_at == datetime(2020, 1, 1)
    assert v.error_message is None


def test_processing_to_failed_requires_error_message():
    v = make_video(VideoStatus.PROCESSING)

    with pytest.raises(VideoStatusTransitionError):
        transition_video_status(v, VideoStatus.FAILED, actor="worker")

    transition_video_status(v, VideoStatus.FAILED, actor="worker", error_message="ffmpeg failed")
    assert v.status == VideoStatus.FAILED
    assert v.error_message == "ffmpeg failed"


def test_invalid_transition_raises():
    v = make_video(VideoStatus.UPLOADING)
    with pytest.raises(VideoStatusTransitionError):
        transition_video_status(v, VideoStatus.READY, actor="worker")  # UPLOADING -> READY нельзя