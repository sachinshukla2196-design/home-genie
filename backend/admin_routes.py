"""Admin panel routes: dashboard, users, products, orders, KYC, withdrawals,
commissions, settings, audit logs, reports (with CSV export)."""
import io
import csv
import math
import re
import secrets
from core import hash_password, next_distributor_id, get_or_create_wallet
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from pymongo.errors import DuplicateKeyError
from typing import Optional, List
from datetime import datetime, timezone
from pagination import clamp_page, page_meta
from money import to_paise, paise_to_float, paise_of
from stock import run_intents, intent

from core import (db, now_iso, new_id, require_admin, get_settings, P_PUBLIC,
                  add_wallet_transaction, wallet_apply, create_notification, log_audit,
                  clean_user, mask_aadhaar, password_update)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _mask_pan(p: str) -> str:
    p = str(p or "").strip().upper()
    if len(p) < 6:
        return "*" * len(p)
    return "XXXXX" + p[5:9] + "X"  # ABCDE1234F -> XXXXX1234X


def _mask_acct(a: str) -> str:
    a = str(a or "").strip()
    if len(a) <= 4:
        return "*" * len(a)
    return "XXXX" + a[-4:]  # only last 4 visible


def _mask_ifsc(i: str) -> str:
    i = str(i or "").strip().upper()
    if len(i) <= 4:
        return "*" * len(i)
    return i[:4] + "*" * (len(i) - 4)  # keep bank code, hide branch


# ---------------- Dashboard ----------------
@router.get("/dashboard")
async def admin_dashboard(admin: dict = Depends(require_admin)):
    settings = await get_settings()
    today = datetime.now(timezone.utc).date().isoformat()

    total_users = await db.users.count_documents({"role": {"$in": ["distributor", "customer", "vendor"]}})
    red_users = await db.users.count_documents({"status": "red", "role": {"$in": ["distributor", "customer", "vendor"]}})
    green_users = await db.users.count_documents({"status": "green", "role": {"$in": ["distributor", "customer", "vendor"]}})
    pending_kyc = await db.kyc_records.count_documents({"status": "pending"})
    pending_wd = await db.withdrawal_requests.count_documents({"status": {"$in": list(REQUESTED_STATES)}})   # requested, awaiting approval

    def today_q(field="created_at"):
        return {field: {"$regex": f"^{today}"}}

    today_regs = await db.users.count_documents({"created_at": {"$regex": f"^{today}"}})
    today_acts = await db.users.count_documents({"status": "green", "approved_at": {"$regex": f"^{today}"}})
    today_orders = await db.orders.count_documents({"created_at": {"$regex": f"^{today}"}, "payment_status": "paid"})

    revenue_docs = await db.orders.find({"payment_status": "paid", "created_at": {"$regex": f"^{today}"}},
                                        {"_id": 0, "total": 1}).to_list(1000)
    today_revenue = sum(o.get("total", 0) for o in revenue_docs)

    all_paid = await db.orders.find({"payment_status": "paid"}, {"_id": 0, "total": 1}).to_list(5000)
    total_revenue = sum(o.get("total", 0) for o in all_paid)

    return {
        "settings": {"currency_symbol": settings.get("currency_symbol", "₹")},
        "stats": {
            "total_users": total_users, "red_users": red_users, "green_users": green_users,
            "today_registrations": today_regs, "today_activations": today_acts,
            "today_orders": today_orders, "today_revenue": today_revenue,
            "total_revenue": total_revenue,
            "pending_kyc": pending_kyc, "pending_withdrawals": pending_wd,
        },
    }


