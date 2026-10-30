#!/usr/bin/env python3
"""
scripts/smoke_config.py — Post-deploy configuration smoke test.

Hits the live API to confirm the deployed configuration is what you expect:
public config health is served, secrets never leak, and the admin config
endpoint is actually protected.

Usage:
    python scripts/smoke_config.py [--base-url http://localhost:8000]
                                   [--expect-version 2.0.0]
                                   [--admin-token <jwt>]

Exit codes:
    0 = all smoke checks pass
    1 = one or more checks failed
"""

from __future__ import annotations

import argparse
import sys

import requests

# Windows consoles default to cp1252 — allow Unicode status output.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


def main() -> None:
    parser = argparse.ArgumentParser(description="Post-deploy config smoke test")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--expect-version", default=None, help="Expected API version")
    parser.add_argument("--admin-token", default=None, help="Admin JWT (optional)")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    # 1. Public config health endpoint is up and sane.
    try:
        resp = requests.get(f"{base}/config/health", timeout=args.timeout)
        if resp.status_code != 200:
            check("GET /config/health", False, f"HTTP {resp.status_code}")
            body = {}
        else:
            body = resp.json()
            check("GET /config/health", True, f"env={body.get('environment')}")
    except requests.RequestException as exc:
        check("GET /config/health", False, str(exc))
        body = {}

    if body:
        check(
            "version matches",
            args.expect_version is None or body.get("version") == args.expect_version,
            f"got {body.get('version')!r}, expected {args.expect_version!r}",
        )
        check("features exposed", isinstance(body.get("features"), dict))
        leaked = [k for k in body if any(s in k.lower() for s in ("secret", "pass", "token"))]
        check("no secret fields in /config/health", not leaked, ", ".join(leaked))

    # 2. System health endpoint responds (503 allowed — reported, not fatal).
    try:
        resp = requests.get(f"{base}/health", timeout=args.timeout)
        check(
            "GET /health",
            resp.status_code in (200, 503),
            f"HTTP {resp.status_code} status={resp.json().get('status')}",
        )
    except (requests.RequestException, ValueError) as exc:
        check("GET /health", False, str(exc))

    # 3. Admin config endpoint rejects anonymous callers.
    try:
        resp = requests.get(f"{base}/admin/config", timeout=args.timeout)
        check(
            "GET /admin/config requires auth", resp.status_code == 401, f"HTTP {resp.status_code}"
        )
    except requests.RequestException as exc:
        check("GET /admin/config requires auth", False, str(exc))

    # 4. With an admin token: config is served with secrets masked.
    if args.admin_token:
        try:
            resp = requests.get(
                f"{base}/admin/config",
                headers={"Authorization": f"Bearer {args.admin_token}"},
                timeout=args.timeout,
            )
            check("GET /admin/config (admin)", resp.status_code == 200, f"HTTP {resp.status_code}")
            if resp.status_code == 200:
                config = resp.json().get("config", {})
                check(
                    "secrets masked",
                    config.get("SECRET_KEY") in ("********", None),
                    f"SECRET_KEY={config.get('SECRET_KEY')!r}",
                )
        except requests.RequestException as exc:
            check("GET /admin/config (admin)", False, str(exc))

    print()
    if failures:
        print(f"❌ SMOKE TEST FAILED: {', '.join(failures)}")
        sys.exit(1)
    print("🎉 All config smoke checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
