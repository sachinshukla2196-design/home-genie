"""Admin order operations (Batch 13, Phase 9 — ADM-06): a paged, filtered order list, an authorised CSV export, and one order
detail that brings every source together. READ ONLY: every action keeps using its existing endpoint (status, refund maker step,
COD confirmation, refund cases, returns), each with its own permission, state checks and audit. Spec:
docs/ADMIN_ORDER_OPERATIONS_SPEC.md.

Privacy: the customer's account contact (mobile / e-mail) is masked in lists and exports; the detail shows it in full only to the
roles that deal with customers (super_admin, admin, support_admin). The delivery address snapshot is shown in the detail (needed
to resolve delivery and returns) and is never exported.
"""
import csv
import io
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from core import db, require_admin
from money import paise_of

router = APIRouter(prefix="/api/admin/order-ops", tags=["admin-order-ops"])
CONTACT_ROLES = ("super_admin", "admin", "support_admin")
EXPORT_ROLES = ("super_admin", "admin", "accounts_admin")
SORTS = {"created": "created_at", "total": "total_paise", "number": "order_number"}


def mask_mobile(m: Optional[str]) -> str:
    m = (m or "").strip()
    return ("•" * max(len(m) - 4, 0) + m[-4:]) if m else ""


def mask_email(e: Optional[str]) -> str:
    e = (e or "").strip()
    if "@" not in e:
        return ""
    name, dom = e.split("@", 1)
    return (name[:1] + "•••@" + dom) if name else "•••@" + dom


def _refund_state(o: dict) -> str:
    ps = o.get("payment_status")
    return "full" if ps == "refunded" else "partial" if ps == "partially_refunded" else "none"


async def _query(q: Optional[str], vendor_id: Optional[str], payment_status: Optional[str], status: Optional[str],
                 fulfilment: Optional[str], method: Optional[str], refund: Optional[str], has_return: Optional[bool],
                 frm: Optional[str], to: Optional[str]) -> dict:
    from homegenie_metrics import ist_range
    from pagination import text_filter
    flt: dict = {}
    if frm or to:
        _, _, start, end = ist_range(frm, to)
        flt["created_at"] = {"$gte": start, "$lt": end}
    if vendor_id:
        flt["fulfilments.vendor_id"] = vendor_id
    if payment_status:
        flt["payment_status"] = payment_status
    if status:
        flt["status"] = status
    if fulfilment:
        flt["fulfilments.status"] = fulfilment
    if method in ("cod", "online"):
        flt["payment_method"] = method
    elif method:
        raise HTTPException(status_code=400, detail="method must be cod or online.")
    if refund:
        if refund not in ("none", "partial", "full", "open_case"):
            raise HTTPException(status_code=400, detail="refund must be none, partial, full or open_case.")
        if refund == "open_case":
            ids = await db.refund_cases.distinct("order_id", {"status": {"$in": ["awaiting_review", "initiated", "failed"]}})
            flt["id"] = {"$in": ids}
        else:
            flt["payment_status"] = {"none": {"$nin": ["refunded", "partially_refunded"]}, "partial": "partially_refunded", "full": "refunded"}[refund]
    if has_return is not None:
        ids = await db.return_cases.distinct("order_id", {})
        flt["id"] = {"$in": ids} if has_return else {"$nin": ids}
    tf = text_filter(q)
    if tf:
        users = await db.users.find({"$or": [{"full_name": tf}, {"mobile": tf}, {"distributor_id": tf}]}, {"_id": 0, "id": 1}).to_list(200)
        flt["$or"] = [{"order_number": tf}, {"id": (q or "").strip()}, {"address.full_name": tf}, {"user_id": {"$in": [u["id"] for u in users]}}]
    return flt


def _row(o: dict, users: dict) -> dict:
    u = users.get(o.get("user_id"), {})
    fl = o.get("fulfilments") or []
    return {"id": o["id"], "order_number": o.get("order_number"), "created_at": o.get("created_at"), "status": o.get("status"),
            "payment_status": o.get("payment_status"), "payment_method": o.get("payment_method"),
            "total_paise": paise_of(o, "total_paise", "total"), "refunded_paise": paise_of(o, "refunded_paise", "refunded_amount"),
            "refund_state": _refund_state(o), "lines": len(o.get("items") or []), "vendors": len(fl),
            "fulfilment": [{"vendor_name": f.get("vendor_name"), "status": f.get("status")} for f in fl],
            "customer": {"name": u.get("full_name") or (o.get("address") or {}).get("full_name"), "mobile": mask_mobile(u.get("mobile")),
                         "account_id": u.get("distributor_id")},
            "flags": [k for k in ("needs_refund", "refund_due_cancel") if o.get(k)] + (["duplicate_payment"] if o.get("duplicate_payments") else [])}


