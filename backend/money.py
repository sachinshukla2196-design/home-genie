"""Exact money arithmetic for HOME GENIES.

All financial arithmetic is done on INTEGER PAISE (1 rupee = 100 paise) using Decimal for the few places that need a
percentage or ratio. Floats are never used for calculation. Rupee floats still exist in stored documents for
backward compatibility; they are always *derived* from paise (`paise_to_float`) and never the source of a calculation.

Rounding rule (one rule everywhere): ROUND_HALF_UP to the nearest paisa.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Iterable

_Q0 = Decimal("1")
_Q2 = Decimal("0.01")


def dec(v) -> Decimal:
    """Rupee value -> Decimal via its shortest decimal text (so the float 0.1 + 0.2 reads as 0.30000000000000004, not a
    binary fraction). Raises ValueError for anything that is not a finite number."""
    if isinstance(v, Decimal):
        d = v
    else:
        try:
            d = Decimal(str(v).strip())
        except (InvalidOperation, ValueError):
            raise ValueError(f"Not a valid amount: {v!r}")
    if not d.is_finite():
        raise ValueError(f"Not a valid amount: {v!r}")
    return d


def to_paise(rupees) -> int:
    """Rupees (int / float / str / Decimal) -> integer paise, rounded half-up to the paisa."""
    return int((dec(rupees) * 100).quantize(_Q0, rounding=ROUND_HALF_UP))


def paise_to_float(paise: int) -> float:
    """Integer paise -> the rupee float that is exactly that value to 2 decimals (for JSON / legacy fields only)."""
    return float((Decimal(int(paise)) / 100).quantize(_Q2))


def paise_to_str(paise: int) -> str:
    return f"{(Decimal(int(paise)) / 100).quantize(_Q2):f}"


def mul_pct(paise: int, pct) -> int:
    """paise x pct% (pct may be int/float/str/Decimal), rounded half-up."""
    return int((Decimal(int(paise)) * dec(pct) / 100).quantize(_Q0, rounding=ROUND_HALF_UP))


def mul_ratio(paise: int, num: int, den: int) -> int:
    """paise x num/den with pure integer arithmetic, rounded half-up (non-negative inputs)."""
    if den <= 0:
        raise ValueError("denominator must be positive")
    return (2 * int(paise) * int(num) + int(den)) // (2 * int(den))


def sum_paise(values: Iterable[int]) -> int:
    return sum(int(v) for v in values)


def split_exact(total: int, parts: int) -> list:
    """Split `total` paise into `parts` shares that add up to exactly `total` (earlier shares get the extra paisa)."""
    base, extra = divmod(int(total), parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def fmt_inr(paise: int) -> str:
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(int(paise)), 100)
    return f"{sign}₹{rupees:,}.{p:02d}"


def paise_of(doc: dict, paise_key: str, legacy_key: str) -> int:
    """Read a money field from a document: the exact paise field when present, else convert the legacy rupee float."""
    v = doc.get(paise_key)
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return to_paise(doc.get(legacy_key) or 0)
