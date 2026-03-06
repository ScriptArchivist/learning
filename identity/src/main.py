from fastapi import FastAPI
from identity.web.auth import router as auth_router

app = FastAPI(
    title="Identity Service",
)

app.include_router(auth_router)