@router.get("/orders")
async def list_orders(q: Optional[str] = None, vendor_id: Optional[str] = None, payment_status: Optional[str] = None,
                      status: Optional[str] = None, fulfilment: Optional[str] = None, method: Optional[str] = None,
                      refund: Optional[str] = None, has_return: Optional[bool] = None, frm: Optional[str] = None,
                      to: Optional[str] = None, sort: str = "created", order: str = "desc", page: int = 1, page_size: int = 25,
                      admin: dict = Depends(require_admin)):
    from pagination import clamp_page, page_meta
    if sort not in SORTS or order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="sort must be created, total or number; order asc or desc.")
    flt = await _query(q, vendor_id, payment_status, status, fulfilment, method, refund, has_return, frm, to)
    page, page_size = clamp_page(page, page_size)
    total = await db.orders.count_documents(flt)
    rows = await db.orders.find(flt, {"_id": 0, "id": 1, "order_number": 1, "created_at": 1, "status": 1, "payment_status": 1,
                                      "payment_method": 1, "total": 1, "total_paise": 1, "refunded_paise": 1, "refunded_amount": 1,
                                      "items.vendor_id": 1, "fulfilments.vendor_name": 1, "fulfilments.status": 1, "fulfilments.vendor_id": 1,
                                      "user_id": 1, "address.full_name": 1, "needs_refund": 1, "refund_due_cancel": 1, "duplicate_payments": 1}) \
        .sort([(SORTS[sort], 1 if order == "asc" else -1), ("id", 1)]).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": list({r.get("user_id") for r in rows})}},
                                                      {"_id": 0, "id": 1, "full_name": 1, "mobile": 1, "distributor_id": 1}).to_list(None)}
    return {"items": [_row(o, users) for o in rows], **page_meta(total, page, page_size)}


@router.get("/orders.csv")
async def export_orders(q: Optional[str] = None, vendor_id: Optional[str] = None, payment_status: Optional[str] = None,
                        status: Optional[str] = None, fulfilment: Optional[str] = None, method: Optional[str] = None,
                        refund: Optional[str] = None, has_return: Optional[bool] = None, frm: Optional[str] = None,
                        to: Optional[str] = None, admin: dict = Depends(require_admin)):
    """CSV of the filtered orders (max 5,000). No addresses; customer contact masked; text is formula-injection safe."""
    from catalogue import csv_safe
    from core import log_audit
    if admin.get("role") not in EXPORT_ROLES:
        raise HTTPException(status_code=403, detail="Your role cannot export orders.")
    flt = await _query(q, vendor_id, payment_status, status, fulfilment, method, refund, has_return, frm, to)
    rows = await db.orders.find(flt, {"_id": 0}).sort("created_at", -1).limit(5000).to_list(5000)
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": list({r.get("user_id") for r in rows})}},
                                                      {"_id": 0, "id": 1, "full_name": 1, "mobile": 1, "distributor_id": 1}).to_list(None)}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["order_number", "created_at", "status", "payment_method", "payment_status", "total", "refunded", "lines", "vendors",
                "customer_account", "customer_mobile"])
    for o in rows:
        r = _row(o, users)
        w.writerow([csv_safe(r["order_number"]), r["created_at"], r["status"], r["payment_method"], r["payment_status"],
                    r["total_paise"] / 100, r["refunded_paise"] / 100, r["lines"], r["vendors"], csv_safe(r["customer"]["account_id"] or ""),
                    r["customer"]["mobile"]])
    await log_audit(admin, "orders_exported", "orders", "", new_value={"rows": len(rows), "filters": {k: v for k, v in
                    dict(q=q, vendor_id=vendor_id, payment_status=payment_status, status=status, fulfilment=fulfilment, method=method,
                         refund=refund, has_return=has_return, frm=frm, to=to).items() if v not in (None, "")}})
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=orders.csv"})


