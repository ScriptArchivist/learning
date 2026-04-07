# web/__init__.py
from .video import router as video_router
from .video_api import router as video_api_router

__all__ = ["video_router", "video_api_router"]