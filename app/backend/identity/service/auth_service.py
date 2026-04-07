from sqlalchemy.orm import Session

from db.models import User
from errors import NotFoundError
from identity.service.jwt_service import create_access_token, create_refresh_token
from identity.service.password_service import verify_password


def login(db: Session, username: str, password: str):
    user = db.query(User).filter(User.username == username).first()

    if not user:
        raise NotFoundError("Invalid credentials")

    if not verify_password(password, user.hashed_password):
        raise NotFoundError("Invalid credentials")

    access = create_access_token(user.id, user.role)
    refresh = create_refresh_token()

    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": 1800,
    }