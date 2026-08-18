## Description

<!-- What does this PR change and why? Link any related issue (#123). -->

## Type of change

- [ ] Bugfix
- [ ] Feature
- [ ] Refactor
- [ ] Docs / chore

## Tests added?

- [ ] Yes — new/updated tests in `tests/`
- [ ] No — explain why not below

<!-- If yes, list the test files. If no, justify (e.g. config-only change). -->

## Screenshots (if UI)

<!-- Drag & drop screenshots or a short screen recording for dashboard/mobile-frontend changes. -->

## Checklist

- [ ] `ruff check . --ignore=F401,E402` passes
- [ ] `pytest tests test_lotto.py` passes locally
- [ ] Docs updated (README / module docstrings / AGENTS.md) where behavior changed
- [ ] Database schema changes include an Alembic migration (`python migrate.py revision -m "..."`)
- [ ] No secrets, API keys, or local paths committed
