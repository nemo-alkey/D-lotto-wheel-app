# resume_tomorrow.ps1 — restore working state after shutdown.
$ErrorActionPreference = "Continue"
Set-Location "D:\lotto-wheel-app"

Write-Host "=== Resuming NZ Lotto Powerball work ===" -ForegroundColor Cyan
Write-Host ""

# 1. Activate venv
.\venv\Scripts\Activate.ps1
Write-Host "Venv: $(python -c 'import sys; print(sys.executable)')" -ForegroundColor Green
Write-Host ""

# 2. Confirm pytest is available
python -m pytest --version
Write-Host ""

# 3. Suite status
Write-Host "=== Test suite baseline ===" -ForegroundColor Cyan
python -m pytest tests/ -q --continue-on-collection-errors
Write-Host ""

# 4. Git state
Write-Host "=== Git state ===" -ForegroundColor Cyan
git status --short
git log --oneline -5
Write-Host ""

# 5. Sanity check on era-aware wiring
Write-Host "=== Powerball era check ===" -ForegroundColor Cyan
python -c @"
from powerball_rules import POWERBALL_MAX_OLD, POWERBALL_MAX_NEW, POWERBALL_CHANGE_DATE
print(f'Change date:        {POWERBALL_CHANGE_DATE}')
print(f'Pre-change max PB:  {POWERBALL_MAX_OLD}')
print(f'Post-change max PB: {POWERBALL_MAX_NEW}')
"@
Write-Host ""

Write-Host "=== Ready. Remaining work: ===" -ForegroundColor Cyan
Write-Host "  1. (optional) Clean up 1-10 in doc comments (settings.py, backtest.py, steps/*)"
Write-Host "  2. (optional) Per-draw era validation at API layer"
Write-Host "  3. (gated) ML retraining — needs ~30 post-change draws (~4 months)"
Write-Host ""

Read-Host "Press Enter to close"