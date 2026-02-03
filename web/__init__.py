# web/__init__.py
from .video import router as video_router
# Удалил импорт explorer_router

__all__ = ["video_router"]  # Удалил explorer_router