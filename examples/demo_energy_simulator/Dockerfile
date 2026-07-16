# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AUTH_ENABLED=false

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 5000

# Single worker keeps the on-disk result store consistent (matches the original).
CMD ["gunicorn", "-w", "1", "-k", "gthread", "--threads", "4", "-b", "0.0.0.0:5000", "app:app"]
