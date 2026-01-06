from fastapi import APIRouter, HTTPException
from model.explorer import Explorer
import data.explorer as service
from errors import Duplicate, Missing


router = APIRouter(prefix = "/explorer")


@router.get("")
@router.get("/")
def get_all() -> list[Explorer]:
    return service.get_all()


@router.get("/{name}")
def get_one(name: str) -> Explorer:
    try:
        return service.get_one(name)
    except Missing as exc:
        raise HTTPException(status_code=404, detail=exc.msg)


@router.post("", status_code=201)
@router.post("/", status_code=201)
def create(explorer: Explorer) -> Explorer:
    try:
        return service.create(explorer)
    except Duplicate as exc:
        raise HTTPException(status_code=404, detail=exc.msg)


@router.patch("/{name}")
def modify(name: str, explorer: dict) -> Explorer:
    try:
        return service.modify(name, explorer)
    except Missing as exc:
        raise HTTPException(status_code=404, detail=exc.msg)


@router.put("/{name}")
def replace(name: str, explorer: Explorer) -> Explorer:
    return service.replace(name, explorer.dict())


@router.delete("/{name}")
def delete(name: str):
    try:
        service.delete(name)
        return {"status": "success", "message": f"Explorer {name} deleted"}
    except Missing as exc:
        raise HTTPException(status_code=404, detail=exc.msg)