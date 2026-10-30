#!/usr/bin/env bash
# ============================================================================
# pre_deploy.sh — pre-deployment gates for the Lotto Wheel App.
#
# Runs lint, format, type checks, tests, a schema-migration check, and a
# verified database backup. Prints DEPLOY OK when every gate passes,
# otherwise DEPLOY BLOCKED with the failing steps listed.
#
# Usage (Git Bash / WSL / Linux):
#   bash scripts/pre_deploy.sh
# ============================================================================
set -u
cd "$(dirname "$0")/.."

PY=${PYTHON:-python}
FAILURES=()

run_step() {
    local name="$1"
    shift
    echo "============================================================"
    echo "RUN  $name"
    echo "============================================================"
    if "$@"; then
        echo "PASS  $name"
    else
        echo "FAIL  $name"
        FAILURES+=("$name")
    fi
    echo
}

run_step "Ruff Lint"       "$PY" -m ruff check . --ignore=F401,E402
run_step "Ruff Format"     "$PY" -m ruff format . --check
run_step "Mypy Types"      "$PY" -m mypy . --ignore-missing-imports
run_step "Tests"           "$PY" -m pytest -m "not slow" -q --tb=short
run_step "Migration Check" "$PY" migrate.py check
run_step "Database Backup" "$PY" database_backup.py backup --now

echo "============================================================"
if [ ${#FAILURES[@]} -eq 0 ]; then
    echo "DEPLOY OK"
    exit 0
else
    echo "DEPLOY BLOCKED — failing checks:"
    printf '  - %s\n' "${FAILURES[@]}"
    exit 1
fi
