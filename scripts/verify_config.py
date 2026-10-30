#!/usr/bin/env python3
"""
scripts/verify_config.py — Pre-deploy configuration verification.

Loads the application configuration exactly as the app would (including the
production rule that ignores .env files) and reports errors and warnings
WITHOUT printing secret values.

Usage:
    python scripts/verify_config.py            # human-readable report
    python scripts/verify_config.py --json     # machine-readable report

Exit codes:
    0 = configuration is valid, safe to deploy
    1 = critical configuration errors — DO NOT deploy
    2 = warnings only, deploy with caution
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# Windows consoles default to cp1252 — allow Unicode status output.
try:
    if sys.stdout.encoding and sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except (AttributeError, OSError):
    pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-deploy config verification")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    # Mirror config/settings.py: production ignores .env files entirely.
    env_file: str | None = str(PROJECT_ROOT / ".env")
    if os.environ.get("ENVIRONMENT", "").strip().lower() == "production":
        env_file = None

    from pydantic import ValidationError

    from config.settings import Settings
    from config_manager import collect_config_issues

    try:
        cfg = Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        if args.json:
            print(json.dumps({"deployable": False, "errors": problems}, indent=2))
        else:
            print("❌ Configuration error — invalid environment settings:")
            for problem in problems:
                print(f"   - {problem}")
        sys.exit(1)

    errors, warnings = collect_config_issues(cfg)

    if args.json:
        print(
            json.dumps(
                {
                    "deployable": not errors,
                    "environment": cfg.ENVIRONMENT,
                    "errors": errors,
                    "warnings": warnings,
                    "config": cfg.masked_dump(),
                },
                indent=2,
            )
        )
    else:
        print("=" * 70)
        print("PRE-DEPLOY CONFIGURATION VERIFICATION")
        print("=" * 70)
        print(f"Environment : {cfg.ENVIRONMENT}")
        print(f"Debug       : {cfg.DEBUG}")
        print(
            f"Database    : {cfg.database_backend} (pooling: {cfg.database_backend == 'postgresql'})"
        )
        print(f"Redis       : {'configured' if cfg.REDIS_URL else 'in-memory fallback'}")
        print(f"SMTP        : {'configured' if cfg.smtp_configured else 'not configured'}")
        print(f"Stripe      : {'configured' if cfg.stripe_configured else 'not configured'}")
        print(
            "Features    : "
            + ", ".join(
                f"{name}={'on' if on else 'off'}" for name, on in cfg.feature_flags().items()
            )
        )
        print()
        for err in errors:
            print(f"❌ {err}")
        for warn in warnings:
            print(f"⚠️  {warn}")
        if not errors and not warnings:
            print("✅ Configuration is valid — safe to deploy.")

    sys.exit(1 if errors else (2 if warnings else 0))


if __name__ == "__main__":
    main()
