#!/usr/bin/env bash
# docker-entrypoint.sh — container startup for the lotto app image.
#
#   1. Point ./lotto.db at the persistent volume (/app/data) so the many
#      modules that open "lotto.db" relative to the workdir work unchanged.
#   2. Run Alembic migrations (when alembic is set up in the image).
#   3. exec supervisord (FastAPI + Streamlit). `exec` replaces this shell,
#      so Docker's SIGTERM lands directly on supervisord, which forwards it
#      to both services — that IS the graceful-shutdown path (no zombie
#      shell holding the signal).
set -euo pipefail

DATA_DIR="${DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"

# --- Persistent database symlink -------------------------------------------
# The named volume is mounted at /app/data. If a lotto.db got baked into
# the image (or a previous container left one), move it onto the volume
# once, then always work through the symlink.
if [ ! -L /app/lotto.db ]; then
    if [ -f /app/lotto.db ]; then
        mv /app/lotto.db "$DATA_DIR/lotto.db"
    fi
    ln -s "$DATA_DIR/lotto.db" /app/lotto.db
fi

# --- Migrations -------------------------------------------------------------
if [ -f /app/migrate.py ] && [ -d /app/alembic ]; then
    echo "[entrypoint] Running Alembic migrations..."
    # Don't abort startup on migration failure — log and let the app's own
    # startup schema check surface the problem in the logs.
    if ! python /app/migrate.py upgrade; then
        echo "[entrypoint] WARNING: migrations failed; starting anyway." >&2
    fi
fi

# --- Services ---------------------------------------------------------------
echo "[entrypoint] Starting FastAPI (:8000) and Streamlit (:8501) via supervisord..."
exec supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
