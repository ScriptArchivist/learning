from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from model.user import User
from service import user as service
from errors import Missing, Duplicate

router = APIRouter(prefix="/user")
oauth2 = OAuth2PasswordBearer(tokenUrl="/user/token")

ACCESS_TOKEN_EXPIRE_MINUTES = 30


def unauthorized():
    raise HTTPException(
        status_code=401,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/token")
async def login(form: OAuth2PasswordRequestForm = Depends()):
    user = service.auth_user(form.username, form.password)
    if not user:
        unauthorized()

    token = service.create_access_token(
        data={"sub": user.name},
        expires=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/token")
def echo_token(token: str = Depends(oauth2)):
    return {"token": token}


# ---------- CRUD ----------

@router.get("")
def get_all() -> list[User]:
    return service.get_all()


@router.get("/{name}")
def get_one(name: str) -> User:
    try:
        return service.get_one(name)
    except Missing as e:
        raise HTTPException(status_code=404, detail=e.msg)


@router.post("", status_code=201)
def create(user: User) -> User:
    try:
        return service.create(user)
    except Duplicate as e:
        raise HTTPException(status_code=409, detail=e.msg)


@router.patch("/{name}")
def modify(name: str, user: User) -> User:
    try:
        return service.modify(name, user)
    except Missing as e:
        raise HTTPException(status_code=404, detail=e.msg)


@router.delete("/{name}")
def delete(name: str):
    try:
        service.delete(name)
        return {"status": "deleted"}
    except Missing as e:
        raise HTTPException(status_code=404, detail=e.msg)
