"""Programme 03 (B-023): the immutable evidence recorded with every vendor settlement when it is requested.

A settlement is a lump sum paid against the vendor's eligible ledger balance. Until now nothing recorded WHICH orders made that
balance eligible, or WHICH bank details the payout was requested against, so a later ledger or bank-detail change could not be
told apart from what finance saw when they approved it. The snapshot records, once, at creation:

- the balance figures the request was checked against (integer paise) and the requested amount;
- the order basis: the net ledger amount of every order that was eligible then (and those still held, with the reason), the
  entries with no order, and a digest over the full list (the stored list is capped so the document stays small);
- the payee bank details in MINIMAL form: account holder name, IFSC, the account number masked to its last four digits, and the
  id of the last approved bank-detail change. The full account number is never copied, logged or hashed here (a plain hash of an
  account number is brute-forceable; A-01 - the encryption-key design - is unresolved, so no new key is introduced).

`snapshot_digest` (SHA-256 over the canonical JSON of the snapshot) is stored next to it; `verify` recomputes it, so any later edit
is detectable. Nothing in the application updates a snapshot after creation. The snapshot is EVIDENCE, not authority to pay:
payment still requires the existing maker-checker approvals and the live balance check. One protective check uses it: a settlement
is not marked paid if the vendor's bank details changed since it was requested (reject it and request a new one).
"""
import hashlib
import json
from typing import Optional

from core import db, now_iso

VERSION = 1
MAX_ORDERS_STORED = 2000          # the digest and totals always cover every order; only the stored list is capped
MAX_HELD_STORED = 500


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(snapshot: dict) -> str:
    return hashlib.sha256(_canon(snapshot).encode()).hexdigest()


def _orders_digest(items: list) -> str:
    h = hashlib.sha256()
    for it in items:                               # items are sorted by order id (ledger.eligible_detail)
        h.update(f"{it['order_id']}:{int(it['amount_paise'])}\n".encode())
    return h.hexdigest()


def mask_account(acct: Optional[str]) -> str:
    a = str(acct or "").strip()
    if not a:
        return ""
    return "*" * len(a) if len(a) <= 4 else "XXXX" + a[-4:]


async def bank_fingerprint(vendor: dict) -> dict:
    """The payee bank details in minimal form (no full account number)."""
    last = await db.vendor_change_requests.find({"vendor_id": vendor["id"], "kind": "bank", "status": "approved"},
                                                {"_id": 0, "id": 1}).sort("decided_at", -1).limit(1).to_list(1)
    acct = str(vendor.get("bank_account") or "").strip()
    return {"present": bool(acct), "account_holder": (vendor.get("bank_account_name") or "").strip(),
            "ifsc": (vendor.get("ifsc") or "").strip().upper(), "account_masked": mask_account(acct),
            "account_last4": acct[-4:] if len(acct) > 4 else "", "bank_change_id": last[0]["id"] if last else None}


BANK_FIELDS = ("present", "account_holder", "ifsc", "account_masked", "account_last4", "bank_change_id")


def bank_changed(snapshot_bank: dict, current: dict) -> list:
    """The bank fields that differ between the snapshot and now (names only; never values)."""
    return [f for f in BANK_FIELDS if (snapshot_bank or {}).get(f) != current.get(f)]


async def build(vendor: dict, bal: dict, amount_paise: int, actor_id: str) -> dict:
    """The snapshot for a settlement being created now. Raises if the composition does not add up (it always should)."""
    import ledger as L
    d = await L.eligible_detail(vendor["id"])
    orders_total = sum(int(x["amount_paise"]) for x in d["eligible"])
    if orders_total + d["non_order_paise"] != d["eligible_paise"]:
        raise RuntimeError("settlement snapshot: eligible composition does not add up")
    return {
        "version": VERSION, "captured_at": now_iso(), "captured_by": actor_id,
        "basis": {"requested_paise": int(amount_paise),
                  **{k: int(bal[k]) for k in ("available_for_settlement_paise", "pending_settlement_paise", "settlement_in_progress_paise",
                                              "vendor_payable_paise", "settled_paise", "awaiting_eligibility_paise")},
                  "eligible_paise": d["eligible_paise"], "non_order_paise": d["non_order_paise"], "orders_total_paise": orders_total,
                  "held_orders": d["held_orders"]},
        "orders": d["eligible"][:MAX_ORDERS_STORED], "orders_count": len(d["eligible"]),
        "orders_truncated": len(d["eligible"]) > MAX_ORDERS_STORED, "orders_digest": _orders_digest(d["eligible"]),
        "held": d["held"][:MAX_HELD_STORED], "held_count": len(d["held"]),
        "bank": await bank_fingerprint(vendor),
    }


def verify(s: dict) -> Optional[bool]:
    """True when the stored snapshot still matches its digest; None for a settlement created before snapshots existed."""
    snap = s.get("snapshot")
    if snap is None:
        return None
    return bool(s.get("snapshot_digest")) and digest(snap) == s["snapshot_digest"]


def summary(s: dict) -> dict:
    """A small view for lists: totals, counts, the masked bank details and whether the snapshot verifies."""
    snap = s.get("snapshot")
    if snap is None:
        return {"present": False}
    return {"present": True, "verified": verify(s), "captured_at": snap.get("captured_at"), "basis": snap.get("basis"),
            "orders_count": snap.get("orders_count"), "held_count": snap.get("held_count"),
            "bank": {k: (snap.get("bank") or {}).get(k) for k in ("present", "account_holder", "ifsc", "account_masked")}}


async def audit(limit_report: int = 200) -> dict:
    """Read-only: every settlement's snapshot verifies, and its requested amount was within the eligible basis it recorded."""
    out = {"with_snapshot": 0, "legacy_without_snapshot": 0, "issues": []}
    async for s in db.settlements.find({}, {"_id": 0}):
        ok = verify(s)
        if ok is None:
            out["legacy_without_snapshot"] += 1
            continue
        out["with_snapshot"] += 1
        problem = None
        if not ok:
            problem = "snapshot_digest_mismatch"
        elif s["snapshot"]["basis"]["requested_paise"] != s.get("amount_paise"):
            problem = "amount_differs_from_snapshot"
        elif s["snapshot"]["basis"]["requested_paise"] > s["snapshot"]["basis"]["available_for_settlement_paise"]:
            problem = "requested_above_recorded_available"
        if problem and len(out["issues"]) < limit_report:
            out["issues"].append({"settlement_id": s["id"], "number": s.get("number"), "issue": problem})
    return out
