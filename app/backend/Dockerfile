FROM python:3.11-slim

WORKDIR /app

RUN sed -i 's|http://deb.debian.org/debian|https://mirror.yandex.ru/debian|g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's|http://deb.debian.org/debian-security|https://mirror.yandex.ru/debian-security|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y \
        gcc \
        libpq-dev \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 10001 appuser

COPY app/backend/requirements.txt .
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app/backend /app

RUN mkdir -p /app/uploads /app/uploads/hls /app/uploads/live \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1