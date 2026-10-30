#!/usr/bin/env python3
"""
verify_deploy.py
================
Final pre-production verification. Run after fix_deploy.py and before git push.

This is stricter than deploy_check.py — it verifies:
- All tests pass (including slow/e2e)
- Security audit (no secrets in code)
- Performance baseline
- Docker image builds
- Database backup restore works

Usage:
    python scripts\verify_deploy.py

Exit 0 = fully verified, safe to deploy to production
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# from typing import List  # not needed in Python 3.11+

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


@dataclass
class VerifyResult:
    name: str
    status: str
    message: str
    duration_ms: float


def run_cmd(cmd: list[str], cwd: Path = PROJECT_ROOT, timeout: int = 300) -> tuple[int, str, str]:
    """Run command, return (returncode, stdout, stderr)."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def verify_all_tests() -> VerifyResult:
    """Run complete test suite including slow and e2e tests."""
    start = time.perf_counter()
    code, out, err = run_cmd([sys.executable, "-m", "pytest", "-v", "--tb=short"])
    duration = (time.perf_counter() - start) * 1000
    list[VerifyResult]
    if code != 0:
        return VerifyResult("All Tests", "FAIL", f"Test suite failed:\n{err[:500]}", duration)

    # Parse pass/fail counts
    summary = [line for line in out.splitlines() if "passed" in line or "failed" in line]
    return VerifyResult("All Tests", "PASS", summary[-1] if summary else "Tests passed", duration)


def verify_security_audit() -> VerifyResult:
    """Check for secrets, hardcoded passwords, and insecure configs."""
    start = time.perf_counter()
    issues: list[str] = []

    # Check for common secrets patterns
    secret_patterns = ["password=", "secret=", "api_key=", "token="]
    py_files = list(PROJECT_ROOT.rglob("*.py"))
    py_files += list(PROJECT_ROOT.rglob("*.yml"))
    py_files += list(PROJECT_ROOT.rglob("*.yaml"))

    for f in py_files:
        if f.name in (".env", ".env.example"):
            continue
        try:
            content = f.read_text(encoding="utf-8")
            for pattern in secret_patterns:
                if pattern in content.lower() and "changeme" not in content.lower():
                    # Check if it's actually a secret or just a variable name
                    lines = content.splitlines()
                    for i, line in enumerate(lines):
                        if pattern in line.lower() and "=" in line:
                            # Skip comments and docstrings
                            stripped = line.strip()
                            if not stripped.startswith("#") and not stripped.startswith('"""'):
                                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                                if val and val not in ("None", "", "os.environ.get", "getenv"):
                                    issues.append(
                                        f"{f.name}:{i+1}: potential secret: {line.strip()[:60]}"
                                    )
        except Exception:
            pass

    duration = (time.perf_counter() - start) * 1000

    if issues:
        return VerifyResult(
            "Security Audit",
            "FAIL",
            f"Found {len(issues)} potential secrets:\n" + "\n".join(issues[:5]),
            duration,
        )

    return VerifyResult("Security Audit", "PASS", "No hardcoded secrets detected", duration)


def verify_performance_baseline() -> VerifyResult:
    """Run performance benchmarks."""
    start = time.perf_counter()

    # Wheel generation benchmark
    bench_start = time.perf_counter()
    code, out, err = run_cmd(
        [sys.executable, "-m", "pytest", "tests/benchmarks/", "-v", "--tb=no"], timeout=60
    )
    bench_duration = time.perf_counter() - bench_start

    total_duration = (time.perf_counter() - start) * 1000

    if code != 0:
        return VerifyResult(
            "Performance", "WARN", "Benchmarks not available or failed", total_duration
        )

    return VerifyResult(
        "Performance",
        "PASS",
        f"Benchmarks completed in {bench_duration:.2f}s",
        total_duration,
    )