# ---------------- Users ----------------
@router.get("/users")
async def admin_users(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {"role": {"$in": ["distributor", "customer", "vendor"]}}
    if status:
        q["status"] = status
    users = await db.users.find(q, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(1000)
    for u in users:
        if u.get("aadhaar_number"):
            u["aadhaar_masked"] = mask_aadhaar(u["aadhaar_number"])
            u.pop("aadhaar_number", None)
    return users


@router.get("/users/{user_id}")
async def admin_user_detail(user_id: str, admin: dict = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    if u.get("aadhaar_number"):
        u["aadhaar_masked"] = mask_aadhaar(u["aadhaar_number"])
        u.pop("aadhaar_number", None)
    from core import get_or_create_wallet
    wallet = await get_or_create_wallet(user_id)    # exact (paise-derived) balances
    orders = await db.orders.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"user": u, "wallet": wallet, "orders": orders}


# ---------------- Products ----------------
class ProductBody(BaseModel):
    sku: str
    name: str
    name_hi: str = ""
    description: str = ""
    description_hi: str = ""
    images: List[str] = []
    mrp: float
    selling_price: float
    gst_percent: float = 5.0
    stock: int = 100
    category: str = "Household Essentials"
    is_active: bool = True
    # Optional purchase options, e.g. [{"name": "Size", "values": ["Free Size"]},
    #                                  {"name": "Shade", "values": ["Maroon", "Gold"]}]
    options: List[dict] = []


@router.post("/products")
async def create_product(body: ProductBody, request: Request, admin: dict = Depends(require_admin)):
    if await db.products.find_one({"sku": body.sku}):
        raise HTTPException(status_code=400, detail="A product with this SKU already exists.")
    p = body.model_dump()
    p.update({"id": new_id(), "created_at": now_iso(), "updated_at": now_iso()})
    await db.products.insert_one(dict(p))
    await log_audit(admin, "product_created", "product", p["id"], new_value={"sku": p["sku"]}, request=request)
    p.pop("_id", None)
    return p


@router.put("/products/{product_id}")
async def update_product(product_id: str, body: ProductBody, request: Request, admin: dict = Depends(require_admin)):
    existing = await db.products.find_one({"id": product_id}, P_PUBLIC)
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found.")
    upd = body.model_dump()
    upd["updated_at"] = now_iso()
    await db.products.update_one({"id": product_id}, {"$set": upd})
    await log_audit(admin, "product_updated", "product", product_id, old_value=existing, new_value=upd, request=request)
    return {**existing, **upd}


@router.delete("/products/{product_id}")
async def deactivate_product(product_id: str, request: Request, admin: dict = Depends(require_admin)):
    await db.products.update_one({"id": product_id}, {"$set": {"is_active": False, "updated_at": now_iso()}})
    await log_audit(admin, "product_deactivated", "product", product_id, request=request)
    return {"ok": True}


@router.delete("/products/{product_id}/permanent")
async def delete_product_permanent(product_id: str, request: Request, admin: dict = Depends(require_admin)):
    p = await db.products.find_one({"id": product_id}, P_PUBLIC)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    await db.products.delete_one({"id": product_id})
    await log_audit(admin, "product_deleted", "product", product_id,
                    old_value={"sku": p.get("sku"), "name": p.get("name")}, request=request)
    return {"ok": True}


# ---------------- Orders ----------------
@router.get("/orders")
async def admin_orders(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    orders = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    uids = list({o.get("user_id") for o in orders if o.get("user_id")})
    users = await db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "full_name": 1}).to_list(2000)
    names = {u["id"]: u.get("full_name") for u in users}
    for o in orders:
        o["user_name"] = names.get(o.get("user_id"), "")
    return orders


class OrderStatusBody(BaseModel):
    status: str


@router.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, body: OrderStatusBody, request: Request, admin: dict = Depends(require_admin)):
    allowed = ["pending", "payment_pending", "paid", "processing", "packed", "shipped", "delivered", "cancelled", "refunded"]
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status.")
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if body.status == "refunded" and o.get("payment_status") in ("paid", "partially_refunded"):
        raise HTTPException(status_code=400, detail="Use the Refund action (with amount & payment reference) to refund a paid order.")
    if o.get("needs_refund") and o.get("payment_status") in ("paid", "partially_refunded") and body.status != "cancelled":
        raise HTTPException(status_code=400, detail="This order was paid after it expired and cannot be fulfilled. "
                                                    "Refund it from the Needs refund queue.")
    upd = {"$set": {"status": body.status, "updated_at": now_iso()}}
    cancelling = body.status == "cancelled" and o.get("status") != "cancelled"
    if cancelling:   # the restock decision is stored atomically with the status change; recovery replays it if interrupted
        upd["$push"] = {"restock_intents": intent("admin_cancel", admin["id"], prev_status=o.get("status", ""))}
    await db.orders.update_one({"id": order_id}, upd)
    restock = None
    if cancelling:
        # Confirmed cancellation: return stock for goods that have not left, stop pre-dispatch fulfilment.
        restock = {"restocked_lines": await run_intents(order_id)}
    # NOTE: 'cancelled' on a PAID order does NOT reverse commissions by itself — only a confirmed
    # payment return (Refund action) does. Unpaid cancelled orders never generated commissions.
    await create_notification(o["user_id"], "order", "Order update",
                              f"Your order {o['order_number']} is now {body.status}.",
                              "ऑर्डर अपडेट", f"आपका ऑर्डर {o['order_number']} अब {body.status} है।")
    await log_audit(admin, "order_status_changed", "order", order_id,
                    old_value={"status": o["status"]}, new_value={"status": body.status, "restock": restock}, request=request)
    return {"ok": True, "restock": restock}


class RefundBody(BaseModel):
    amount: Optional[float] = None  # None/omitted = full remaining refund
    reference: str
    reason: str = ""
    cancel_order: bool = False


@router.post("/orders/{order_id}/refund")
async def refund_order(order_id: str, body: RefundBody, request: Request, admin: dict = Depends(require_admin)):
    """Record a confirmed payment return (full or partial) and claw back order-dependent credits proportionally."""
    ref = (body.reference or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Refund payment reference (UTR / Razorpay refund id) is required.")
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.get("payment_status") not in ("paid", "partially_refunded"):
        raise HTTPException(status_code=400, detail="Only paid orders can be refunded.")
    from cod_rules import refundable_total_paise
    remaining_p = refundable_total_paise(o, paise_of(o, "total_paise", "total")) - paise_of(o, "refunded_paise", "refunded_amount")
    remaining = paise_to_float(remaining_p)
    if body.amount is not None and (to_paise(body.amount) <= 0 or to_paise(body.amount) > remaining_p):
        raise HTTPException(status_code=400, detail=f"Refund amount must be between 0 and ₹{remaining}.")
    import shop_routes
    res = await shop_routes.reverse_order_financials(order_id, admin, request, refund_amount=body.amount, reference=ref, reason=body.reason)
    if res.get("duplicate"):
        raise HTTPException(status_code=409, detail="A refund with this reference was already recorded for this order.")
    new_status = "cancelled" if body.cancel_order else ("refunded" if to_paise(res["refund_amount"]) >= remaining_p else o.get("status"))
    upd = {"$set": {"status": new_status, "updated_at": now_iso()}}
    cancelling = new_status == "cancelled" and o.get("status") != "cancelled"
    if cancelling:
        upd["$push"] = {"restock_intents": intent("admin_cancel", admin["id"], prev_status=o.get("status", ""))}
    await db.orders.update_one({"id": order_id}, upd)
    if cancelling:
        await run_intents(order_id)
    await create_notification(o["user_id"], "order", "Refund processed",
                              f"₹{res['refund_amount']:g} refunded on order {o['order_number']} (ref {ref}).",
                              "रिफंड हो गया", f"ऑर्डर {o['order_number']} पर ₹{res['refund_amount']:g} रिफंड हुआ।")
    return {"ok": True, **res, "status": new_status}


@router.get("/refund-queue")
async def refund_queue(state: str = "open", page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    """Orders paid after they had expired (15-minute rule, stock gone) or been cancelled; they cannot be fulfilled.
    'open' = still awaiting a refund (oldest first); 'resolved' = fully refunded."""
    if state not in ("open", "resolved"):
        raise HTTPException(status_code=400, detail="state must be 'open' or 'resolved'.")
    page, page_size = clamp_page(page, page_size)
    open_q = {"needs_refund": True, "payment_status": {"$in": ["paid", "partially_refunded"]}}
    q = open_q if state == "open" else {"needs_refund": True, "payment_status": "refunded"}
    total = await db.orders.count_documents(q)
    rows = await db.orders.find(q, {"_id": 0}).sort("needs_refund_at", 1 if state == "open" else -1) \
        .skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": [r["user_id"] for r in rows]}},
                                                     {"_id": 0, "id": 1, "full_name": 1, "mobile": 1}).to_list(page_size)}
    now = datetime.now(timezone.utc)
    for r in rows:
        u = users.get(r["user_id"], {})
        r["user_name"], r["user_mobile"] = u.get("full_name", ""), u.get("mobile", "")
        try:
            r["waiting_hours"] = round((now - datetime.fromisoformat(r.get("needs_refund_at") or r["paid_at"])).total_seconds() / 3600, 1)
        except Exception:
            r["waiting_hours"] = None
    return {"items": rows, **page_meta(total, page, page_size), "open_count": await db.orders.count_documents(open_q)}


