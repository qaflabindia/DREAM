"""Registered procedural task families for counterfactual evaluation.

Each family has an instance generator, a set of allowlisted candidate actions
(pure functions, never recorded code), the action a naive agent uses by
default, and the environment's ground-truth convention. Actions return a
string; a failed action returns "ERROR". Ground truth is computed by the
environment's convention, not by any model output.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_DOWN
from typing import Callable


@dataclass(frozen=True)
class Family:
    name: str
    generate: Callable[[random.Random], tuple]
    actions: dict[str, Callable[[tuple], str]]
    default: str
    truth: str  # the action that implements the environment's convention

    def run(self, action: str, x: tuple) -> str:
        try:
            return self.actions[action](x)
        except Exception:
            return "ERROR"

    def reference(self, x: tuple) -> str:
        return self.run(self.truth, x)

    def correct(self, action: str, x: tuple, reference: str | None = None) -> bool:
        return same(self.run(action, x), self.reference(x) if reference is None else reference)


def same(a: str, b: str) -> bool:
    """Numeric answers compare by exact decimal value; others as strings."""
    if a == "ERROR" or b == "ERROR":
        return False
    try:
        return Decimal(a) == Decimal(b)
    except Exception:
        return a == b


def _money(rng):
    return tuple(f"{rng.randrange(1, 100000) / 100:.2f}" for _ in range(rng.randrange(2, 6)))


def _three_dp(rng):
    whole, d2 = rng.randrange(0, 1000), rng.randrange(0, 100)
    d3 = 5 if rng.random() < 0.4 else rng.randrange(0, 10)
    return (f"{whole}.{d2:02d}{d3}",)


def _date(rng):
    d = date(2020, 1, 1).fromordinal(date(2020, 1, 1).toordinal() + rng.randrange(0, 2000))
    return (f"{d.day:02d}/{d.month:02d}/{d.year}",)


def _pct(rng):
    return (rng.randrange(50, 5000), rng.randrange(50, 5000))


def _ids(rng):
    base = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    typed = base.lower() if rng.random() < 0.4 else base
    typed = typed + " " if rng.random() < 0.2 else typed
    if rng.random() < 0.3:  # genuinely different id
        typed = typed[:-2] + ("Q" if typed[-2] != "Q" else "R") + typed[-1]
    return (typed, base)


def _gross(rng):
    return (f"{rng.randrange(100, 100000) / 100:.2f}",)


def _q2(v: Decimal, mode) -> str:
    return str(v.quantize(Decimal("0.01"), rounding=mode))


FAMILIES: dict[str, Family] = {f.name: f for f in [
    Family("money_sum", _money, {
        "float_sum": lambda x: repr(sum(float(v) for v in x)),
        "decimal_sum": lambda x: str(sum((Decimal(v) for v in x), Decimal(0))),
        "int_cents": lambda x: f"{sum(round(float(v) * 100) for v in x) / 100:.2f}",
    }, default="float_sum", truth="decimal_sum"),
    Family("round_2dp", _three_dp, {
        "half_up": lambda x: _q2(Decimal(x[0]), ROUND_HALF_UP),
        "half_even": lambda x: _q2(Decimal(x[0]), ROUND_HALF_EVEN),
        "truncate": lambda x: _q2(Decimal(x[0]), ROUND_DOWN),
    }, default="half_up", truth="half_even"),
    Family("date_parse", _date, {
        "month_first": lambda x: date(int(x[0][6:]), int(x[0][:2]), int(x[0][3:5])).isoformat(),
        "day_first": lambda x: date(int(x[0][6:]), int(x[0][3:5]), int(x[0][:2])).isoformat(),
    }, default="month_first", truth="day_first"),
    Family("pct_change", _pct, {
        "relative_to_old": lambda x: f"{(x[1] - x[0]) / x[0] * 100:.2f}",
        "relative_to_new": lambda x: f"{(x[1] - x[0]) / x[1] * 100:.2f}",
    }, default="relative_to_old", truth="relative_to_old"),
    Family("id_match", _ids, {
        "exact": lambda x: str(x[0] == x[1]),
        "casefold": lambda x: str(x[0].casefold() == x[1].casefold()),
        "casefold_strip": lambda x: str(x[0].strip().casefold() == x[1].strip().casefold()),
    }, default="exact", truth="casefold_strip"),
    Family("pretax_from_gross", _gross, {
        "subtract_rate": lambda x: _q2(Decimal(x[0]) * (1 - Decimal("0.18")), ROUND_HALF_EVEN),
        "divide_rate": lambda x: _q2(Decimal(x[0]) / Decimal("1.18"), ROUND_HALF_EVEN),
    }, default="subtract_rate", truth="divide_rate"),
]}
