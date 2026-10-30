"""Render the candidate-line report to reports/predictions/YYYY-MM-DD.md.

Prompt pack: reporting. Uses candidate_sets.build_candidate_sets() (which
needs models/nn_tuned.pkl from optuna_tune.py).
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import section  # noqa: E402
from candidate_sets import build_candidate_sets  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = REPO_ROOT / "reports" / "predictions"

MODEL_VERSION = "models/nn_tuned.pkl (Optuna-tuned feed-forward NN)"
DIV1_ODDS = "1 in 53,737,320"
LINE_COST = "$0.80"


def next_draw_date(today: date) -> date:
    d = today
    while d.weekday() not in (2, 5):  # Wed or Sat
        d += timedelta(days=1)
    return d


def render(sets: list[dict], target: str) -> str:
    lines = [f"# NZ Lotto Powerball - candidate lines for {target}", ""]
    lines.append(f"- Model: {MODEL_VERSION}")
    lines.append(f"- Target draw date: {target}")
    lines.append("")
    lines.append("## Candidate sets")
    lines.append("")
    for i, s in enumerate(sets, 1):
        lines.append(f"### {i}. {s['name']}")
        lines.append(f"- Numbers: {', '.join(str(n) for n in s['numbers'])}")
        lines.append(f"- Powerball: {s['pb']}")
        lines.append(f"- Combined confidence: {s['confidence']:.4f}")
        lines.append(f"- Rationale: {s['reasoning']}")
        lines.append("")
    lines.append("## Statistical rationale")
    lines.append("")
    lines.append("Each set is a different heuristic view of the same data (model")
    lines.append("probability, hot numbers, overdue numbers, pair affinity, and a")
    lines.append("blend). Under a fair machine all five are statistically")
    lines.append("indistinguishable from a random ticket; the ordering only reflects")
    lines.append("model confidence, not an edge.")
    lines.append("")
    lines.append("## Disclaimer")
    lines.append("")
    lines.append(f"- Expected value per line is negative (~{LINE_COST} cost vs a fraction")
    lines.append("  of that returned on average); the game cannot be beaten.")
    lines.append(f"- Division 1 odds are {DIV1_ODDS} per line.")
    lines.append("- These are NOT predictions. Each draw is an independent event and")
    lines.append("  the numbers carry no predictive power.")
    lines.append("- For entertainment only. Play responsibly.")
    return "\n".join(lines)


def main() -> int:
    try:
        sets = build_candidate_sets()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        return 1

    today = date.today()
    target = next_draw_date(today).isoformat()
    content = render(sets, target)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{today.isoformat()}.md"
    out.write_text(content, encoding="utf-8")

    section("Prediction report")
    print(f"Wrote: {out}")
    print()
    print(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
