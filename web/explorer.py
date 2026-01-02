from fastapi import APIRouter
from model.explorer import Explorer
import fake.explorer as service

router = APIRouter(prefix = "/explorer")

@router.get("/")
def get_all() -> list[Explorer]:
    return service.get_all()

@router.get("/{name}")
def get_one(name: str) -> Explorer | None:
    return service.get_one(name)

@router.post("/")
def create(explorer: Explorer) -> Explorer:
    return service.create(explorer)

@router.patch("/{name}")
def modify(name: str, explorer: Explorer) -> Explorer:
    return service.modify(explorer)

@router.put("/{name}")
def replace(name: str, explorer: Explorer) -> Explorer:
    return service.replace(explorer)

@router.delete("/{name}")
def delete(name: str):
    if service.delete(name):
        return {"status": True}
    else:
        return {"status": False}