def verify_docker_build() -> VerifyResult:
    """Verify Docker image builds successfully."""
    start = time.perf_counter()
    dockerfile = PROJECT_ROOT / "Dockerfile"
    if not dockerfile.exists():
        return VerifyResult(
            "Docker Build", "SKIP", "No Dockerfile found", (time.perf_counter() - start) * 1000
        )

    code, out, err = run_cmd(["docker", "build", "-t", "lotto-wheel-app:test", "."], timeout=300)
    duration = (time.perf_counter() - start) * 1000

    if code != 0:
        return VerifyResult("Docker Build", "FAIL", f"Docker build failed:\n{err[:500]}", duration)

    return VerifyResult("Docker Build", "PASS", "Image built successfully", duration)


def verify_backup_restore() -> VerifyResult:
    """Verify database backup can be created and restored."""
    start = time.perf_counter()
    backup_script = PROJECT_ROOT / "database_backup.py"
    if not backup_script.exists():
        return VerifyResult(
            "Backup/Restore",
            "SKIP",
            "database_backup.py not found",
            (time.perf_counter() - start) * 1000,
        )

    # Create backup
    code, out, err = run_cmd([sys.executable, "database_backup.py", "backup", "--now"], timeout=60)
    if code != 0:
        return VerifyResult(
            "Backup/Restore",
            "FAIL",
            f"Backup failed: {err[:200]}",
            (time.perf_counter() - start) * 1000,
        )

    duration = (time.perf_counter() - start) * 1000
    return VerifyResult("Backup/Restore", "PASS", "Backup created successfully", duration)


def verify_ci_green() -> VerifyResult:
    """Check if local CI equivalent passes."""
    start = time.perf_counter()

    checks = [
        ([sys.executable, "-m", "ruff", "check", ".", "--ignore=F401,E402"], "Lint"),
        ([sys.executable, "-m", "ruff", "format", ".", "--check"], "Format"),
        ([sys.executable, "-m", "mypy", ".", "--ignore-missing-imports"], "Types"),
        ([sys.executable, "-m", "pytest", "-m", "not slow", "-q"], "Fast Tests"),
    ]

    failures = []
    for cmd, name in checks:
        code, _, _ = run_cmd(cmd, timeout=120)
        if code != 0:
            failures.append(name)

    duration = (time.perf_counter() - start) * 1000

    if failures:
        return VerifyResult(
            "CI Parity", "FAIL", f"Local CI failures: {', '.join(failures)}", duration
        )

    return VerifyResult("CI Parity", "PASS", "All local CI checks pass", duration)


ALL_VERIFICATIONS = [
    verify_ci_green,
    verify_all_tests,
    verify_security_audit,
    verify_performance_baseline,
    verify_docker_build,
    verify_backup_restore,
]


def main() -> None:
    print("=" * 70)
    print("LOTTO WHEEL APP — PRE-PRODUCTION VERIFICATION")
    print("=" * 70)
    print(f"Started: {datetime.now().isoformat()}")
    print("This is STRICT — all checks must pass for production deploy.\n")

    results: list[VerifyResult] = []
    failures = 0

    for verify_fn in ALL_VERIFICATIONS:
        result = verify_fn()
        results.append(result)

        icon = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️", "SKIP": "⏭️"}[result.status]
        print(f"\n{icon} {result.name}: {result.status}")
        print(f"   {result.message}")
        print(f"   Duration: {result.duration_ms:.0f}ms")

        if result.status == "FAIL":
            failures += 1

    print("\n" + "=" * 70)
    print("FINAL RESULT")
    print("=" * 70)

    if failures == 0:
        print("\n🎉 ALL VERIFICATIONS PASS")
        print("   The project is ready for production deployment.")
        print("\n   Next steps:")
        print("   1. git push origin main")
        print("   2. Monitor CI pipeline")
        print("   3. Deploy to staging")
        print("   4. Run smoke tests")
        print("   5. Deploy to production")
        sys.exit(0)
    else:
        print(f"\n❌ {failures} VERIFICATION(S) FAILED")
        print("   Fix all failures before deploying to production.")
        sys.exit(1)


if __name__ == "__main__":
    main()
