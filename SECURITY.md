# Security Policy

## Supported Versions

Security fixes are applied to the latest code on `main` only. Older commits
and forks are not supported.

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| older   | :x:                |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security reports.**

- Email: **support@lottowheel.app** with the subject line
  `[SECURITY] <short description>`.
- Include: affected endpoint/file, steps to reproduce, impact, and (if
  possible) a suggested fix or proof of concept.
- You will receive an acknowledgement within **72 hours** and a triage
  decision (accepted / declined / needs-more-info) within **7 days**.
- We practice coordinated disclosure: please give us **90 days** to ship a
  fix before publishing details.

## Security Update Policy

- **Critical** (remote auth bypass, secret exposure, injection): hotfix as
  soon as possible, target within 7 days of triage.
- **High/Medium**: fixed in the next regular merge to `main`, target within
  30 days.
- **Low**: batched with routine maintenance.

Dependencies are pinned to exact versions in `requirements.txt` and scanned
in CI on every push/PR via `pip-audit` (see `.github/workflows/ci.yml`,
`security` job). Vulnerable dependency releases are bumped promptly and
noted in the commit message.

## Hardening Notes (current state)

- Passwords are bcrypt-hashed; registration enforces complexity
  (min 8 chars, 1 uppercase, 1 lowercase, 1 digit).
- JWT access tokens expire in 15 minutes; refresh tokens in 7 days and are
  rotated on use. Refresh tokens cannot be used as access tokens.
- `/token` is rate limited to 5 attempts/IP/minute; accounts lock for
  30 minutes after 5 failed logins.
- All API input models run pydantic validators (unique/sorted/ranged number
  pools, past-only dates, sanitized strings). Database access uses
  parameterized queries only.
- Secrets come from environment variables (see `config/secrets.py` and
  `.env.example`). With `DEBUG=false` the app refuses to start with a
  placeholder `JWT_SECRET_KEY` or wildcard CORS origin.
- CORS is an explicit origin list (`CORS_ORIGINS`), never `*` in production.
- Every response carries security headers (nosniff, DENY frame, XSS
  protection, HSTS, CSP); documentation pages use a tailored CSP.
- Authentication attempts and admin actions are appended to
  `data/logs/security.log` (rotated, 10 MB × 5). Passwords and tokens are
  never logged.
