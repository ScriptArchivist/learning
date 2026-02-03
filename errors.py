# errors.py
"""
Кастомные исключения для приложения.
"""

class AppError(Exception):
    """Базовое исключение приложения."""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)

class NotFoundError(AppError):
    """Ресурс не найден."""
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404)

class Missing(AppError):  # ← ДОБАВЛЕНО
    """Ресурс отсутствует (альтернативное название для NotFoundError)."""
    def __init__(self, message: str = "Resource missing"):
        super().__init__(message, status_code=404)

class ValidationError(AppError):
    """Ошибка валидации данных."""
    def __init__(self, message: str = "Validation error"):
        super().__init__(message, status_code=400)

class ForbiddenError(AppError):
    """Доступ запрещен."""
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, status_code=403)

class ConflictError(AppError):
    """Конфликт (ресурс уже существует)."""
    def __init__(self, message: str = "Conflict"):
        super().__init__(message, status_code=409)

class Duplicate(AppError):  # ← ДОБАВЛЕНО
    """Дубликат (альтернативное название для ConflictError)."""
    def __init__(self, message: str = "Resource already exists"):
        super().__init__(message, status_code=409)

class UnauthorizedError(AppError):
    """Не авторизован."""
    def __init__(self, message: str = "Unauthorized"):
        super().__init__(message, status_code=401)

class InternalServerError(AppError):
    """Внутренняя ошибка сервера."""
    def __init__(self, message: str = "Internal server error"):
        super().__init__(message, status_code=500)