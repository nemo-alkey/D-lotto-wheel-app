#!/usr/bin/env python3
"""
international_lotteries.py — Prize calculators and wheel adapters for global
lottery games.

Design
------
- ``BasePrizeCalculator`` defines the interface every game implements:
  division lookup, prize amount, and number validation, plus a wheel
  adapter that maps Bluskov-style 6/40 wheels onto the game's pool.
- Concrete games (PowerballUS, MegaMillions, EuroMillions, NZLotto) carry
  embedded default configs. ``config/lottery_games.json`` can override any
  of them and can define entirely NEW games — the factory then builds a
  generic config-driven calculator, no code changes needed.

Game configs live in ``config/lottery_games.json`` with this shape:
    {
      "GAME_CODE": {
        "name": "...", "currency": "USD",
        "pool_size_main": 69, "pool_size_bonus": 26,
        "numbers_to_pick": 5, "bonus_to_pick": 1,
        "jackpot_estimate": 20000000,
        "divisions": [
          {"division": 1, "main": 5, "bonus": 1, "prize": "jackpot"},
          {"division": 2, "main": 5, "bonus": 0, "prize": 1000000}, ...
        ]
      }
    }

CLI self-test:
    python international_lotteries.py --game POWERBALL_US \
        --numbers "1,2,3,4,5" --bonus 7
    python international_lotteries.py --list-games
"""

from __future__ import annotations

import argparse
import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

CONFIG_PATH = Path(__file__).parent / "config" / "lottery_games.json"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_game_configs(config_path: Path | str | None = None) -> dict[str, Any]:
    """Load game configs from JSON (empty dict if the file is missing)."""
    path = Path(config_path) if config_path else CONFIG_PATH
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return cast(dict[str, Any], json.load(f))


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class BasePrizeCalculator(ABC):
    """Interface + shared logic for a lottery game's prize structure.

    Subclasses set ``game_code`` and ``DEFAULT_CONFIG``; the active config
    is the JSON override when present, else the embedded default.
    """

    game_code: str = ""
    DEFAULT_CONFIG: dict[str, Any] = {}

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = dict(config or self.DEFAULT_CONFIG)
        self.name: str = cfg.get("name", self.game_code)
        self.currency: str = cfg.get("currency", "")
        self.pool_size_main: int = int(cfg["pool_size_main"])
        self.pool_size_bonus: int = int(cfg["pool_size_bonus"])
        self.numbers_to_pick: int = int(cfg["numbers_to_pick"])
        self.bonus_to_pick: int = int(cfg["bonus_to_pick"])
        self.jackpot_estimate: float = float(cfg.get("jackpot_estimate", 0))
        # (main_matches, bonus_matches) -> (division, prize_spec)
        self._rules: dict[tuple[int, int], tuple[int, object]] = {}
        for d in cfg.get("divisions", []):
            self._rules[(int(d["main"]), int(d["bonus"]))] = (
                int(d["division"]),
                d["prize"],
            )

    # ------------------------------------------------------------------
    @abstractmethod
    def calculate_division(self, main_matches: int, bonus_matches: int) -> int | None:
        """Return the division for a match combination, or None if no win."""

    @abstractmethod
    def get_prize_amount(self, division: int | None, jackpot_amount: float = 0) -> float:
        """Return the prize for a division. "jackpot" divisions pay
        ``jackpot_amount`` (or the config's jackpot_estimate if 0)."""

    @abstractmethod
    def validate_numbers(self, numbers: Sequence[int], bonus: Sequence[int]) -> bool:
        """True if the main numbers and bonus pick(s) are legal for the game."""

    # ------------------------------------------------------------------
    # Wheel adapter
    # ------------------------------------------------------------------
    def adapt_wheel(
        self,
        wheel: list[Sequence[int]],
        user_numbers: Sequence[int],
    ) -> list[list[int]]:
        """Map a Bluskov-style wheel onto this game's number range.

        ``wheel`` tickets contain generic indices 1..len(user_numbers);
        index i maps to user_numbers[i-1] (same convention as
        bluskov_wheel_library.substitute_numbers). Tickets are truncated to
        this game's ``numbers_to_pick`` and duplicates are dropped.

        NOTE: truncating a 6-number wheel to 5 numbers (or otherwise
        resizing) VOIDS the original coverage guarantee — this adapter is a
        convenience mapping, not a guarantee-preserving transformation.
        """
        pool = [int(n) for n in user_numbers]
        if len(set(pool)) != len(pool):
            raise ValueError("user_numbers must not contain duplicates.")
        for n in pool:
            if not (1 <= n <= self.pool_size_main):
                raise ValueError(
                    f"Number {n} out of range for {self.game_code} " f"(1-{self.pool_size_main})."
                )

        tickets: list[list[int]] = []
        seen = set()
        for ticket in wheel:
            mapped = tuple(sorted(pool[int(p) - 1] for p in ticket[: self.numbers_to_pick]))
            if len(set(mapped)) != self.numbers_to_pick:
                continue  # truncation produced a duplicate — skip
            if mapped not in seen:
                seen.add(mapped)
                tickets.append(list(mapped))
        return tickets


