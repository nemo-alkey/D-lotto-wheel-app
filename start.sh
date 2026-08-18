#!/bin/bash
set -e

echo "=== NZ Lotto Powerball — Startup ==="
echo ""

# ---------------------------------------------------------------------------
# Detect environment: Docker vs local/Codespaces
# ---------------------------------------------------------------------------
IN_DOCKER=false
if [ -f /.dockerenv ] || [ -f /app/supervisord.conf ]; then
    IN_DOCKER=true
fi

if $IN_DOCKER; then
    # =======================================================================
    # Docker startup
    # =======================================================================
    echo "[env] Docker container detected"

    if [ -d "/data" ]; then
        if [ ! -f "/data/lotto_working.db" ]; then
            echo "[init] Copying bundled lotto_working.db to /data/ ..."
            cp /app/lotto_working.db /data/lotto_working.db
        else
            echo "[init] Using existing lotto_working.db from /data/"
        fi
        ln -sf /data/lotto_working.db /app/lotto_working.db
    fi

    if [ ! -f "/app/lotto.db" ]; then
        echo "[init] Creating lotto.db schema..."
        python3 -c "
import database
database.initialize_database()
print('[init] lotto.db schema created.')
"
        if [ -d "/data" ] && [ -f "/app/lotto.db" ]; then
            mv /app/lotto.db /data/lotto.db
            ln -sf /data/lotto.db /app/lotto.db
        fi
    fi

    echo "[init] Draw count: $(python3 -c "
from lotto_wheels import load_draws
d = load_draws()
print(len(d))" 2>/dev/null || echo '0 (waiting for data)')"
    echo ""
    echo "=== Starting services ==="
    echo "  API:        http://localhost:8000"
    echo "  Dashboard:  http://localhost:8501"
    echo ""

    exec /usr/local/bin/supervisord -c /app/supervisord.conf

else
    # =======================================================================
    # Local / GitHub Codespaces startup
    # =======================================================================
    echo "[env] Local / Codespaces environment detected"
    echo ""

    # Ensure pip dependencies are installed
    if [ -f requirements.txt ]; then
        echo "[pip] Installing dependencies..."
        pip install --upgrade pip -q
        pip install -r requirements.txt -q
        echo "[pip] Done."
    fi

    # Ensure database exists
    if [ ! -f lotto.db ]; then
        echo "[db] Initialising lotto.db..."
        python -c "
import database
database.initialize_database()
print('[db] lotto.db created.')
"
    fi

    # Show draw count
    echo "[db] Draw count: $(python -c "
from lotto_wheels import load_draws
d = load_draws()
print(len(d))" 2>/dev/null || echo '0 (run python update_draws.py to populate)')"
    echo ""

    # Start both services in background
    echo "=== Starting services ==="
    echo "  API:        http://localhost:8000"
    echo "  Dashboard:  http://localhost:8501"
    echo ""

    # Start FastAPI
    echo "[api] Starting FastAPI server on port 8000..."
    uvicorn api:app --host 0.0.0.0 --port 8000 &
    API_PID=$!

    # Start Streamlit
    echo "[dashboard] Starting Streamlit dashboard on port 8501..."
    streamlit run dashboard.py --server.port 8501 --server.address 0.0.0.0 &
    DASH_PID=$!

    echo ""
    echo "Both services started in background."
    echo "  API PID:       $API_PID"
    echo "  Dashboard PID: $DASH_PID"
    echo ""
    echo "Press Ctrl+C to stop both services."

    # Trap Ctrl+C to clean up
    cleanup() {
        echo ""
        echo "Shutting down..."
        kill $API_PID 2>/dev/null || true
        kill $DASH_PID 2>/dev/null || true
        wait $API_PID 2>/dev/null || true
        wait $DASH_PID 2>/dev/null || true
        echo "Done."
    }
    trap cleanup EXIT INT TERM

    # Wait for either process to exit
    wait $API_PID $DASH_PID
fi