@router.delete("/orders/{order_id}")
async def delete_order(order_id: str, request: Request, admin: dict = Depends(require_admin)):
    """Permanently delete an order and its related payment transactions."""
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.get("payment_status") in ("paid", "partially_refunded", "refunded") or await db.commissions.count_documents({"reference_order_id": order_id}):
        raise HTTPException(status_code=400, detail="Paid orders with financial history cannot be deleted. Use Refund to reverse it; the record stays for audit.")
    await db.orders.delete_one({"id": order_id})
    await db.payment_transactions.delete_many({"order_id": order_id})
    await log_audit(admin, "order_deleted", "order", order_id,
                    old_value={"order_number": o.get("order_number"), "total": o.get("total")}, request=request)
    return {"ok": True}


# ---------------- Payments ----------------
@router.get("/payments")
async def admin_payments(admin: dict = Depends(require_admin)):
    return await db.payment_transactions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


# ---------------- Activations / Referrals / Commissions ----------------
@router.get("/referrals")
async def admin_referrals(admin: dict = Depends(require_admin)):
    return await db.referral_relationships.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.get("/commissions")
async def admin_commissions(admin: dict = Depends(require_admin)):
    return await db.commissions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


class CommissionActionBody(BaseModel):
    action: str  # release / hold
    reason: str = ""


MONEY_ADMIN_ROLES = ("super_admin", "accounts_admin")      # roles that may move money by hand (same set as the finance controls)


def require_money_admin(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") not in MONEY_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only a finance administrator can do this.")
    return admin


@router.put("/commissions/{commission_id}/status")
async def commission_status(commission_id: str, body: CommissionActionBody, request: Request, admin: dict = Depends(require_money_admin)):
    """`release` is "release now" through the normal release path (same conditions, no override). `hold` sets a flag that keeps a
    commission out of the cron without changing its status, so refunds still claw it back. A hold is not a bypass: releasing a
    held commission needs every normal condition, exactly as for any other."""
    reason = (body.reason or "").strip()
    if len(reason) < 5 or len(reason) > 300:
        raise HTTPException(status_code=422, detail="A reason of 5 to 300 characters is required.")
    c = await db.commissions.find_one({"id": commission_id})
    if not c:
        raise HTTPException(status_code=404, detail="Commission not found.")
    if body.action == "release":
        from commission import release_commission_now
        res = await release_commission_now(commission_id)
        if not res["ok"]:
            raise HTTPException(status_code=res["code"], detail=res["detail"])
        if not res.get("already"):
            await log_audit(admin, "commission_released", "commission", commission_id,
                            old_value={"status": c.get("status")}, new_value={"status": "RELEASED", "released_paise": res.get("released_paise"), "reason": reason}, request=request)
        return {"ok": True, **{k: v for k, v in res.items() if k != "ok"}}
    if body.action == "hold":
        held = await db.commissions.update_one({"id": commission_id, "status": {"$in": ["PENDING", "PARTIALLY_REVERSED"]}, "released_at": None,
                                                 "manual_hold": {"$ne": True}},
                                               {"$set": {"manual_hold": True, "held_at": now_iso(), "held_by": admin["id"], "hold_reason": reason}})
        if held.modified_count != 1:
            raise HTTPException(status_code=409, detail="Only a pending, unreleased, not already held commission can be held.")
        await log_audit(admin, "commission_held", "commission", commission_id,
                        old_value={"status": c.get("status")}, new_value={"manual_hold": True, "reason": reason}, request=request)
        return {"ok": True, "status": c.get("status"), "manual_hold": True}
    raise HTTPException(status_code=400, detail="Invalid action.")


# ---------------- KYC review ----------------
@router.get("/kyc")
async def admin_kyc(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    recs = await db.kyc_records.find(q, {"_id": 0}).sort("submitted_at", -1).to_list(1000)
    for r in recs:
        if r.get("aadhaar"):
            r["aadhaar"] = mask_aadhaar(r["aadhaar"])
        if r.get("pan"):
            r["pan"] = _mask_pan(r["pan"])
        if r.get("bank_account"):
            r["bank_account"] = _mask_acct(r["bank_account"])
        if r.get("ifsc"):
            r["ifsc"] = _mask_ifsc(r["ifsc"])
    return recs


class KycReview(BaseModel):
    action: str  # verify / reject
    reason: Optional[str] = ""


class KycEditBody(BaseModel):
    pan: Optional[str] = None
    account_holder_name: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    bank_name: Optional[str] = None


@router.put("/kyc/{user_id}/edit")
async def admin_edit_kyc(user_id: str, body: KycEditBody, request: Request, admin: dict = Depends(require_admin)):
    """Admin completes/corrects a member's identity details. Saved to the real DB, audited."""
    upd = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if "pan" in upd:
        upd["pan"] = upd["pan"].upper()
    if "ifsc" in upd:
        upd["ifsc"] = upd["ifsc"].upper()
    upd["updated_at"] = now_iso()
    existing = await db.kyc_records.find_one({"user_id": user_id})
    if existing:
        await db.kyc_records.update_one({"user_id": user_id}, {"$set": upd})
    else:
        u = await db.users.find_one({"id": user_id})
        if not u:
            raise HTTPException(status_code=404, detail="Distributor not found.")
        upd.update({"id": new_id(), "user_id": user_id, "distributor_id": u.get("distributor_id"),
                    "status": "pending", "aadhaar": "", "created_at": now_iso(), "submitted_at": now_iso()})
        await db.kyc_records.insert_one(upd)
        await db.users.update_one({"id": user_id}, {"$set": {"kyc_status": "pending"}})
    await log_audit(admin, "kyc_edited_by_admin", "kyc", user_id, new_value=list(upd.keys()), request=request)
    return {"ok": True}


@router.put("/kyc/{user_id}")
async def review_kyc(user_id: str, body: KycReview, request: Request, admin: dict = Depends(require_admin)):
    k = await db.kyc_records.find_one({"user_id": user_id}, {"_id": 0})
    if not k:
        raise HTTPException(status_code=404, detail="KYC record not found.")
    new_status = None
    if body.action == "verify":
        new_status = "verified"
    elif body.action == "reject":
        new_status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="Invalid action.")
    await db.kyc_records.update_one({"user_id": user_id},
                                    {"$set": {"status": new_status, "rejection_reason": body.reason,
                                              "updated_at": now_iso()}})
    await db.users.update_one({"id": user_id}, {"$set": {"kyc_status": new_status, "updated_at": now_iso()}})
    await create_notification(user_id, "kyc",
                              "KYC verified" if new_status == "verified" else "KYC rejected",
                              "Your KYC has been verified." if new_status == "verified"
                              else f"Your KYC was rejected: {body.reason}",
                              "केवाईसी सत्यापित" if new_status == "verified" else "केवाईसी अस्वीकृत",
                              "आपकी केवाईसी सत्यापित हो गई है।" if new_status == "verified"
                              else f"आपकी केवाईसी अस्वीकृत: {body.reason}")
    await log_audit(admin, "kyc_reviewed", "kyc", user_id, new_value={"status": new_status}, request=request)
    return {"ok": True, "status": new_status}


