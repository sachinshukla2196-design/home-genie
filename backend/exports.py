"""Programme 02 / W4: one place for how a report or export leaves the server.

- `csv_cell(v)`        spreadsheet-formula neutralisation for EVERY exported cell (one rule, tested). Numbers stay numbers; a text
                        value that a spreadsheet would read as a formula gets a leading apostrophe.
- `csv_response(...)`  an in-memory CSV streamed in the authorised response: no file is written, no link is created, nothing is
                        cached (`Cache-Control: no-store`), and the response carries an export id that is also in the audit record.
- `check_size(...)`    refuses (HTTP 413) instead of silently truncating when a request asks for more rows than an export allows.
- `date_bounds(...)`   validated YYYY-MM-DD bounds (real dates, start not after end).
- `audit_export(...)`  one audit record per export attempt (success, refused or failed): who, role, what, range, filters (free text
                        redacted), rows, format, export id. Never the exported values, never a token, password, OTP, PAN, Aadhaar
                        or account number.
- masking helpers     for bulk listings (contact, payment references).
"""
import csv
import io
import re
from typing import Iterable, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse

from core import log_audit, new_id

# Characters that make a spreadsheet treat a cell as a formula (incl. full-width forms Excel also accepts) and the control
# characters that can start one after a line break inside a cell.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")
_NUMBER = re.compile(r"[+-]?\d+(\.\d+)?")


def csv_cell(v):
    """Neutralise spreadsheet formula injection in one cell. Numbers / booleans are returned unchanged (they are not text), and
    so is a text value that is only a number (e.g. "-120.00": a spreadsheet reads it as a number, never as a formula)."""
    if v is None:
        return ""
    if isinstance(v, (bool, int, float)):
        return v
    s = str(v)
    if _NUMBER.fullmatch(s.strip()):
        return s
    if s.lstrip(" ").startswith(FORMULA_START) or s.startswith(FORMULA_START):
        return "'" + s
    return s


def csv_text(header: List[str], rows: Iterable[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([csv_cell(h) for h in header])
    for r in rows:
        w.writerow([csv_cell(x) for x in r])
    return buf.getvalue()


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120] or "export.csv"


def csv_response(text: str, filename: str, export_id: str) -> StreamingResponse:
    return StreamingResponse(iter([text]), media_type="text/csv", headers={
        "Content-Disposition": f"attachment; filename={_safe_filename(filename)}",
        "Cache-Control": "no-store", "Pragma": "no-cache", "X-Export-Id": export_id})


def date_bounds(date_from: Optional[str], date_to: Optional[str]) -> Optional[dict]:
    """`created_at` bounds from inclusive YYYY-MM-DD dates; 400 for a malformed / impossible date or a start after the end."""
    from pagination import date_range
    try:
        b = date_range(date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e} must be a real date like 2026-10-23.")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=400, detail="The start date is after the end date.")
    return b


def new_export_id() -> str:
    return "exp_" + new_id().replace("-", "")[:20]


_DIGITS = re.compile(r"\d{5,}")
_EMAIL = re.compile(r"[^\s@]+@[^\s@]+")


def redact(text: Optional[str]) -> Optional[str]:
    """Free-text filters (a search box) may hold a mobile number, an e-mail or an identity number: keep the shape, not the value."""
    if text is None:
        return None
    t = _EMAIL.sub("[email]", str(text)[:80])
    return _DIGITS.sub(lambda m: "•" * (len(m.group()) - 2) + m.group()[-2:], t)


async def audit_export(actor: dict, request: Optional[Request], kind: str, export_id: str, *, status: str = "success",
                       rows: Optional[int] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
                       filters: Optional[dict] = None, fmt: str = "csv", reason: Optional[str] = None, scope: Optional[str] = None) -> None:
    """status: success | refused | failed. `filters` values are redacted; nothing exported is ever written here."""
    clean = {k: (redact(v) if isinstance(v, str) else v) for k, v in (filters or {}).items() if v not in (None, "")}
    await log_audit(actor, f"export_{status}", "export", kind, new_value={
        "export_id": export_id, "report": kind, "format": fmt, "role": actor.get("role"), "rows": rows,
        "date_from": date_from, "date_to": date_to, "filters": clean, **({"reason": reason} if reason else {}),
        **({"scope": scope} if scope else {})}, request=request)


async def check_size(actor: dict, request: Optional[Request], kind: str, export_id: str, count: int, limit: int, **ctx) -> None:
    """Refuse an export larger than `limit` rows (no silent truncation); the refusal is audited."""
    if count > limit:
        await audit_export(actor, request, kind, export_id, status="refused", rows=count, reason="too_many_rows", **ctx)
        raise HTTPException(status_code=413, detail=f"This export has {count:,} rows; the limit is {limit:,}. "
                                                    "Choose a shorter date range or more filters.")


# ------------------------------------------------------------------ masking for bulk listings / exports
def mask_mobile(m: Optional[str]) -> str:
    m = str(m or "").strip()
    return ("•" * max(len(m) - 4, 0) + m[-4:]) if m else ""


def mask_email(e: Optional[str]) -> str:
    e = str(e or "").strip()
    if "@" not in e:
        return ""
    name, dom = e.split("@", 1)
    return (name[:1] + "•••@" + dom) if name else "•••@" + dom


def mask_reference(r: Optional[str], keep: int = 6) -> str:
    """Payment session ids work as look-up keys for the public payment-status endpoint: listings show only the tail."""
    r = str(r or "")
    return ("•" * max(len(r) - keep, 0) + r[-keep:]) if r else ""
