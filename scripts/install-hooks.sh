#!/usr/bin/env bash
# install-hooks.sh — installs the pre-commit hooks for this repository.
#
# Usage:  bash scripts/install-hooks.sh
#
# Uses the project venv when present, otherwise the system Python.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ -x venv/Scripts/python.exe ]; then
    PY=venv/Scripts/python.exe      # Windows venv
elif [ -x venv/bin/python ]; then
    PY=venv/bin/python              # POSIX venv
else
    PY=python
fi

"$PY" -m pip install --quiet pre-commit
"$PY" -m pre_commit install

echo "pre-commit hooks installed. They will run on every 'git commit'."
echo "Run the full quality suite any time with: bash scripts/run-lint.sh"