# ---------------------------------------------------------------------------
# Generic config-driven implementation
# ---------------------------------------------------------------------------


class ConfigDrivenCalculator(BasePrizeCalculator):
    """Prize calculator driven entirely by a config dict/JSON entry."""

    def __init__(self, game_code: str | None = None, config: dict[str, Any] | None = None) -> None:
        if game_code:
            self.game_code = game_code
        super().__init__(config)

    def calculate_division(self, main_matches: int, bonus_matches: int) -> int | None:
        rule = self._rules.get((main_matches, bonus_matches))
        return rule[0] if rule else None

    def get_prize_amount(self, division: int | None, jackpot_amount: float = 0) -> float:
        if division is None:
            return 0.0
        for div, prize in self._rules.values():
            if div == division:
                if prize == "jackpot":
                    return float(jackpot_amount or self.jackpot_estimate)
                return float(cast(Any, prize))
        return 0.0

    def validate_numbers(self, numbers: Sequence[int], bonus: Sequence[int]) -> bool:
        nums = [int(n) for n in numbers]
        if len(nums) != self.numbers_to_pick or len(set(nums)) != len(nums):
            return False
        if any(n < 1 or n > self.pool_size_main for n in nums):
            return False
        bonus_list = [int(b) for b in bonus]
        if len(bonus_list) != self.bonus_to_pick or len(set(bonus_list)) != len(bonus_list):
            return False
        if any(b < 1 or b > self.pool_size_bonus for b in bonus_list):
            return False
        # Games where the bonus comes from the main pool (e.g. NZ Lotto)
        # must not overlap the main numbers
        return not (self.pool_size_bonus == self.pool_size_main and set(bonus_list) & set(nums))


# ---------------------------------------------------------------------------
# Concrete games (embedded defaults; JSON can override)
# ---------------------------------------------------------------------------


class PowerballUS(ConfigDrivenCalculator):
    """US Powerball: 5/69 + 1/26."""

    game_code = "POWERBALL_US"
    DEFAULT_CONFIG = {
        "name": "Powerball (US) 5/69 + 1/26",
        "currency": "USD",
        "pool_size_main": 69,
        "pool_size_bonus": 26,
        "numbers_to_pick": 5,
        "bonus_to_pick": 1,
        "jackpot_estimate": 20_000_000,
        "divisions": [
            {"division": 1, "main": 5, "bonus": 1, "prize": "jackpot"},
            {"division": 2, "main": 5, "bonus": 0, "prize": 1_000_000},
            {"division": 3, "main": 4, "bonus": 1, "prize": 50_000},
            {"division": 4, "main": 4, "bonus": 0, "prize": 100},
            {"division": 5, "main": 3, "bonus": 1, "prize": 100},
            {"division": 6, "main": 3, "bonus": 0, "prize": 7},
            {"division": 7, "main": 2, "bonus": 1, "prize": 7},
            {"division": 8, "main": 1, "bonus": 1, "prize": 4},
            {"division": 9, "main": 0, "bonus": 1, "prize": 4},
        ],
    }