# ---------------- Withdrawals review ----------------
@router.get("/withdrawals")
async def admin_withdrawals(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    rows = await db.withdrawal_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    ids = {r.get(k) for r in rows for k in ("approved_by", "paid_by", "rejected_by") if r.get(k)}
    names = {u["id"]: u.get("full_name") for u in await db.users.find({"id": {"$in": list(ids)}}, {"_id": 0, "id": 1, "full_name": 1}).to_list(len(ids) or 1)}
    for r in rows:
        for k in ("approved_by", "paid_by", "rejected_by"):
            if r.get(k):
                r[k + "_name"] = names.get(r[k])
    return rows


class WithdrawalReview(BaseModel):
    action: str  # approve / reject / mark_paid
    note: Optional[str] = ""
    payout_reference: Optional[str] = None   # required for mark_paid: the bank / UTR / processor reference the finance user supplies


# The business state REQUESTED is stored as "pending" (what POST /api/withdrawals creates). "under_review" is never created by any
# route; a legacy record in it is treated exactly as requested everywhere (review, dashboard count, finance report, screens).
REQUESTED_STATES = ("pending", "under_review")
PAYOUT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/#:\-]{2,63}$")


def _finalised():
    return HTTPException(status_code=400, detail="This withdrawal has already been finalised.")


@router.put("/withdrawals/{wd_id}")
async def review_withdrawal(wd_id: str, body: WithdrawalReview, request: Request, admin: dict = Depends(require_money_admin)):
    """Withdrawal review: super_admin / accounts_admin only. The workflow is REQUESTED -> APPROVED -> PAID, or -> REJECTED.

    approve   : requested -> approved; the approver and time are recorded (a legacy approval without an approver may be re-recorded).
    reject    : requested or approved -> rejected; the reservation returns to available.
    mark_paid : approved -> paid only, by a DIFFERENT finance user from the approver, with a payout reference that has not been
                used for another withdrawal. The money moves FIRST in one conditional wallet update that re-checks the wallet
                is still safe (available balance not negative, reservation still in pending) and records the operation key, so
                pay and reject exclude each other and neither applies twice. Then the status is claimed. A retry finishes it."""
    wr = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0})
    if not wr:
        raise HTTPException(status_code=404, detail="Withdrawal not found.")
    if body.action not in ("approve", "mark_paid", "reject"):
        raise HTTPException(status_code=400, detail="Invalid action.")
    settings = await get_settings()
    sym = settings.get("currency_symbol", "₹")
    now = now_iso()
    note = (body.note or "").strip()[:300]

    if body.action == "approve":
        if wr.get("status") == "approved" and wr.get("approved_by"):
            if wr["approved_by"] == admin["id"]:
                return {"ok": True, "status": "approved", "already": True}
            raise HTTPException(status_code=409, detail="This withdrawal was already approved by another finance user.")
        flt = {"id": wd_id, "$or": [{"status": {"$in": list(REQUESTED_STATES)}}, {"status": "approved", "approved_by": None}]}
        claimed = await db.withdrawal_requests.update_one(
            flt, {"$set": {"status": "approved", "approved_by": admin["id"], "approved_at": now, "admin_note": note, "updated_at": now}})
        if claimed.modified_count != 1:
            current = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0}) or {}
            if current.get("status") == "approved" and current.get("approved_by") == admin["id"]:
                return {"ok": True, "status": "approved", "already": True}
            if current.get("status") == "approved":
                raise HTTPException(status_code=409, detail="This withdrawal was already approved by another finance user.")
            raise _finalised()
        await log_audit(admin, "withdrawal_approved", "withdrawal", wd_id, old_value={"status": wr["status"]},
                        new_value={"status": "approved", "approved_by": admin["id"]}, request=request)
        await create_notification(wr["user_id"], "withdrawal", "Withdrawal approved",
                                  f"Your withdrawal of {sym}{int(wr['amount'])} is approved and will be paid.",
                                  "निकासी स्वीकृत", f"आपकी {sym}{int(wr['amount'])} की निकासी स्वीकृत हुई।")
        return {"ok": True, "status": "approved"}

    wd_p = paise_of(wr, "amount_paise", "amount")
    pay_op, reject_op = f"withdrawal_paid:{wd_id}", f"withdrawal_rejected:{wd_id}"
    my_op = pay_op if body.action == "mark_paid" else reject_op
    target = "paid" if body.action == "mark_paid" else "rejected"
    wallet = await db.wallets.find_one({"user_id": wr["user_id"]}, {"_id": 0, "applied_ops": 1}) or {}
    done = set(wallet.get("applied_ops") or [])
    if (pay_op in done or reject_op in done) and my_op not in done:
        raise _finalised()
    ref = None
    if my_op not in done:                                   # first attempt: every precondition is checked before money moves
        if body.action == "mark_paid":
            if wr.get("status") != "approved":
                raise HTTPException(status_code=409, detail="A withdrawal must be approved before it can be paid."
                                    if wr.get("status") in REQUESTED_STATES else "This withdrawal has already been finalised.")
            if not wr.get("approved_by"):
                raise HTTPException(status_code=409, detail="This approval predates approver records. Approve it again before paying.")
            if wr["approved_by"] == admin["id"]:
                raise HTTPException(status_code=403, detail="The finance user who approved this withdrawal cannot also pay it.")
            ref = (body.payout_reference or "").strip()
            if not PAYOUT_REF_RE.match(ref):
                raise HTTPException(status_code=422, detail="A payout reference (UTR / bank or processor reference, 3-64 characters: "
                                                            "letters, digits, space and . _ / # : -) is required to mark a withdrawal paid.")
            try:                                            # one reference, one withdrawal (the _id makes this race-safe)
                await db.withdrawal_payout_refs.insert_one({"_id": ref.upper(), "withdrawal_id": wd_id, "by": admin["id"], "at": now})
            except DuplicateKeyError:
                owner = await db.withdrawal_payout_refs.find_one({"_id": ref.upper()}) or {}
                if owner.get("withdrawal_id") != wd_id:
                    raise HTTPException(status_code=409, detail="This payout reference is already recorded for another withdrawal.")
            flt = {"available_balance_paise": {"$gte": 0}, "pending_balance_paise": {"$gte": wd_p}}
            inc = {"pending_balance_paise": -wd_p, "pending_balance": paise_to_float(-wd_p),
                   "total_withdrawn_paise": wd_p, "total_withdrawn": paise_to_float(wd_p)}
        else:
            if wr.get("status") not in REQUESTED_STATES + ("approved",):
                raise _finalised()
            flt = {"pending_balance_paise": {"$gte": wd_p}}
            inc = {"pending_balance_paise": -wd_p, "pending_balance": paise_to_float(-wd_p),
                   "available_balance_paise": wd_p, "available_balance": paise_to_float(wd_p)}
        moved = await db.wallets.update_one(
            {"user_id": wr["user_id"], "applied_ops": {"$nin": [pay_op, reject_op]}, **flt},
            {"$inc": inc, "$push": {"applied_ops": my_op}, "$set": {"updated_at": now}})
        if moved.modified_count != 1:
            wallet = await db.wallets.find_one({"user_id": wr["user_id"]}, {"_id": 0}) or {}
            ops = wallet.get("applied_ops") or []
            if my_op not in ops:
                if ref:
                    await db.withdrawal_payout_refs.delete_one({"_id": ref.upper(), "withdrawal_id": wd_id})   # nothing was paid
                if pay_op in ops or reject_op in ops:
                    raise _finalised()
                if body.action == "mark_paid":
                    raise HTTPException(status_code=409, detail=(
                        "This withdrawal cannot be paid: the HomeGenie's earnings were reversed after it was requested, so the "
                        f"wallet is not in a safe state (available {sym}{wallet.get('available_balance', 0)}). Reject it, or wait "
                        "until future earnings cover the shortfall."))
                raise HTTPException(status_code=409, detail="The withdrawal reservation is no longer in the wallet; finance must review it.")
    else:                                                   # a retry after the money already moved: just finish the record
        ref = (await db.withdrawal_payout_refs.find_one({"withdrawal_id": wd_id}) or {}).get("_id") if body.action == "mark_paid" else None
    from financial_ops import ensure_ledger
    await ensure_ledger({"id": new_id(), "user_id": wr["user_id"], "type": "WITHDRAWAL", "status": "PAID" if target == "paid" else "REJECTED",
                         "direction": "debit" if target == "paid" else "credit", "amount": paise_to_float(wd_p), "amount_paise": wd_p,
                         "reference": wd_id, "op_key": my_op, "created_by": admin["id"], "created_at": now,
                         "description": f"Withdrawal paid (ref {ref})" if target == "paid" else "Withdrawal rejected - amount returned"})
    sets = {"status": target, "admin_note": note, "updated_at": now}
    if target == "paid":
        stored_ref = (await db.withdrawal_payout_refs.find_one({"withdrawal_id": wd_id}) or {}).get("_id") or ref
        sets.update({"paid_by": admin["id"], "paid_at": now, "payout_reference": stored_ref})
        from_states = ["approved"]
    else:
        sets.update({"rejected_by": admin["id"], "rejected_at": now})
        from_states = list(REQUESTED_STATES) + ["approved"]
    claimed = await db.withdrawal_requests.update_one({"id": wd_id, "status": {"$in": from_states}}, {"$set": sets})
    if claimed.modified_count != 1:
        current = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0, "status": 1})
        if (current or {}).get("status") == target:
            return {"ok": True, "status": target, "already": True}          # a retry of a finished pay / reject
        raise _finalised()
    await create_notification(wr["user_id"], "withdrawal", f"Withdrawal {target}",
                              f"Your withdrawal of {sym}{int(wr['amount'])} is now {target}.",
                              f"निकासी {target}",
                              f"आपकी {sym}{int(wr['amount'])} की निकासी अब {target} है।")
    await log_audit(admin, f"withdrawal_{target}", "withdrawal", wd_id, old_value={"status": wr["status"]},
                    new_value={"status": target, **({"payout_reference": sets.get("payout_reference"), "approved_by": wr.get("approved_by")}
                                                     if target == "paid" else {})}, request=request)
    return {"ok": True, "status": target, **({"payout_reference": sets["payout_reference"]} if target == "paid" else {})}


