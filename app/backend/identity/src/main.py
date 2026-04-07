from fastapi import FastAPI
from identity.web.auth import router as auth_router
from src.metrics import install_http_metrics

app = FastAPI(
    title="Identity Service",
)

install_http_metrics(app, "identity-service")

app.include_router(auth_router)