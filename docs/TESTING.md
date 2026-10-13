# Testing

How to run, understand, and extend the test suite.

---

## Running tests

    # Everything
    python -m pytest tests/ -q

    # Skip slow dashboard e2e
    python -m pytest tests/ -q -m "not slow"

    # One file
    python -m pytest tests/unit/test_prize_calculator.py -q

    # With stdout shown
    python -m pytest tests/ -q -s

---

## Test categories

| Directory | Scope | Runtime |
|---|---|---|
| tests/unit/ | Pure functions | ms |
| tests/integration/ | DB, API, auth, monitoring | seconds |
| tests/e2e/ | Streamlit dashboard (marked slow) | slow |

Slow tests are marked @pytest.mark.slow. Exclude with -m "not slow".

---

## Fixtures

Shared fixtures live in tests/conftest.py.

### db_connection

In-memory SQLite with the current draws schema (draw_id, draw_number, draw_date, numbers, bonus, powerball 1-14, rule_era).

### client

FastAPI TestClient running the full app lifespan.

### authenticated_client

TestClient with a registered user and JWT preset in headers. Yields (client, username). Users go to a temp DB.

---

## Conventions

- Every bug fix gets a regression test named after the bug, not the fix.
- Test boundary values just inside and just outside the rule.
- Era-aware tests use named constants (PRE_CHANGE_DATE, POST_CHANGE_DATE), not magic strings.
- No network in unit tests; mock scrapers and APIs.
- Slow tests are marked @pytest.mark.slow.

---

## Type checking

Config is mypy.ini. Run:

    python -m mypy .

Expected: Success, no issues found.

New source files should type-check cleanly. If a module has many pre-existing errors, add a [mypy-module] ignore_errors = True section rather than leaving the whole repo red.

---

## Known warnings

The suite emits warnings safe to ignore:

- DeprecationWarning from Alembic (path_separator)
- UserWarning about SMTP not configured (expected in test env)
- Exception ignored in atexit callback on Windows (pytest temp-dir cleanup, harmless)

To silence the last one, add to pytest.ini:

    [pytest]
    addopts = -p no:cacheprovider