# ---------------- Settings ----------------
@router.get("/settings")
async def admin_get_settings(admin: dict = Depends(require_admin)):
    return await get_settings()


class SettingsBody(BaseModel):
    commission_direct_pct: Optional[float] = None
    commission_referral_pct: Optional[float] = None
    commission_team_pct: Optional[float] = None
    return_window_days: Optional[int] = None
    point_value: Optional[float] = None
    points_withdrawal_enabled: Optional[bool] = None
    cod_enabled: Optional[bool] = None
    cod_fee: Optional[float] = None
    badge_t1_sales: Optional[float] = None
    badge_t2_sales: Optional[float] = None
    badge_t3_sales: Optional[float] = None
    badge_t4_sales: Optional[float] = None
    require_kyc_for_withdrawal: Optional[bool] = None
    gst_percent: Optional[float] = None
    company_name: Optional[str] = None
    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    company_address: Optional[str] = None


# Settings that change who is paid how much, when, or under which checks. Any admin may still edit the others.
MONEY_POLICY_SETTINGS = ("commission_direct_pct", "commission_referral_pct", "commission_team_pct", "return_window_days", "point_value",
                         "points_withdrawal_enabled", "cod_enabled", "cod_fee", "require_kyc_for_withdrawal", "gst_percent")
_PCT = ("commission_direct_pct", "commission_referral_pct", "commission_team_pct")


