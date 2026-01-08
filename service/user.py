import os
from datetime import timedelta, datetime
from jose import jwt, JWTError
from model.user import User
from service.security import verify_password

if os.getenv("CRYPTID_UNIT_TEST"):
    from fake import user as data
else:
    from data import user as data


SECRET_KEY = "keep-it-secret-keep-it-safe"
ALGORITHM = "HS256"


# ---------- AUTH ----------

def lookup_user(username: str) -> User | None:
    return data.find(username)


def auth_user(name: str, plain: str) -> User | None:
    user = lookup_user(name)
    if not user:
        return None
    if not verify_password(plain, user.hash):
        return None
    return user


def create_access_token(data: dict, expires: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_jwt_username(token: str) -> str | None:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None


def get_current_user(token: str) -> User | None:
    username = get_jwt_username(token)
    if not username:
        return None
    return lookup_user(username)


# ---------- CRUD ----------

def get_all() -> list[User]:
    return data.get_all()


def get_one(name: str) -> User:
    return data.get_one(name)


def create(user: User) -> User:
    return data.create(user)


def replace(name: str, user: User) -> User:
    data.delete(name)
    return data.create(user)


def modify(name: str, user: User) -> User:
    return data.modify(name, user)


def delete(name: str) -> None:
    return data.delete(name)
