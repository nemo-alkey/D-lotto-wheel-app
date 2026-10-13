# 2026-10-14: find the new Lotto NZ API endpoint

## Blocker
- api.mylotto.co.nz: NXDOMAIN
- api.lottonz.co.nz: NXDOMAIN
- www.mylotto.co.nz: 210.55.2.7 (serves SPA HTML)
- www.lottonz.co.nz: 210.55.2.24 (serves SPA HTML)

## Method
1. Open https://www.mylotto.co.nz in Chrome/Edge
2. F12 -> Network tab -> filter 'Fetch/XHR'
3. Navigate to a results page
4. Find JSON request -> copy URL
5. That URL is the new API endpoint

## Files to update
    Select-String -Path *.py -Pattern "mylotto" -SimpleMatch

## Recovery commands (once host is known)
python backfill_by_drawnum.py --start 2400 --end 2400   # single test
python backfill_by_drawnum.py --start 2309 --end 2511   # full gap
python write_full_audit.py                              # verify counts
python scripts\analysis\chi_square.py                   # verify uniformity
