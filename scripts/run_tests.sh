#!/usr/bin/env bash
# run_tests.sh — test runner for environments without `make`.
# Usage:
#   scripts/run_tests.sh              # all tests (tests/ + legacy test_lotto.py)
#   scripts/run_tests.sh unit         # unit tests only
#   scripts/run_tests.sh integration  # integration tests only (requires DB)
#   scripts/run_tests.sh fast         # everything except slow tests
#   scripts/run_tests.sh legacy       # legacy test_lotto.py suite
set -euo pipefail
cd "$(dirname "$0")/.."

PYTEST="venv/Scripts/python.exe -m pytest"
[ -x venv/Scripts/python.exe ] || PYTEST="python -m pytest"

case "${1:-all}" in
    all)         $PYTEST tests test_lotto.py ;;
    unit)        $PYTEST tests/unit ;;
    integration) $PYTEST tests/integration -m integration ;;
    fast)        $PYTEST tests -m "not slow" ;;
    legacy)      $PYTEST test_lotto.py -v --tb=short ;;
    *) echo "Unknown target: $1 (expected: all|unit|integration|fast|legacy)" >&2; exit 1 ;;
esac
