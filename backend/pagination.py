"""Small shared helpers for server-side pagination and safe text search."""
import math
import re
from typing import Optional

MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 20


def clamp_page(page: Optional[int], page_size: Optional[int]):
    p = max(int(page or 1), 1)
    s = min(max(int(page_size or DEFAULT_PAGE_SIZE), 1), MAX_PAGE_SIZE)
    return p, s


def page_meta(total: int, page: int, page_size: int) -> dict:
    return {"total": total, "page": page, "page_size": page_size, "pages": max(math.ceil(total / page_size), 1)}


def text_filter(q: Optional[str]) -> Optional[dict]:
    """Case-insensitive 'contains' filter. The input is escaped, so it can never act as a regex or a Mongo operator."""
    q = (q or "").strip()[:80]
    return {"$regex": re.escape(q), "$options": "i"} if q else None


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def is_real_date(v: str) -> bool:
    """YYYY-MM-DD that is also a real calendar date (rejects 2026-13-01 and 2026-02-30)."""
    from datetime import date
    try:
        date.fromisoformat(v)
        return bool(DATE_RE.fullmatch(v))
    except ValueError:
        return False


def date_range(date_from: Optional[str], date_to: Optional[str]) -> Optional[dict]:
    """ISO-date (YYYY-MM-DD) bounds on a `created_at` ISO-string field; returns None when neither is given."""
    out = {}
    if date_from:
        if not is_real_date(date_from):
            raise ValueError("date_from")
        out["$gte"] = date_from
    if date_to:
        if not is_real_date(date_to):
            raise ValueError("date_to")
        out["$lte"] = f"{date_to}T23:59:59.999999"
    return out or None
