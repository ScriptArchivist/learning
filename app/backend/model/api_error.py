# model/api_error.py
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel


class ErrorDTO(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorDTO