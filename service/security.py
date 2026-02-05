# service/security.py
"""
Заглушка для аутентификации. Позже заменим на вызов Auth Service.
"""

from typing import Optional, Dict, Any

def get_current_user() -> Dict[str, Any]:
    """Заглушка - возвращает тестового пользователя."""
    return {
        "id": 1,
        "username": "test_user", 
        "email": "test@example.com",
        "is_active": True,
        "storage_limit": 10737418240,  # 10GB
        "used_storage": 0
    }

def verify_storage_limit(user: Dict[str, Any], file_size: int) -> bool:
    """Заглушка - всегда разрешает."""
    return True