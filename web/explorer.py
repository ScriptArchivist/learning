# web/explorer.py
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

# Создаем router
router = APIRouter(prefix="/explorer")

# Импорты
from db.database import get_session
from model.explorer import Explorer
import service.explorer as service
from errors import Duplicate, Missing


@router.get("")
@router.get("/")
def get_all(db: Session = Depends(get_session)) -> list[Explorer]:
    return service.get_all(db)


@router.get("/{name}")
def get_one(name: str, db: Session = Depends(get_session)) -> Explorer:
    try:
        return service.get_one(db, name)
    except Missing as exc:
        raise HTTPException(status_code=404, detail=exc.msg)


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create(explorer: Explorer, db: Session = Depends(get_session)) -> Explorer:
    try:
        return service.create(db, explorer)
    except Duplicate as exc:
        raise HTTPException(status_code=409, detail=exc.msg)


@router.patch("/{name}")
def modify(name: str, explorer: dict, db: Session = Depends(get_session)) -> Explorer:
    try:
        return service.modify(db, name, explorer)
    except Missing as exc:
        raise HTTPException(status_code=404, detail=exc.msg)
    except Duplicate as exc:
        raise HTTPException(status_code=409, detail=exc.msg)


@router.put("/{name}")
def replace(name: str, explorer: Explorer, db: Session = Depends(get_session)) -> Explorer:
    try:
        return service.replace(db, name, explorer)
    except Missing as exc:
        raise HTTPException(status_code=404, detail=exc.msg)
    except Duplicate as exc:
        raise HTTPException(status_code=409, detail=exc.msg)


@router.delete("/{name}")
def delete(name: str, db: Session = Depends(get_session)):
    try:
        result = service.delete(db, name)
        if result:
            return {"status": "success", "message": f"Explorer {name} deleted"}
    except Missing as exc:
        raise HTTPException(status_code=404, detail=exc.msg)