def _settings_problems(new: dict) -> list:
    """Technical validity only (no policy): finite, non-negative, percentages within 0-100 and the three commission rates
    together at most 100% of the base, whole days, a positive point value."""
    out = []
    for k, v in new.items():
        if isinstance(v, float) and not math.isfinite(v):
            out.append(f"{k} must be a finite number")
    for k in _PCT + ("gst_percent",):
        if new.get(k) is not None and not 0 <= new[k] <= 100:
            out.append(f"{k} must be between 0 and 100")
    if sum(float(new.get(k) or 0) for k in _PCT) > 100:
        out.append("the three commission percentages together cannot exceed 100")
    if new.get("return_window_days") is not None and not 0 <= new["return_window_days"] <= 365:
        out.append("return_window_days must be between 0 and 365")
    if new.get("point_value") is not None and not new["point_value"] > 0:
        out.append("point_value must be greater than 0")
    for k in ("cod_fee", "badge_t1_sales", "badge_t2_sales", "badge_t3_sales", "badge_t4_sales"):
        if new.get(k) is not None and new[k] < 0:
            out.append(f"{k} cannot be negative")
    return out


@router.put("/settings")
async def admin_update_settings(body: SettingsBody, request: Request, admin: dict = Depends(require_admin)):
    old = await get_settings()
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    changed_money = [k for k in MONEY_POLICY_SETTINGS if k in upd and upd[k] != old.get(k)]
    if changed_money and admin.get("role") not in MONEY_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only a finance administrator can change: " + ", ".join(changed_money) + ".")
    problems = _settings_problems({**{k: old.get(k) for k in _PCT}, **upd})
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    await db.business_settings.update_one({"id": "business_settings"}, {"$set": upd})
    await log_audit(admin, "settings_updated", "business_settings", "business_settings",
                    old_value=old, new_value=upd, request=request)
    return await get_settings()


@router.post("/referral-codes")
async def gen_referral_code(request: Request, admin: dict = Depends(require_admin)):
    code = "ANJ" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    doc = {"id": new_id(), "code": code, "active": True, "created_by": admin["id"],
           "created_by_name": admin.get("full_name"), "uses": 0, "created_at": now_iso()}
    await db.referral_codes.insert_one(dict(doc))
    doc.pop("_id", None)
    await log_audit(admin, "referral_code_generated", "referral_code", code, request=request)
    return doc


@router.get("/referral-codes")
async def list_referral_codes(admin: dict = Depends(require_admin)):
    return await db.referral_codes.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.delete("/referral-codes/{code}")
async def delete_referral_code(code: str, request: Request, admin: dict = Depends(require_admin)):
    rc = await db.referral_codes.find_one({"code": code})
    if not rc:
        raise HTTPException(status_code=404, detail="Reference code not found.")
    if rc.get("is_master"):
        raise HTTPException(status_code=400, detail="The master reference ID cannot be deleted.")
    await db.referral_codes.delete_one({"code": code})
    await log_audit(admin, "referral_code_deleted", "referral_code", code, request=request)
    return {"ok": True}


class ResetBody(BaseModel):
    confirm: str


@router.get("/registration-requests")
async def list_registration_requests(admin: dict = Depends(require_admin)):
    return await db.registration_requests.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", -1).to_list(500)


async def activate_registration(r: dict, approver: Optional[dict] = None) -> str:
    """Create the account for a registration request (idempotent) and mark the request approved.
    Used on registration itself (no admin approval needed for normal users), by the lazy/sweep activation of
    requests that were left pending, and by the admin Approve button. Never creates a second user for a mobile/email."""
    existing = await db.users.find_one({"$or": [{"mobile": r["mobile"]}] + ([{"email": r["email"]}] if r.get("email") else [])})
    if existing:
        did = existing.get("distributor_id")
    else:
        did = await next_distributor_id()
        user = {
            "id": new_id(), "distributor_id": did, "full_name": r["full_name"],
            "email": r.get("email") or None, "mobile": r["mobile"], "password_hash": r["password_hash"],
            "role": "distributor", "status": "red", "account_status": "active",
            "mobile_verified": False, "email_verified": bool(r.get("email_verified")),
            "google_linked": bool(r.get("google_linked")),
            "sponsor_id": r.get("sponsor_id") or None, "sponsor_user_id": None,
            "address": r.get("address", ""), "state": r.get("state", ""), "city": r.get("city", ""),
            "pincode": r.get("pincode", ""), "aadhaar_number": r.get("aadhaar_number", ""), "kyc_status": "not_started",
            "profile_complete": bool(r.get("email")), "created_at": now_iso(), "updated_at": now_iso(),
        }
        try:
            await db.users.insert_one(dict(user))
        except Exception:
            raise HTTPException(status_code=400, detail="Could not create distributor (possibly a duplicate email or mobile). Please check and try again.")
        await get_or_create_wallet(user["id"])
        # HOME GENIES: approval records the sponsor link only. No reward is paid.
        sp_did = r.get("sponsor_id")
        if sp_did:
            rc = await db.referral_codes.find_one({"code": sp_did, "active": True})
            if rc:
                sponsor = await db.users.find_one({"id": rc.get("created_by")}) or await db.users.find_one({"role": "super_admin"})
                parent_label = rc["code"]  # the referral code itself is the recorded parent
                await db.referral_codes.update_one({"code": sp_did}, {"$inc": {"uses": 1}})  # counted once, when the account is created
            else:
                sponsor = await db.users.find_one({"distributor_id": sp_did})
                parent_label = sp_did
            if sponsor:
                await db.users.update_one({"id": user["id"]},
                                          {"$set": {"sponsor_user_id": sponsor["id"], "sponsor_distributor_id": parent_label}})
                if not await db.referral_relationships.find_one({"referred_user_id": user["id"]}):
                    await db.referral_relationships.insert_one({
                        "id": new_id(), "sponsor_id": sponsor["id"],
                        "sponsor_distributor_id": parent_label,
                        "referred_user_id": user["id"], "referred_distributor_id": did,
                        "commission_paid": False, "created_at": now_iso(),
                    })
                # HOME GENIES: no reward is paid for a registration. Recruitment alone
                # never generates commission — only the sponsor link is recorded above.
    await db.registration_requests.update_one({"id": r["id"]},
        {"$set": {"status": "approved", "distributor_id": did, "approved_by": (approver or {}).get("id") or "auto",
                  "approved_at": now_iso()}})
    return did