@router.get("/orders/{order_id}")
async def order_detail(order_id: str, admin: dict = Depends(require_admin)):
    from eligibility import delivered_at, payout_block
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    u = await db.users.find_one({"id": o.get("user_id")}, {"_id": 0, "full_name": 1, "mobile": 1, "email": 1, "distributor_id": 1, "role": 1}) or {}
    full = admin.get("role") in CONTACT_ROLES
    seller = await db.users.find_one({"id": o.get("seller_user_id")}, {"_id": 0, "full_name": 1, "distributor_id": 1}) if o.get("seller_user_id") else None
    vendors = {}
    for f in o.get("fulfilments") or []:
        vid = f.get("vendor_id")
        lines = [li for li in o.get("items") or [] if li.get("vendor_id") == vid]
        ledger = await db.vendor_ledger.find({"order_id": order_id, "vendor_id": vid}, {"_id": 0, "type": 1, "amount_paise": 1, "source_key": 1,
                                                                                      "posted_at": 1, "reason": 1}).sort("posted_at", 1).to_list(100)
        d_at = delivered_at(o, vid)
        vendors[vid] = {"vendor_id": vid, "vendor_name": f.get("vendor_name"), "status": f.get("status"),
                        "lines": [i for i, li in enumerate(o.get("items") or []) if li.get("vendor_id") == vid],
                        "goods_paise": sum(paise_of(li, "total_paise", "total") for li in lines),
                        "carrier": f.get("carrier"), "tracking_number": f.get("tracking_number"), "tracking_url": f.get("tracking_url"),
                        "timeline": f.get("events") or [], "delivered_at": d_at.isoformat() if d_at else None,
                        "delivery_evidence": next((e.get("note") for e in reversed(f.get("events") or []) if e.get("status") == "delivered"), None),
                        "refund_due": bool(f.get("refund_due")),
                        "ledger": ledger, "ledger_net_paise": sum(e["amount_paise"] for e in ledger),
                        "payout_block": await payout_block(o, vendor_id=vid)}
    txns = await db.payment_transactions.find({"order_id": order_id}, {"_id": 0, "session_id": 1, "provider": 1, "status": 1, "payment_status": 1,
                                                                       "amount": 1, "created_at": 1, "updated_at": 1}).sort("created_at", 1).to_list(50)
    comms = await db.commissions.find({"order_id": order_id}, {"_id": 0, "id": 1, "type": 1, "user_id": 1, "status": 1, "amount_paise": 1,
                                                               "amount": 1, "reversed_paise": 1, "base_paise": 1, "percent": 1, "released_at": 1}).to_list(20)
    names = {x["id"]: x for x in await db.users.find({"id": {"$in": [c["user_id"] for c in comms]}}, {"_id": 0, "id": 1, "distributor_id": 1}).to_list(20)}
    for c in comms:
        c["member"] = names.get(c.pop("user_id"), {}).get("distributor_id")
        c["amount_paise"] = paise_of(c, "amount_paise", "amount")
    returns = await db.return_cases.find({"order_id": order_id}, {"_id": 0}).sort("created_at", 1).to_list(50)
    refunds = await db.refund_cases.find({"order_id": order_id}, {"_id": 0}).sort("created_at", 1).to_list(50)
    refund_events = await db.order_refunds.find({"order_id": order_id}, {"_id": 0}).sort("created_at", 1).to_list(50)
    audit = await db.audit_logs.find({"entity_id": order_id}, {"_id": 0, "action": 1, "user_id": 1, "user_email": 1, "created_at": 1,
                                                               "new_value": 1, "old_value": 1}).sort("created_at", 1).to_list(200)
    whole = delivered_at(o)
    return {
        "order": {k: o.get(k) for k in ("id", "order_number", "created_at", "status", "payment_method", "payment_status", "paid_at", "payment_reference",
                                       "prices_include_gst", "money_version", "items", "items_total_paise", "subtotal", "gst_amount", "cod_fee",
                                       "cod_fee_paise", "total", "total_paise", "refunded_paise", "invoice_number", "cancel_reason", "cancelled_at",
                                       "needs_refund", "refund_due_cancel", "duplicate_payments", "cod_collection", "cod_discrepancy",
                                       "cod_expected_paise", "commission_base_paise", "status_set_by_admin", "seller_distributor_id")},
        "address": o.get("address"),
        "customer": {"name": u.get("full_name"), "account_id": u.get("distributor_id"), "role": u.get("role"),
                     "mobile": u.get("mobile") if full else mask_mobile(u.get("mobile")),
                     "email": u.get("email") if full else mask_email(u.get("email")), "masked": not full},
        "seller": seller, "vendors": list(vendors.values()),
        "delivery": {"order_delivered_at": whole.isoformat() if whole else None, "order_payout_block": await payout_block(o),
                     "note": "Delivery is recorded per vendor by the vendor's fulfilment; an admin status change is shown separately and is not a delivery."},
        "payments": txns, "commissions": comms, "returns": returns, "refund_cases": refunds, "refund_events": refund_events, "audit": audit,
    }
