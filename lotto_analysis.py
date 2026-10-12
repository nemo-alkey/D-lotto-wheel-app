#!/usr/bin/env python3
"""Comprehensive Lotto number analysis."""

import sqlite3

conn = sqlite3.connect('data/lotto.db')

numbers = {}
for row in conn.execute('SELECT numbers FROM draws'):
    for n in row[0].split(','):
        numbers[n] = numbers.get(n, 0) + 1

bonus_balls = {}
for row in conn.execute('SELECT bonus FROM draws'):
    if row[0] is not None:
        bonus_balls[str(row[0])] = bonus_balls.get(str(row[0]), 0) + 1

powerballs = {}
for row in conn.execute('SELECT powerball FROM draws WHERE powerball > 0'):
    powerballs[str(row[0])] = powerballs.get(str(row[0]), 0) + 1

print("=" * 60)
print("NZ LOTTO 39-YEAR ANALYSIS (2,413 draws)")
print("=" * 60)

print("\nHOT NUMBERS (Most Frequent):")
for n, count in sorted(numbers.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  {n}: {count} times ({count/2413*100:.1f}%)")

print("\nCOLD NUMBERS (Least Frequent):")
for n, count in sorted(numbers.items(), key=lambda x: x[1])[:10]:
    print(f"  {n}: {count} times ({count/1000*100:.1f}%)")

print("\nBONUS BALL FREQUENCY:")
for n, count in sorted(bonus_balls.items(), key=lambda x: x[1], reverse=True)[:10]:
    print(f"  {n}: {count} times")

if powerballs:
    print("\nPOWERBALL FREQUENCY:")
    for n, count in sorted(powerballs.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {n}: {count} times")

expected = 2413 * 6 / 40
print(f"\nSTATISTICS:")
print(f"  Expected frequency per number: {expected:.1f}")
print(f"  Hottest (#1): {numbers['1']} (expected {expected:.1f})")
print(f"  Difference: +{numbers['1'] - expected:.0f} above expected")

conn.close()