async def activate_pending_registrations() -> int:
    """One-off, idempotent sweep: turn requests left 'pending' into accounts (no duplicates). Run at DB init."""
    n = 0
    async for r in db.registration_requests.find({"status": "pending"}):
        try:
            await activate_registration(r)
            n += 1
        except Exception:
            continue
    return n


@router.post("/registration-requests/{req_id}/approve")
async def approve_registration_request(req_id: str, request: Request, admin: dict = Depends(require_admin)):
    r = await db.registration_requests.find_one({"id": req_id})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    if r.get("status") == "approved":
        raise HTTPException(status_code=400, detail="This request is already approved.")
    if await db.users.find_one({"mobile": r["mobile"]}):
        raise HTTPException(status_code=400, detail="A user with this mobile already exists.")
    did = await activate_registration(r, admin)
    await log_audit(admin, "registration_approved", "user", did, new_value={"distributor_id": did}, request=request)
    return {"message": f"Approved. HomeGenie ID {did} created.", "distributor_id": did}


class RejectReqBody(BaseModel):
    reason: str = ""


@router.post("/registration-requests/{req_id}/reject")
async def reject_registration_request(req_id: str, request: Request, body: RejectReqBody = RejectReqBody(), admin: dict = Depends(require_admin)):
    r = await db.registration_requests.find_one({"id": req_id})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    if r.get("status") == "approved":
        # the account was already created at registration; rejecting the record would contradict the live account
        raise HTTPException(status_code=400, detail="This registration has already created an active account and cannot be rejected.")
    await db.registration_requests.update_one({"id": req_id},
        {"$set": {"status": "rejected", "rejection_reason": (body.reason or "").strip(),
                  "rejected_by": admin["id"], "rejected_at": now_iso()}})
    await log_audit(admin, "registration_rejected", "registration_request", req_id,
                    new_value={"reason": (body.reason or "").strip()}, request=request)
    return {"message": "Request rejected."}


class BlockBody(BaseModel):
    blocked: bool


@router.put("/users/{user_id}/block")
async def block_user(user_id: str, body: BlockBody, request: Request, admin: dict = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    await db.users.update_one({"id": user_id}, {"$set": {"blocked": body.blocked,
        "account_status": "blocked" if body.blocked else "active", "updated_at": now_iso()}})
    await log_audit(admin, "user_blocked" if body.blocked else "user_unblocked", "user", user_id, request=request)
    return {"ok": True, "blocked": body.blocked}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request, admin: dict = Depends(require_admin)):
    """DEACTIVATES the account; it never erases it. The user document, wallet, ledger, orders, commissions and audit
    references stay, so financial history is kept. The account is blocked and every existing session is refused.
    Repeated requests change nothing. Personal-data anonymisation is not performed: no retention policy is defined yet."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    if u.get("role") in {"super_admin", "admin", "accounts_admin", "support_admin"}:
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted.")
    if u.get("account_status") == "deleted":
        return {"ok": True, "already_deactivated": True}
    now = now_iso()
    await db.users.update_one({"id": user_id, "account_status": {"$ne": "deleted"}},
                              {"$set": {"account_status": "deleted", "blocked": True, "deleted_at": now,
                                        "deleted_by": admin["id"], "updated_at": now}})
    await log_audit(admin, "user_deactivated", "user", user_id,
                    old_value={"distributor_id": u.get("distributor_id"), "account_status": u.get("account_status")},
                    new_value={"account_status": "deleted"}, request=request)
    return {"ok": True, "deactivated": True}


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    aadhaar_number: Optional[str] = None


@router.put("/users/{user_id}")
async def admin_update_user(user_id: str, body: AdminUserUpdate, request: Request, admin: dict = Depends(require_admin)):
    """Admin completes/corrects a distributor's profile."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    upd = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if "email" in upd:
        upd["email"] = upd["email"].lower() or None
    try:
        await db.users.update_one({"id": user_id}, {"$set": {**upd, "updated_at": now_iso()}})
    except Exception:
        raise HTTPException(status_code=400, detail="Could not update (email or mobile may already be in use).")
    await log_audit(admin, "user_profile_updated", "user", user_id, new_value=list(upd.keys()), request=request)
    updated = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if updated.get("aadhaar_number"):
        updated["aadhaar_masked"] = mask_aadhaar(updated["aadhaar_number"])
        updated.pop("aadhaar_number", None)
    return updated


class WalletCreditBody(BaseModel):
    distributor_id: str
    amount: float = Field(gt=0, le=10_000_000, allow_inf_nan=False)       # technical bound against typing errors, not a policy limit
    reason: str
    request_id: str                                                         # idempotency key: a retry or double click credits once

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: float) -> float:
        exponent = Decimal(str(v)).as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError("amount can have at most 2 decimal places")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if not 5 <= len(v) <= 300:
            raise ValueError("reason must be 5 to 300 characters")
        return v

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", v):
            raise ValueError("request_id must be 8-64 characters: letters, digits, _ and -")
        return v


