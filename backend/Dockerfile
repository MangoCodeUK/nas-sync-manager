# NAS Sync Manager — backend image (FastAPI + Uvicorn).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# rsync is the transfer engine for the rsync provider; openssh-client lets it use
# SSH transport (rsync -e ssh) as an alternative to the daemon protocol. Installed
# before the pip layer because these change far less often than requirements.txt.
RUN apt-get update \
 && apt-get install -y --no-install-recommends rsync openssh-client \
 && rm -rf /var/lib/apt/lists/*

# Install dependencies first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code + migrations.
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

# Data volume (SQLite lives here in production).
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# The healthcheck in docker-compose hits /health via urllib (no curl needed).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
