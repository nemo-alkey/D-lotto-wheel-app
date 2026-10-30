#!/usr/bin/env python3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


print("=" * 60)
print("LOTTO WHEEL APP - DEPLOYMENT HEALTH CHECK")
print("=" * 60)

checks = [
    ("Ruff Lint", [sys.executable, "-m", "ruff", "check", ".", "--ignore=F401,E402"]),
    ("Ruff Format", [sys.executable, "-m", "ruff", "format", ".", "--check"]),
    ("Mypy Types", [sys.executable, "-m", "mypy", ".", "--ignore-missing-imports"]),
    ("Fast Tests", [sys.executable, "-m", "pytest", "-m", "not slow", "-q", "--tb=no"]),
]

passed = 0
for name, cmd in checks:
    start = time.perf_counter()
    result = run(cmd)
    elapsed = (time.perf_counter() - start) * 1000
    if result.returncode == 0:
        print(f"PASS  {name} ({elapsed:.0f}ms)")
        passed += 1
    else:
        print(f"FAIL  {name}")
        if result.stdout:
            print(f"      {result.stdout[:200]}")

print(f"\nRESULT: {passed}/{len(checks)} passed")
sys.exit(0 if passed == len(checks) else 1)
