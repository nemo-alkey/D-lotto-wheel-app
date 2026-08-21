#!/usr/bin/env python3
"""Cleanup script — detect and remove blank/placeholder .md and .csv files.

Usage:
    python cleanup.py --dry-run     # Generate report only
    python cleanup.py --delete      # Delete confirmed files
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    "venv",
    "env",
    ".pytest_cache",
    "Lib",
    "Scripts",
    "Include",
    "share",
}
EXCLUDE_STARTS = {
    "data/raw",
    "data/processed",
    "data/races",
    "logs",
    "results",
    "models",
}

PROTECTED = {
    "README.md",
    "readme.md",
    "CONCEPTS.md",
    "ML_BETTING_GUIDE.md",
    "TEST_REYNOLDS_RANKINGS_GUIDE.md",
    "FORMULAS.md",
    "ARCHITECTURE.md",
    "CONCEPTS_26_35_SPECIFICATIONS.md",
    "CONCEPTS_IMPLEMENTATION_SUMMARY.md",
    "PROJECT_STATUS.md",
    "CONTRIBUTING.md",
    "DEPLOYMENT.md",
    "MAINTENANCE_RUNBOOK.md",
    "KELLY_CRITERION_ENHANCEMENTS.md",
    "SPORTS_EDGE_ARCHITECTURE.md",
    "PRE-INSTALLATION-CHECKLIST.md",
    "CHANGELOG.md",
    "KNOWN_ISSUES.md",
    "ROADMAP.md",
    "RELEASE_CHECKLIST.md",
    "LICENSE",
    "DRAW_BIAS.md",
    "API_README.md",
    "CODESPACES_QUICKSTART.md",
    "QUICK-START-SETUP.md",
    "QUICKSTART_STREAMING.md",
    "QUICK_START_ML_BETTING.md",
    "SETUP-V2-FEATURES.md",
    "TROUBLESHOOTING.md",
    "features/SCHEMA.md",
    "k8s/README.md",
    "docs/ROADMAP.md",
}

PLACEHOLDER_PATTERNS = [
    re.compile(r"^(TODO|TBD|placeholder|coming\s*soon|\[insert\s+content\])\s*$", re.I),
    re.compile(r"^#\s*\w+\.(md|csv)\s*$", re.I),
]


def is_blank(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            return True
        return content in ("", "\ufeff")
    except Exception:
        return path.stat().st_size == 0


def is_placeholder(path: Path) -> bool:
    try:
        content = path.read_text(encoding="utf-8-sig").strip()
        if not content:
            return False  # caught by is_blank
        for pattern in PLACEHOLDER_PATTERNS:
            if pattern.match(content):
                return True
        # Check if only contains filename-as-title
        basename = path.name.lower()
        return content.lower() == f"# {basename}" or content.lower() == basename
    except Exception:
        return False


def scan_project(root: Path) -> list[tuple[Path, str, str]]:
    """Return list of (path, reason, action)."""
    findings: list[tuple[Path, str, str]] = []

    for file in root.rglob("*"):
        if file.suffix.lower() not in (".md", ".csv"):
            continue

        # Exclude dirs
        parts = set(file.parts)
        if parts & EXCLUDE_DIRS:
            continue

        # Exclude data dir paths
        rel = str(file.relative_to(root)).replace("\\", "/")
        if any(rel.startswith(e) for e in EXCLUDE_STARTS):
            continue

        # Protected
        if file.name in PROTECTED or file.name.lower() in {n.lower() for n in PROTECTED}:
            continue

        # Special: data/*.csv with actual data
        if file.suffix == ".csv" and file.stat().st_size > 100:
            continue

        if is_blank(file):
            action = (
                "DELETE"
                if file.stat().st_size == 0 or file.read_text(encoding="utf-8-sig").strip() == ""
                else "FLAG"
            )
            findings.append((file, "blank (empty file)", action))
        elif is_placeholder(file):
            findings.append((file, "placeholder content", "DELETE"))

    return sorted(findings, key=lambda x: str(x[0]))


def find_references(root: Path, deleted_paths: list[Path]) -> list[str]:
    """Find references to deleted files in remaining .md, .py, .yaml files."""
    issues: list[str] = []
    deleted_names = {p.name for p in deleted_paths}

    for file in root.rglob("*"):
        if file.suffix not in (".md", ".py", ".yaml", ".yml", ".json"):
            continue
        parts = set(file.parts)
        if parts & EXCLUDE_DIRS:
            continue
        try:
            content = file.read_text(encoding="utf-8-sig")
        except Exception:
            continue

        for name in deleted_names:
            if name in content:
                # Check if it's a markdown link or import
                issues.append(f"  {file.relative_to(root)} references '{name}'")
                break  # one issue per file

    return issues


def generate_report(findings: list[tuple[Path, str, str]]) -> str:
    lines = [
        "=" * 60,
        f"CLEANUP REPORT — {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
        "=" * 60,
        f"Total files found: {len(findings)}",
        "",
    ]

    deletes = [f for f in findings if f[2] == "DELETE"]
    flags = [f for f in findings if f[2] == "FLAG"]

    if deletes:
        lines.append(f"Files to DELETE ({len(deletes)}):")
        for path, reason, _ in deletes:
            lines.append(f"  {path.relative_to(ROOT)}  [{reason}]")

    if flags:
        lines.append(f"\nFiles to FLAG for review ({len(flags)}):")
        for path, reason, _ in flags:
            lines.append(f"  {path.relative_to(ROOT)}  [{reason}]")

    if not findings:
        lines.append("No blank or placeholder files found.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Cleanup blank/placeholder files")
    parser.add_argument("--dry-run", action="store_true", help="Report only, no deletion")
    parser.add_argument("--delete", action="store_true", help="Delete eligible files")
    args = parser.parse_args()

    if not args.dry_run and not args.delete:
        print("Specify --dry-run or --delete")
        sys.exit(1)

    findings = scan_project(ROOT)

    if args.dry_run:
        report = generate_report(findings)
        Path("cleanup_report.txt").write_text(report, encoding="utf-8")
        print(report)
        print("\nReport saved to cleanup_report.txt")
        return

    if args.delete:
        deletes = [f for f in findings if f[2] == "DELETE"]
        if not deletes:
            print("No files eligible for deletion.")
            return

        deleted_paths: list[Path] = []
        log_lines = [
            f"CLEANUP LOG — {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
            f"Deleted {len(deletes)} files:",
        ]
        for path, reason, _ in deletes:
            try:
                path.unlink()
                log_lines.append(f"  DELETED {path.relative_to(ROOT)} [{reason}]")
                deleted_paths.append(path)
                print(f"  Deleted: {path.relative_to(ROOT)}")
            except Exception as e:
                log_lines.append(f"  FAILED {path.relative_to(ROOT)} — {e}")

        # Find broken references
        refs = find_references(ROOT, deleted_paths)
        if refs:
            log_lines.append(f"\nBroken references found ({len(refs)}):")
            log_lines.extend(refs)

        Path("cleanup_log.txt").write_text("\n".join(log_lines), encoding="utf-8")
        print("\nLog saved to cleanup_log.txt")


if __name__ == "__main__":
    main()