@router.post("/wallet/credit")
async def admin_wallet_credit(body: WalletCreditBody, request: Request, admin: dict = Depends(require_money_admin)):
    """Manual points credit. Finance administrators only; exact amount, mandatory reason and idempotency key; one ledger row and
    one wallet move per key (the same pattern as commission release); audited. A repeated key returns the original credit."""
    did = (body.distributor_id or "").strip().upper()
    u = await db.users.find_one({"distributor_id": did})
    if not u:
        raise HTTPException(status_code=404, detail=f"Distributor {did} not found.")
    paise = to_paise(body.amount)
    op = f"admin_credit:{body.request_id}"
    existing = await db.wallet_transactions.find_one({"op_key": op}, {"_id": 0})
    if existing:
        if existing.get("user_id") != u["id"] or existing.get("amount_paise") != paise:
            raise HTTPException(status_code=409, detail="This request_id was already used for a different credit.")
        return {"message": "This credit was already applied.", "already": True, "distributor_id": did, "amount": paise_to_float(paise)}
    from financial_ops import ensure_ledger, move_wallet_once
    await ensure_ledger({"id": new_id(), "user_id": u["id"], "type": "MANUAL_ADMIN_CREDIT", "direction": "credit", "status": "CREDITED",
                         "amount": paise_to_float(paise), "amount_paise": paise, "reference": f"admin:{admin.get('distributor_id', '')}",
                         "description": body.reason, "op_key": op, "created_by": admin["id"], "created_at": now_iso()})
    moved = await move_wallet_once(u["id"], {"available_balance": paise, "total_earned": paise}, op)
    if moved:
        await create_notification(u["id"], "wallet", f"₹{int(paise // 100)} credited",
                                  f"{body.reason} — ₹{paise_to_float(paise)} added to your wallet.",
                                  f"₹{int(paise // 100)} क्रेडिट हुआ", f"{body.reason} — ₹{paise_to_float(paise)} आपके वॉलेट में जोड़े गए।")
        await log_audit(admin, "admin_wallet_credit", "user", u["id"],
                        new_value={"distributor_id": did, "amount_paise": paise, "reason": body.reason, "request_id": body.request_id}, request=request)
    from core import get_or_create_wallet
    w = await get_or_create_wallet(u["id"])
    return {"message": f"₹{paise_to_float(paise)} credited to {did}.", "distributor_id": did, "amount": paise_to_float(paise),
            "available_balance": round(float((w or {}).get("available_balance", 0)), 2)}


class AdminPwBody(BaseModel):
    password: Optional[str] = None


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, body: AdminPwBody, request: Request, admin: dict = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    # Generated default: 12 random chars (letters + digits), not a guessable prefix + 5 digits.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    new_pw = (body.password or "").strip() or ("".join(secrets.choice(alphabet) for _ in range(12)))
    if len(new_pw) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    # Changing the password also signs the user out everywhere (older sessions are revoked).
    await db.users.update_one({"id": user_id}, {"$set": {**password_update(new_pw), "updated_at": now_iso()}})
    await db.password_reset_requests.update_many({"user_id": user_id, "status": "pending"},
        {"$set": {"status": "resolved", "resolved_by": admin["id"], "resolved_at": now_iso()}})
    await log_audit(admin, "admin_reset_password", "user", user_id, request=request)
    return {"message": "Password reset successfully.", "password": new_pw,
            "distributor_id": u.get("distributor_id"), "email": u.get("email"), "full_name": u.get("full_name")}


@router.get("/password-reset-requests")
async def list_password_reset_requests(admin: dict = Depends(require_admin)):
    return await db.password_reset_requests.find({"status": "pending"}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/password-reset-requests/{req_id}/dismiss")
async def dismiss_password_reset_request(req_id: str, request: Request, admin: dict = Depends(require_admin)):
    await db.password_reset_requests.update_one({"id": req_id},
        {"$set": {"status": "dismissed", "resolved_by": admin["id"], "resolved_at": now_iso()}})
    return {"ok": True}


# ---------------- Audit logs ----------------
@router.get("/audit-logs")
async def admin_audit(admin: dict = Depends(require_admin)):
    return await db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.delete("/audit-logs")
async def clear_audit_logs(request: Request, admin: dict = Depends(require_admin)):
    """SUPER ADMIN only: permanently clears audit history and records one
    immutable system event noting the deletion."""
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can delete audit logs.")
    count = (await db.audit_logs.delete_many({})).deleted_count
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
    await db.audit_logs.insert_one({
        "id": new_id(), "user_id": None, "user_email": "system",
        "action": "audit_logs_cleared", "entity": "system", "entity_id": "audit_logs",
        "old_value": {"deleted_count": count}, "new_value": None,
        "protected": True, "ip": ip, "created_at": now_iso(),
    })
    return {"ok": True, "deleted": count}


# ---------------- Reports ----------------
REPORTS = {
    "registrations": ("users", {"role": {"$in": ["distributor", "customer", "vendor"]}},
                      ["distributor_id", "full_name", "email", "mobile", "status", "state", "city", "created_at"]),
    "sales": ("orders", {"payment_status": "paid"},
              ["order_number", "distributor_id", "subtotal", "gst_amount", "total", "status", "created_at"]),
    "orders": ("orders", {}, ["order_number", "distributor_id", "total", "status", "payment_status", "created_at"]),
    "payments": ("payment_transactions", {}, ["session_id", "order_id", "amount", "currency", "payment_status", "created_at"]),
    "referrals": ("referral_relationships", {},
                  ["sponsor_distributor_id", "referred_distributor_id", "commission_paid", "created_at"]),
    "commissions": ("commissions", {}, ["sponsor_distributor_id", "referred_distributor_id", "type", "amount", "status", "created_at"]),
    "wallet": ("wallet_transactions", {}, ["user_id", "type", "direction", "amount", "status", "created_at"]),
    "withdrawals": ("withdrawal_requests", {}, ["request_number", "distributor_id", "amount", "status", "created_at"]),
}


@router.get("/reports/{report}")
async def get_report(report: str, admin: dict = Depends(require_admin)):
    if report not in REPORTS:
        raise HTTPException(status_code=404, detail="Report not found.")
    coll, q, fields = REPORTS[report]
    rows = await db[coll].find(q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    return {"report": report, "fields": fields, "rows": rows, "count": len(rows)}


@router.get("/reports/{report}/export")
async def export_report(report: str, admin: dict = Depends(require_admin)):
    if report not in REPORTS:
        raise HTTPException(status_code=404, detail="Report not found.")
    coll, q, fields = REPORTS[report]
    rows = await db[coll].find(q, {"_id": 0}).sort("created_at", -1).to_list(5000)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({f: r.get(f, "") for f in fields})
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f"attachment; filename={report}_report.csv"})
