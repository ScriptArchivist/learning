# service/user.py
from sqlalchemy.orm import Session

from db.models import User
from errors import NotFoundError


def get_user_by_id(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        raise NotFoundError("User not found")
    return user
