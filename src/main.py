# src/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# CORS для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В разработке. В продакшене укажи конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Импортируем только video_router (explorer удален)
from web.video import router as video_router

# Подключаем только video_router
app.include_router(video_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "service": "Video Platform API",
        "version": "1.0",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "videos": "/api/v1/videos",
            "upload": "/api/v1/videos/upload/prepare"
        }
    }

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Video Platform API",
        "database": "connected"  # TODO: добавить проверку подключения к БД
    }