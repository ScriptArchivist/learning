from model.user import User
from errors import Missing, Duplicate
from service.security import hash_password

fakes = [
    User(name="kwiiobo", hash=hash_password("abc")),
    User(name="ermagerd", hash=hash_password("xyz")),
]


def find(name: str) -> User | None:
    for u in fakes:
        if u.name == name:
            return u
    return None


def get_all() -> list[User]:
    return fakes


def get_one(name: str) -> User:
    user = find(name)
    if not user:
        raise Missing(msg=f"Missing user {name}")
    return user


def create(user: User) -> User:
    if find(user.name):
        raise Duplicate(msg=f"Duplicate user {user.name}")
    fakes.append(user)
    return user


def modify(name: str, user: User) -> User:
    existing = find(name)
    if not existing:
        raise Missing(msg=f"Missing user {name}")
    existing.hash = user.hash
    return existing


def delete(name: str) -> None:
    user = find(name)
    if not user:
        raise Missing(msg=f"Missing user {name}")
    fakes.remove(user)
