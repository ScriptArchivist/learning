# web/live.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, status
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
    get_active_live_sessions,
    get_live_session_by_stream_key,
    stop_live_session,
)
from service.security import get_current_user as get_current_user_stub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live", tags=["live"], redirect_slashes=False)


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
            idempotency_key=idempotency_key,
        )

        return LiveSessionCreateResponse(
            session=LiveSessionDTO.model_validate(session),
            rtmp_url=rtmp_url,
            hls_url=hls_url,
        )
    except Exception as e:
        logger.exception("create_live_session_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/active", response_model=list[LiveSessionActiveItemDTO])
def get_active_live_sessions_endpoint(
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    """
    Viewer-ready список активных live-сессий.

    ВАЖНО:
    Этот маршрут должен быть объявлен РАНЬШЕ, чем /sessions/{stream_key},
    иначе FastAPI интерпретирует 'active' как stream_key.
    """
    try:
        items = get_active_live_sessions(db=db)
        return [LiveSessionActiveItemDTO.model_validate(item) for item in items]
    except Exception as e:
        logger.exception("get_active_live_sessions_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


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
        return LiveSessionDTO.model_validate(session)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("get_live_session_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))