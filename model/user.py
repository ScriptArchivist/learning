# model/user.py (полная версия)
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from datetime import datetime
from typing import Optional  # ← ВАЖНО: добавь эту строку!

class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50, examples=["john_doe"])
    email: EmailStr = Field(..., examples=["user@example.com"])

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100, examples=["strongpassword123"])

class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None
    storage_limit: Optional[int] = Field(None, gt=0)

class UserInDB(UserBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    is_active: bool
    created_at: datetime
    storage_limit: int
    used_storage: int
    hashed_password: str