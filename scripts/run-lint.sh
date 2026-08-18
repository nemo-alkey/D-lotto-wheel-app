#!/usr/bin/env bash
# run-lint.sh — runs the full code-quality suite.
#
#   1. ruff check           (linting)
#   2. ruff format --check  (formatting)
#   3. mypy .               (static type checking, strict)
#
# Exits non-zero if any step fails. Mirrors the CI lint job.
#
# Usage:  bash scripts/run-lint.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x venv/Scripts/python.exe ]; then
    PY=venv/Scripts/python.exe      # Windows venv
elif [ -x venv/bin/python ]; then
    PY=venv/bin/python              # POSIX venv
else
    PY=python
fi

echo "==> ruff check"
"$PY" -m ruff check .

echo "==> ruff format --check"
"$PY" -m ruff format --check .

echo "==> mypy"
"$PY" -m mypy .

echo "All quality checks passed."
