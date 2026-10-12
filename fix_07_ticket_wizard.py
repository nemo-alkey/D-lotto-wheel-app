"""ticket_wizard.py — line ~151 PB selectbox."""
from __future__ import annotations
import ast, sys
from pathlib import Path

TARGET = Path("ticket_wizard.py")
src = TARGET.read_text(encoding="utf-8")

OLD = 'pb = st.selectbox("Powerball", list(range(1, 11)), key="wiz_pb_manual")'
NEW = """from powerball_rules import powerball_max_for_date as _pb_max
    pb = st.selectbox("Powerball", list(range(1, _pb_max(None) + 1)), key="wiz_pb_manual")"""

if OLD in src:
    src = src.replace(OLD, NEW, 1)
    print("OK  : ticket_wizard.py selectbox")
elif "range(1, _pb_max(None) + 1)" in src:
    print("SKIP: ticket_wizard.py already era-aware")
else:
    print("MISS: ticket_wizard.py selectbox not found")

TARGET.write_text(src, encoding="utf-8")
try:
    ast.parse(src); print("\nSyntax check: OK")
except SyntaxError as e:
    print(f"\nSyntax FAILED at line {e.lineno}: {e.msg}"); sys.exit(1)