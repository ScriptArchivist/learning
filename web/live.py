# web/live.py
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from db.database import get_db_read, get_db_write
from errors import ForbiddenError, NotFoundError
from model.live import (
    LiveSessionActiveItemDTO,
    LiveSessionCreateRequest,
    LiveSessionCreateResponse,
    LiveSessionDTO,
)
from model.user import UserInDB
from service.live_service import (
    create_live_session,
    disconnect_live_session_by_stream_key,
    get_active_live_sessions,
    get_live_session_by_stream_key,
    get_live_thumbnail_url,
    stop_live_session,
)
from service.security import get_current_user as get_current_user_stub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live", tags=["live"], redirect_slashes=False)


def _check_internal_token_or_raise(token: str | None) -> None:
    expected = os.getenv("LIVE_INTERNAL_TOKEN")
    if not expected:
        return
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid internal token")


def _to_live_session_dto(session) -> LiveSessionDTO:
    base = LiveSessionDTO.model_validate(session)
    return base.model_copy(update={"thumbnail_url": get_live_thumbnail_url(session.stream_key)})


@router.post("/sessions", response_model=LiveSessionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_live_session_endpoint(
    body: LiveSessionCreateRequest,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        session, rtmp_url, hls_url, created = create_live_session(
            db=db,
            owner_id=current_user["id"],
            stream_key=body.stream_key,
            ttl_seconds=body.ttl_seconds,
            title=body.title,
            idempotency_key=idempotency_key,
        )

        thumbnail_url = get_live_thumbnail_url(session.stream_key)

        return LiveSessionCreateResponse(
            session=_to_live_session_dto(session),
            rtmp_url=rtmp_url,
            hls_url=hls_url,
            thumbnail_url=thumbnail_url,
        )
    except Exception as e:
        logger.exception("create_live_session_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/active", response_model=list[LiveSessionActiveItemDTO])
def get_active_live_sessions_endpoint(
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    try:
        items = get_active_live_sessions(db=db)
        return [LiveSessionActiveItemDTO.model_validate(item) for item in items]
    except Exception as e:
        logger.exception("get_active_live_sessions_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/disconnect/{stream_key}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_live_session_endpoint(
    stream_key: str,
    db: Session = Depends(get_db_write),
    internal_token: str | None = Header(default=None, alias="X-Live-Internal-Token"),
):
    try:
        _check_internal_token_or_raise(internal_token)
        disconnect_live_session_by_stream_key(db=db, stream_key=stream_key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except HTTPException:
        raise
    except Exception:
        logger.exception("disconnect_live_session_endpoint failed: stream_key=%s", stream_key)
        return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def stop_live_session_endpoint(
    session_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        stop_live_session(db=db, session_id=session_id, owner_id=current_user["id"])
        return None
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("stop_live_session_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{stream_key}", response_model=LiveSessionDTO)
def get_live_session_endpoint(
    stream_key: str,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    try:
        session = get_live_session_by_stream_key(db=db, stream_key=stream_key, owner_id=current_user["id"])
        return _to_live_session_dto(session)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("get_live_session_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))