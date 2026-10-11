# D2T — Disease-to-Target discovery platform
# Build:  docker compose build
# Run:    docker compose up -d

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Minimal OS deps (certs for HTTPS APIs; curl for healthcheck)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Application source
COPY . .

# Ensure runtime directories exist (volumes often mount over these)
RUN mkdir -p storage/registry storage/users storage/raw outputs data/raw

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8080/health || exit 1

# Bind all interfaces so host/port mapping works
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8080"]