class MegaMillions(ConfigDrivenCalculator):
    """US Mega Millions: 5/70 + 1/25."""

    game_code = "MEGA_MILLIONS"
    DEFAULT_CONFIG = {
        "name": "Mega Millions (US) 5/70 + 1/25",
        "currency": "USD",
        "pool_size_main": 70,
        "pool_size_bonus": 25,
        "numbers_to_pick": 5,
        "bonus_to_pick": 1,
        "jackpot_estimate": 20_000_000,
        "divisions": [
            {"division": 1, "main": 5, "bonus": 1, "prize": "jackpot"},
            {"division": 2, "main": 5, "bonus": 0, "prize": 1_000_000},
            {"division": 3, "main": 4, "bonus": 1, "prize": 10_000},
            {"division": 4, "main": 4, "bonus": 0, "prize": 500},
            {"division": 5, "main": 3, "bonus": 1, "prize": 200},
            {"division": 6, "main": 3, "bonus": 0, "prize": 10},
            {"division": 7, "main": 2, "bonus": 1, "prize": 10},
            {"division": 8, "main": 1, "bonus": 1, "prize": 4},
            {"division": 9, "main": 0, "bonus": 1, "prize": 2},
        ],
    }


class EuroMillions(ConfigDrivenCalculator):
    """EuroMillions: 5/50 + 2/12 (12 divisions)."""

    game_code = "EUROMILLIONS"
    DEFAULT_CONFIG = {
        "name": "EuroMillions 5/50 + 2/12",
        "currency": "EUR",
        "pool_size_main": 50,
        "pool_size_bonus": 12,
        "numbers_to_pick": 5,
        "bonus_to_pick": 2,
        "jackpot_estimate": 17_000_000,
        "divisions": [
            {"division": 1, "main": 5, "bonus": 2, "prize": "jackpot"},
            {"division": 2, "main": 5, "bonus": 1, "prize": 130_000},
            {"division": 3, "main": 5, "bonus": 0, "prize": 13_000},
            {"division": 4, "main": 4, "bonus": 2, "prize": 844},
            {"division": 5, "main": 4, "bonus": 1, "prize": 77},
            {"division": 6, "main": 3, "bonus": 2, "prize": 37},
            {"division": 7, "main": 4, "bonus": 0, "prize": 25},
            {"division": 8, "main": 2, "bonus": 2, "prize": 14},
            {"division": 9, "main": 3, "bonus": 1, "prize": 11},
            {"division": 10, "main": 3, "bonus": 0, "prize": 9},
            {"division": 11, "main": 1, "bonus": 2, "prize": 7},
            {"division": 12, "main": 2, "bonus": 1, "prize": 5},
        ],
    }


class NZLotto(ConfigDrivenCalculator):
    """NZ Lotto: 6/40 + bonus ball (NZ Powerball add-on is out of scope)."""

    game_code = "NZ_LOTTO"
    DEFAULT_CONFIG = {
        "name": "NZ Lotto (6/40 + bonus)",
        "currency": "NZD",
        "pool_size_main": 40,
        "pool_size_bonus": 40,
        "numbers_to_pick": 6,
        "bonus_to_pick": 1,
        "jackpot_estimate": 1_000_000,
        "divisions": [
            {"division": 1, "main": 6, "bonus": 0, "prize": 1_000_000},
            {"division": 2, "main": 5, "bonus": 1, "prize": 30_000},
            {"division": 3, "main": 5, "bonus": 0, "prize": 1_000},
            {"division": 4, "main": 4, "bonus": 1, "prize": 100},
            {"division": 5, "main": 4, "bonus": 0, "prize": 60},
            {"division": 6, "main": 3, "bonus": 1, "prize": 40},
            {"division": 7, "main": 3, "bonus": 0, "prize": 20},
        ],
    }


