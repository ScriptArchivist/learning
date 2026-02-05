FROM python:3.11-slim

WORKDIR /app

# Устанавливаем системные зависимости для psycopg
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем всё остальное
COPY . .

# Устанавливаем пути Python
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Команда по умолчанию (для миграций)
CMD ["alembic", "upgrade", "head"]