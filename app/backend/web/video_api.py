# web/video_api.py
"""
Video API (metadata & playback)

Этап 3: отдельный сервис для Flutter:
- POST /videos
- GET /videos/{id}
- GET /videos
- GET /videos/{id}/playback
- PATCH /videos/{id}
- DELETE /videos/{id}

Важно:
- upload / file / thumbnail / hls / share / watch — НЕ часть video-api
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from db.database import get_db_read, get_db_write
from errors import ForbiddenError, NotFoundError, ValidationError
from model.video import VideoCreate, VideoFilter, VideoPagination, VideoStatus, VideoUpdate, Visibility
from model.video_contract import VideoDetailDTO, VideoListResponse
from service.video_presenter import to_detail, to_list_item
from service.video_service import create_video, delete_video, get_video, get_videos, update_video
from model.user import UserInDB


def get_current_user_stub() -> UserInDB:
    return {
        "id": 1,
        "username": "replica_test_user",
        "email": "replica_test_user@example.com",
        "role": "user",
        "is_active": True,
    }


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/videos", tags=["videos"], redirect_slashes=False)


def get_video_api_read_db(
    consistent: bool = Query(False, description="Read from master when true"),
):
    dependency = get_db_write if consistent else get_db_read
    yield from dependency()


@router.post("", response_model=VideoDetailDTO, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=VideoDetailDTO, status_code=status.HTTP_201_CREATED)
def create_video_endpoint(
    video_data: VideoCreate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        video = create_video(db=db, video_data=video_data, user_id=current_user["id"])
        return to_detail(video)
    except (ValidationError, ForbiddenError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=VideoListResponse)
@router.get("/", response_model=VideoListResponse)
def list_videos_endpoint(
    status: Optional[VideoStatus] = Query(None),
    visibility: Optional[Visibility] = Query(None),
    owner_id: Optional[int] = Query(None),
    min_duration: Optional[float] = Query(None),
    max_duration: Optional[float] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_video_api_read_db),
):
    filter_data = VideoFilter(
        status=status,
        visibility=visibility,
        owner_id=owner_id,
        min_duration=min_duration,
        max_duration=max_duration,
        search_text=search,
    )
    pagination = VideoPagination(page=page, per_page=per_page)

    videos, total = get_videos(db, filter_data, pagination, user_id=current_user["id"])
    return VideoListResponse(
        items=[to_list_item(v) for v in videos],
        page=page,
        per_page=per_page,
        total=total,
    )


@router.get("/{video_id}", response_model=VideoDetailDTO)
def get_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_video_api_read_db),
):
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        return to_detail(video)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.patch("/{video_id}", response_model=VideoDetailDTO)
def update_video_endpoint(
    video_id: int,
    payload: VideoUpdate,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        video = update_video(
            db=db,
            video_id=video_id,
            update_data=payload,
            user_id=current_user["id"],
        )
        return to_detail(video)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video_endpoint(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        delete_video(
            db=db,
            video_id=video_id,
            user_id=current_user["id"],
        )
        return None
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{video_id}/playback")
def get_video_playback(
    video_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_video_api_read_db),
):
    try:
        video = get_video(db, video_id, user_id=current_user["id"])
        item = to_list_item(video)
        return {"video_id": video.id, "hls_ready": item.hls_ready, "hls_url": item.hls_url}
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))