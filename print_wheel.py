#!/usr/bin/env python3
"""
print_wheel.py — Generate an A4 PDF playslip for a given wheel.

Usage:
    python3 print_wheel.py double             → wheel_playslip.pdf
    python3 print_wheel.py double out.pdf     → out.pdf

Requires: pip install reportlab
"""

import os
import sys

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# Add parent dir so we can import lotto_wheels
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lotto_wheels import WHEELS


def build_pdf(wheel_name: str, output_path: str) -> None:
    """Generate an A4 PDF playslip for *wheel_name* and save to *output_path*."""
    if wheel_name not in WHEELS:
        print(f"Unknown wheel: '{wheel_name}'")
        print(f"Available wheels: {', '.join(WHEELS)}")
        sys.exit(1)

    tickets, pb = WHEELS[wheel_name]

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=15 * mm,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    normal_style = styles["Normal"]
    # Reduce default font sizes a little for table readability
    table_style = styles["Normal"]
    table_style.fontSize = 9

    elements = []

    # ---- Title ----
    elements.append(
        Paragraph(
            f"NZ Lotto Powerball – {wheel_name} Wheel",
            title_style,
        )
    )
    elements.append(Spacer(1, 6 * mm))

    # ---- Table ----
    header = ["Ticket #", "Main Numbers"]
    data_rows = []
    for i, ticket in enumerate(tickets, 1):
        nums_str = " ".join(str(n) for n in sorted(ticket))
        data_rows.append([str(i), nums_str])

    table_data = [header] + data_rows
    col_widths = [28 * mm, 140 * mm]

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (1, 0), (1, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f3f4")]),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    elements.append(table)

    # ---- Suggested Powerball + Cost ----
    elements.append(Spacer(1, 6 * mm))
    cost = len(tickets) * 1.50
    elements.append(
        Paragraph(
            f"Suggested Powerball: <b>{pb}</b>",
            normal_style,
        )
    )
    elements.append(Spacer(1, 2 * mm))
    elements.append(
        Paragraph(
            f"Total cost: <b>${cost:.2f}</b>  ({len(tickets)} lines × $1.50)",
            normal_style,
        )
    )

    doc.build(elements)
    print(f"PDF saved to {output_path}")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python print_wheel.py <wheel_name> [output.pdf]")
        print(f"  wheel_name: {', '.join(WHEELS)}")
        print("  output.pdf defaults to wheel_playslip.pdf")
        sys.exit(1)

    wheel_name = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) >= 3 else "wheel_playslip.pdf"
    build_pdf(wheel_name, output_path)


if __name__ == "__main__":
    main()
