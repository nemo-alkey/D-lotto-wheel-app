#!/usr/bin/env python3
"""Racing Analytics Platform — entry point.

Delegates to the canonical v4.0 app in src.web_dashboard.app.

Usage:
    python app.py
    gunicorn app:create_app() -b 0.0.0.0:5000
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.web_dashboard.app import create_app

if __name__ == "__main__":
    try:
        from migrate import check_schema_version

        check_schema_version()
    except Exception:
        pass  # never block startup on a version-check failure

    app = create_app()
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "").lower() in ("true", "1")
    app.run(host=host, port=port, debug=debug)
