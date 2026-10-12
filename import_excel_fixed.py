#!/usr/bin/env python3
"""Import NZ Lotto historical data from official Excel file."""

import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import openpyxl

DB_PATH = Path.cwd() / "data" / "lotto.db"
EXCEL_PATH = Path.cwd() / "winning_numbers.xlsx"


def parse_draw_number(val) -> int:
    """Extract integer from 'Draw 1' or '1'."""
    if val is None:
        return 0
    match = re.search(r'\d+', str(val))
    return int(match.group()) if match else 0


def parse_date(val) -> str:
    """Parse dates like 'Saturday 1 August 1987' → '1987-08-01'."""
    if val is None:
        return ""
    text = str(val).strip()
    
    formats = [
        "%A %d %B %Y",      # Saturday 1 August 1987
        "%a %d %B %Y",      # Sat 1 August 1987
        "%d %B %Y",         # 1 August 1987
        "%d %b %Y",         # 1 Aug 1987
        "%Y-%m-%d",         # 1987-08-01
        "%d/%m/%Y",         # 01/08/1987
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    
    return ""


def import_excel() -> None:
    if not EXCEL_PATH.exists():
        print(f"Excel file not found: {EXCEL_PATH}")
        return
    
    print(f"Reading: {EXCEL_PATH}")
    wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
    sheet = wb[wb.sheetnames[0]]
    print(f"Sheet: {wb.sheetnames[0]}")
    
    # Find header row
    headers = None
    data_start = 0
    for i, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if row and any(str(cell).lower() in ["draw", "date", "bonus", "power"] 
                       for cell in row if cell):
            headers = [str(c).lower().strip() if c else "" for c in row]
            data_start = i
            print(f"Headers at row {i}: {headers}")
            break
    
    if not headers:
        print("Could not find headers")
        return
    
    # Map columns
    col_draw = next((i for i, h in enumerate(headers) if "draw" in h and h != ""), 0)
    col_date = next((i for i, h in enumerate(headers) if "date" in h), 1)
    col_nums = [i for i, h in enumerate(headers) if h in ["1", "2", "3", "4", "5", "6"]]
    col_bonus = next((i for i, h in enumerate(headers) if "bonus" in h and "2nd" not in h), 8)
    col_power = next((i for i, h in enumerate(headers) if "power" in h), 10)
    
    print(f"Columns: draw={col_draw}, date={col_date}, nums={col_nums}, bonus={col_bonus}, power={col_power}")
    
    # Get existing dates
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    existing_dates = {r[0] for r in conn.execute("SELECT draw_date FROM draws")}
    conn.close()
    
    inserted = skipped = failed = 0
    
    for i, row in enumerate(sheet.iter_rows(values_only=True), 1):
        if i <= data_start:
            continue
        
        # Stop at empty rows or summary rows
        if not row or not row[0]:
            continue
        if str(row[0]).lower().startswith("total"):
            continue
        
        try:
            draw_num = parse_draw_number(row[col_draw])
            date_str = parse_date(row[col_date])
            
            if not date_str:
                failed += 1
                if failed <= 3:
                    print(f"  ! Row {i}: could not parse date: {row[col_date]}")
                continue
            
            if date_str in existing_dates:
                skipped += 1
                continue
            
            # Extract 6 main numbers
            numbers = []
            for idx in col_nums:
                if idx < len(row) and row[idx] is not None:
                    try:
                        n = int(row[idx])
                        if 1 <= n <= 40:
                            numbers.append(n)
                    except (ValueError, TypeError):
                        pass
            
            if len(numbers) != 6:
                failed += 1
                if failed <= 5:
                    print(f"  ! Row {i}: expected 6 numbers, got {len(numbers)}")
                continue
            
            # Bonus ball
            bonus = 0
            if col_bonus < len(row) and row[col_bonus] is not None:
                try:
                    bonus = int(row[col_bonus])
                except (ValueError, TypeError):
                    pass
            
            # Powerball
            powerball = 0
            if col_power < len(row) and row[col_power] is not None:
                try:
                    powerball = int(row[col_power])
                except (ValueError, TypeError):
                    pass
            
            # Insert
            conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
            try:
                conn.execute(
                    "INSERT INTO draws (draw_number, draw_date, numbers, bonus, powerball) VALUES (?, ?, ?, ?, ?)",
                    (draw_num, date_str, ",".join(map(str, sorted(numbers))), bonus, powerball),
                )
                conn.commit()
                inserted += 1
                if inserted % 100 == 0:
                    print(f"  ... {inserted} inserted")
            except sqlite3.IntegrityError:
                skipped += 1
            finally:
                conn.close()
                
        except Exception as e:
            failed += 1
            if failed <= 3:
                print(f"  ! Row {i} error: {e}")
            continue
    
    print(f"\nDone. Inserted: {inserted} | Skipped: {skipped} | Failed: {failed}")
    
    conn = sqlite3.connect(str(DB_PATH.resolve()), timeout=10)
    count = conn.execute("SELECT COUNT(*) FROM draws").fetchone()[0]
    min_date, max_date = conn.execute("SELECT MIN(draw_date), MAX(draw_date) FROM draws").fetchone()
    conn.close()
    print(f"Total draws in DB: {count}")
    if min_date and max_date:
        print(f"Date range: {min_date} to {max_date}")


if __name__ == "__main__":
    import_excel()