_GAME_CLASSES = {c.game_code: c for c in (NZLotto, PowerballUS, MegaMillions, EuroMillions)}


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_calculator(game_code: str, config_path: Path | str | None = None) -> BasePrizeCalculator:
    """Return the prize calculator for a game code.

    Known codes: NZ_LOTTO, POWERBALL_US, MEGA_MILLIONS, EUROMILLIONS.
    Any other code is looked up in config/lottery_games.json and built as a
    generic config-driven calculator — so users can add games without
    touching code.

    Raises:
        ValueError: if the game code is unknown and not in the JSON config.
    """
    code = game_code.strip().upper()
    overrides = load_game_configs(config_path)

    cls = _GAME_CLASSES.get(code)
    if cls is not None:
        # JSON override wins over the embedded default
        return cls(config=overrides.get(code))

    if code in overrides:
        return ConfigDrivenCalculator(code, overrides[code])

    available = sorted(set(_GAME_CLASSES) | set(overrides))
    raise ValueError(
        f"Unknown game code {game_code!r}. Available: {', '.join(available)} "
        f"(or add it to {CONFIG_PATH.name})."
    )


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------


def _parse_ints(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="International lottery prize calculator self-test."
    )
    parser.add_argument("--game", help="Game code, e.g. POWERBALL_US")
    parser.add_argument("--numbers", help="Your main numbers, comma-separated")
    parser.add_argument("--bonus", default="", help="Your bonus number(s), comma-separated")
    parser.add_argument(
        "--draw-numbers",
        default="",
        help="Winning draw main numbers (default: same as --numbers)",
    )
    parser.add_argument(
        "--draw-bonus",
        default="",
        help="Winning draw bonus number(s) (default: same as --bonus)",
    )
    parser.add_argument(
        "--jackpot",
        type=float,
        default=0,
        help="Jackpot amount for jackpot divisions (0 = config estimate)",
    )
    parser.add_argument("--list-games", action="store_true", help="List available game codes")
    args = parser.parse_args()

    if args.list_games:
        overrides = load_game_configs()
        for code in sorted(set(_GAME_CLASSES) | set(overrides)):
            calc = get_calculator(code)
            print(f"  {code}: {calc.name}")
        return

    if not args.game or not args.numbers:
        parser.error("--game and --numbers are required (or use --list-games)")

    calc = get_calculator(args.game)

    numbers = _parse_ints(args.numbers)
    if len(numbers) > calc.numbers_to_pick:
        print(
            f"Note: {calc.game_code} plays {calc.numbers_to_pick} main numbers; "
            f"using the first {calc.numbers_to_pick} of {len(numbers)} given."
        )
        numbers = numbers[: calc.numbers_to_pick]
    bonus = _parse_ints(args.bonus) if args.bonus else []

    draw_numbers = _parse_ints(args.draw_numbers)[: calc.numbers_to_pick] or numbers
    draw_bonus = _parse_ints(args.draw_bonus) if args.draw_bonus else bonus

    if not calc.validate_numbers(numbers, bonus):
        print(
            f"INVALID ticket for {calc.game_code}: "
            f"need {calc.numbers_to_pick} unique mains 1-{calc.pool_size_main} "
            f"and {calc.bonus_to_pick} bonus 1-{calc.pool_size_bonus}."
        )
        raise SystemExit(1)

    main_matches = len(set(numbers) & set(draw_numbers))
    bonus_matches = len(set(bonus) & set(draw_bonus))

    division = calc.calculate_division(main_matches, bonus_matches)
    prize = calc.get_prize_amount(division, jackpot_amount=args.jackpot)

    print(f"\nGame:    {calc.name}")
    print(f"Ticket:  {sorted(numbers)} + bonus {bonus}")
    print(f"Draw:    {sorted(draw_numbers)} + bonus {draw_bonus}")
    print(f"Matches: {main_matches} main + {bonus_matches} bonus")
    if division is None:
        print("Result:  no winning division")
    else:
        print(f"Result:  Division {division} — estimated prize " f"{calc.currency} {prize:,.2f}")


if __name__ == "__main__":
    main()
