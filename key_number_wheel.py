#!/usr/bin/env python3
"""Key-number wheel generator.

Generates all 6‑number tickets that include one or more fixed numbers,
with a fixed Powerball. Useful for playing a "banker" system.

Usage:
    python key_number_wheel.py --pool "1,2,16,22,27,33,34,39" --key 1 --powerball 1
    python key_number_wheel.py --pool "1,12,13,15,19,22,23,24" --key 1,12 --powerball 2
"""

import argparse
import sys
from itertools import combinations
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate key-number lottery wheels")
    parser.add_argument(
        "--pool",
        type=str,
        required=True,
        help="Comma-separated list of numbers to wheel from (e.g., 1,2,3,4,5,6,7,8)",
    )
    parser.add_argument(
        "--key",
        type=str,
        required=True,
        help="Comma-separated list of numbers that must appear in every ticket",
    )
    parser.add_argument(
        "--powerball", type=int, default=1, help="Powerball number to use (1-10, default 1)"
    )
    parser.add_argument(
        "--ticket-size", type=int, default=6, help="Number of main numbers per ticket (default 6)"
    )
    args = parser.parse_args()

    # Parse pool and key numbers
    pool = sorted({int(x) for x in args.pool.split(",") if x.strip()})
    keys = sorted({int(x) for x in args.key.split(",") if x.strip()})

    # Validate
    if len(pool) < args.ticket_size:
        print(f"Pool must have at least {args.ticket_size} numbers.")
        return 1
    for k in keys:
        if k not in pool:
            print(f"Key number {k} is not in the pool!")
            return 1
    if len(keys) > args.ticket_size:
        print("Too many key numbers for the ticket size.")
        return 1
    if not (1 <= args.powerball <= 10):
        print("Powerball must be between 1 and 10.")
        return 1

    # Remaining numbers (pool minus keys) that can fill the rest of each ticket
    others = [n for n in pool if n not in keys]
    slots_left = args.ticket_size - len(keys)

    print("=" * 60)
    print("KEY-NUMBER WHEEL GENERATOR")
    print(f"Pool: {pool}")
    print(f"Key numbers (always included): {keys}")
    print(f"Powerball: {args.powerball}")
    print("=" * 60)

    tickets = []
    if slots_left == 0:
        # Only one possible ticket (all keys)
        tickets.append(tuple(keys))
    else:
        # Generate all combinations of the remaining numbers to fill the ticket
        for combo in combinations(others, slots_left):
            ticket = tuple(sorted(keys + list(combo)))
            tickets.append(ticket)

    print(f"\nNumber of tickets: {len(tickets)}")
    print(f"Cost: ${len(tickets) * 0.70:.2f} (at $0.70 per ticket)")

    print("\nTickets:")
    for i, ticket in enumerate(tickets, 1):
        print(f"  Ticket {i:2d}: {' '.join(f'{n:2d}' for n in ticket)}  PB:{args.powerball}")

    # Save to file
    output_file = Path.cwd() / f"key_wheel_pb{args.powerball}.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(f"Key-number wheel (Powerball {args.powerball})\n")
        f.write(f"Pool: {pool}\n")
        f.write(f"Keys: {keys}\n")
        f.write(f"Tickets ({len(tickets)}):\n")
        for ticket in tickets:
            f.write(f"  {' '.join(f'{n:2d}' for n in ticket)}  PB:{args.powerball}\n")
    print(f"\nSaved to: {output_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
