"""Append-only vendor status history (onboarding / approval / suspension). Never edited; resubmissions add new rows."""
from typing import Optional

from core import db, now_iso, new_id


async def record_vendor_status(vendor_id: str, frm: Optional[str], to: str, actor: str, reason: str = "", internal_note: str = ""):
    """`reason` is shown to the vendor; `internal_note` is admin-only and is never returned by vendor endpoints."""
    await db.vendor_status_history.insert_one({"id": new_id(), "vendor_id": vendor_id, "from": frm, "to": to, "actor": actor,
                                               "reason": reason, "internal_note": internal_note, "at": now_iso()})


async def missing_required_documents(vendor_id: str) -> list:
    """Documents an admin has made mandatory that this vendor has not provided (or had rejected). Empty until configured."""
    pol = await db.vendor_policy.find_one({"id": "vendor_policy"}, {"_id": 0}) or {}
    req = pol.get("required_documents") or []
    if not req:
        return []
    have = {d["type"] for d in await db.vendor_documents.find({"vendor_id": vendor_id, "status": {"$ne": "rejected"}, "deleted": {"$ne": True}}, {"_id": 0, "type": 1}).to_list(50)}
    return [r for r in req if r not in have]
