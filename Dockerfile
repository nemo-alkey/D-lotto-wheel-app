# NZ Lotto Powerball — multi-stage Docker image
# Stage 1 builds/compiles Python dependencies; stage 2 carries only the
# installed packages and app code. Both services (FastAPI :8000,
# Streamlit :8501) run under supervisord as the non-root user `lotto`.

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /build

# Build tools are needed only if a wheel is missing for the platform
# (everything in requirements.txt ships manylinux wheels, but keep the
# toolchain here so exotic architectures still build — it never reaches
# the runtime image).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc \
    && rm -rf /var/lib/apt/lists/*

# Install into a dedicated prefix so the runtime stage can copy it wholesale.
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Runtime system deps: supervisord (process manager) + curl (healthcheck).
# Also create the non-root user the services run as.
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 lotto \
    && useradd --uid 1000 --gid lotto --create-home lotto

# Bring in only the installed Python packages from the builder stage.
COPY --from=builder /install /usr/local

# Trim package fat that ships inside some wheels (tests, __pycache__) —
# keeps the image closer to the 500 MB target.
RUN find /usr/local/lib/python3.11/site-packages \
      -type d \( -name "__pycache__" -o -name "tests" \) \
      -prune -exec rm -rf {} + 2>/dev/null || true

WORKDIR /app

# App code (.dockerignore keeps this lean: no venv, tests, .git, local DBs).
COPY --chown=lotto:lotto . .

# Persistent data dir (SQLite lives here via a symlink created by the
# entrypoint, so modules that open ./lotto.db work unchanged).
RUN mkdir -p /app/data && chown -R lotto:lotto /app

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Everything below runs as the non-root user (UID 1000).
USER lotto

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
