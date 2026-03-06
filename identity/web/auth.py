from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db_write
from identity.service.auth_service import login
from pydantic import BaseModel


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login_endpoint(body: LoginRequest, db: Session = Depends(get_db_write)):
    return login(db, body.username, body.password)