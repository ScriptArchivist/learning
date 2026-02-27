# web/live.py
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from db.database import get_db_read, get_db_write
from errors import ForbiddenError, NotFoundError
from model.live import LiveSessionCreateResponse, LiveSessionDTO
from model.user import UserInDB
from service.live_service import create_live_session, get_live_session, stop_live_session
from service.security import get_current_user as get_current_user_stub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live", tags=["live"], redirect_slashes=False)


@router.post("/sessions", response_model=LiveSessionCreateResponse, status_code=status.HTTP_201_CREATED)
def create_live_session_endpoint(
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        session, rtmp_url, hls_url = create_live_session(db=db, owner_id=current_user["id"])
        return LiveSessionCreateResponse(
            session=LiveSessionDTO.model_validate(session),
            rtmp_url=rtmp_url,
            hls_url=hls_url,
        )
    except Exception as e:
        logger.exception("create_live_session_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sessions/{session_id}/stop", response_model=LiveSessionDTO)
def stop_live_session_endpoint(
    session_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_write),
):
    try:
        session = stop_live_session(db=db, session_id=session_id, owner_id=current_user["id"])
        return LiveSessionDTO.model_validate(session)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception("stop_live_session_endpoint failed")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/sessions/{session_id}", response_model=LiveSessionDTO)
def get_live_session_endpoint(
    session_id: int,
    current_user: UserInDB = Depends(get_current_user_stub),
    db: Session = Depends(get_db_read),
):
    try:
        session = get_live_session(db=db, session_id=session_id, owner_id=current_user["id"])
        return LiveSessionDTO.model_validate(session)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))