"""Admin panel routes: dashboard, users, products, orders, KYC, withdrawals,
commissions, settings, audit logs, reports (with CSV export)."""
import io
import csv
import math
import re
import secrets
from core import hash_password, next_distributor_id, get_or_create_wallet
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, FileResponse
import os as _os
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from core import (db, now_iso, new_id, require_admin, get_settings,
                  add_wallet_transaction, create_notification, log_audit,
                  clean_user, mask_aadhaar)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/final-report.pdf")
async def final_report_pdf(admin: dict = Depends(require_admin)):
    path = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "FINAL_APPLICATION_REPORT.pdf")
    if not _os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(path, media_type="application/pdf", filename="HOME_GENIES_Report.pdf")


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

    total_users = await db.users.count_documents({"role": {"$in": ["distributor", "customer"]}})
    red_users = await db.users.count_documents({"status": "red", "role": {"$in": ["distributor", "customer"]}})
    green_users = await db.users.count_documents({"status": "green", "role": {"$in": ["distributor", "customer"]}})
    pending_kyc = await db.kyc_records.count_documents({"status": "pending"})
    pending_wd = await db.withdrawal_requests.count_documents({"status": {"$in": ["pending", "under_review"]}})

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
    q = {"role": {"$in": ["distributor", "customer"]}}
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
    wallet = await db.wallets.find_one({"user_id": user_id}, {"_id": 0})
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
    existing = await db.products.find_one({"id": product_id}, {"_id": 0})
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
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
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
    await db.orders.update_one({"id": order_id}, {"$set": {"status": body.status, "updated_at": now_iso()}})
    # NOTE: 'cancelled' on a PAID order does NOT reverse commissions by itself — only a confirmed
    # payment return (Refund action) does. Unpaid cancelled orders never generated commissions.
    await create_notification(o["user_id"], "order", "Order update",
                              f"Your order {o['order_number']} is now {body.status}.",
                              "ऑर्डर अपडेट", f"आपका ऑर्डर {o['order_number']} अब {body.status} है।")
    await log_audit(admin, "order_status_changed", "order", order_id,
                    old_value={"status": o["status"]}, new_value={"status": body.status}, request=request)
    return {"ok": True}


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
    remaining = round(float(o.get("total") or 0) - float(o.get("refunded_amount") or 0), 2)
    if body.amount is not None and (body.amount <= 0 or round(body.amount, 2) > remaining):
        raise HTTPException(status_code=400, detail=f"Refund amount must be between 0 and ₹{remaining}.")
    import shop_routes
    res = await shop_routes.reverse_order_financials(order_id, admin, request, refund_amount=body.amount, reference=ref, reason=body.reason)
    if res.get("duplicate"):
        raise HTTPException(status_code=409, detail="A refund with this reference was already recorded for this order.")
    new_status = "cancelled" if body.cancel_order else ("refunded" if res["refund_amount"] >= remaining - 0.005 else o.get("status"))
    await db.orders.update_one({"id": order_id}, {"$set": {"status": new_status, "updated_at": now_iso()}})
    await create_notification(o["user_id"], "order", "Refund processed",
                              f"₹{res['refund_amount']:g} refunded on order {o['order_number']} (ref {ref}).",
                              "रिफंड हो गया", f"ऑर्डर {o['order_number']} पर ₹{res['refund_amount']:g} रिफंड हुआ।")
    return {"ok": True, **res, "status": new_status}


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


@router.put("/commissions/{commission_id}/status")
async def commission_status(commission_id: str, body: CommissionActionBody, request: Request, admin: dict = Depends(require_admin)):
    c = await db.commissions.find_one({"id": commission_id})
    if not c:
        raise HTTPException(status_code=404, detail="Commission not found.")
    if body.action == "release":
        if c.get("status") == "RELEASED":
            raise HTTPException(status_code=400, detail="This commission is already released.")
        await db.commissions.update_one({"id": commission_id},
            {"$set": {"status": "RELEASED", "released_at": now_iso(), "released_by": admin["id"]}})
        await log_audit(admin, "commission_released", "commission", commission_id,
                        old_value={"status": c.get("status")}, new_value={"status": "RELEASED"}, request=request)
        return {"ok": True, "status": "RELEASED"}
    if body.action == "hold":
        await db.commissions.update_one({"id": commission_id},
            {"$set": {"status": "HELD", "held_at": now_iso(), "held_by": admin["id"]}})
        await log_audit(admin, "commission_held", "commission", commission_id,
                        old_value={"status": c.get("status")}, new_value={"status": "HELD"}, request=request)
        return {"ok": True, "status": "HELD"}
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
    return await db.withdrawal_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)


class WithdrawalReview(BaseModel):
    action: str  # approve / reject / mark_paid
    note: Optional[str] = ""


@router.put("/withdrawals/{wd_id}")
async def review_withdrawal(wd_id: str, body: WithdrawalReview, request: Request, admin: dict = Depends(require_admin)):
    wr = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0})
    if not wr:
        raise HTTPException(status_code=404, detail="Withdrawal not found.")
    settings = await get_settings()
    sym = settings.get("currency_symbol", "₹")

    new_status = None
    if body.action not in ("approve", "mark_paid", "reject"):
        raise HTTPException(status_code=400, detail="Invalid action.")
    target = {"approve": "approved", "mark_paid": "paid", "reject": "rejected"}[body.action]
    # Atomically claim the transition from a non-terminal state — makes the review
    # idempotent so a double approve/pay/reject can never double-modify the wallet.
    claimed = await db.withdrawal_requests.update_one(
        {"id": wd_id, "status": {"$in": ["pending", "under_review", "approved"]}},
        {"$set": {"status": target, "admin_note": body.note, "updated_at": now_iso()}})
    if claimed.modified_count != 1:
        raise HTTPException(status_code=400, detail="This withdrawal has already been finalised.")
    new_status = target
    if body.action == "mark_paid":
        # settle: clear the held pending amount and record it as withdrawn
        await db.wallets.update_one({"user_id": wr["user_id"]},
                                    {"$inc": {"pending_balance": -wr["amount"], "total_withdrawn": wr["amount"]},
                                     "$set": {"updated_at": now_iso()}})
        await add_wallet_transaction(wr["user_id"], "WITHDRAWAL", wr["amount"], "PAID",
                                     description="Withdrawal paid", direction="debit")
    elif body.action == "reject":
        # return the held amount to available balance
        await db.wallets.update_one({"user_id": wr["user_id"]},
                                    {"$inc": {"available_balance": wr["amount"], "pending_balance": -wr["amount"]},
                                     "$set": {"updated_at": now_iso()}})
        await add_wallet_transaction(wr["user_id"], "WITHDRAWAL", wr["amount"], "REJECTED",
                                     description="Withdrawal rejected - amount returned", direction="credit")

    await create_notification(wr["user_id"], "withdrawal", f"Withdrawal {new_status}",
                              f"Your withdrawal of {sym}{int(wr['amount'])} is now {new_status}.",
                              f"निकासी {new_status}",
                              f"आपकी {sym}{int(wr['amount'])} की निकासी अब {new_status} है।")
    await log_audit(admin, "withdrawal_reviewed", "withdrawal", wd_id,
                    old_value={"status": wr["status"]}, new_value={"status": new_status}, request=request)
    return {"ok": True, "status": new_status}


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
    require_kyc_for_withdrawal: Optional[bool] = None
    gst_percent: Optional[float] = None
    company_name: Optional[str] = None
    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    company_address: Optional[str] = None


@router.put("/settings")
async def admin_update_settings(body: SettingsBody, request: Request, admin: dict = Depends(require_admin)):
    old = await get_settings()
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
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


@router.post("/registration-requests/{req_id}/approve")
async def approve_registration_request(req_id: str, request: Request, admin: dict = Depends(require_admin)):
    r = await db.registration_requests.find_one({"id": req_id})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    if r.get("status") == "approved":
        raise HTTPException(status_code=400, detail="This request is already approved.")
    if await db.users.find_one({"mobile": r["mobile"]}):
        raise HTTPException(status_code=400, detail="A user with this mobile already exists.")
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
    await db.registration_requests.update_one({"id": req_id},
        {"$set": {"status": "approved", "distributor_id": did, "approved_by": admin["id"], "approved_at": now_iso()}})
    await log_audit(admin, "registration_approved", "user", user["id"], new_value={"distributor_id": did}, request=request)
    return {"message": f"Approved. HomeGenie ID {did} created.", "distributor_id": did}


class RejectReqBody(BaseModel):
    reason: str = ""


@router.post("/registration-requests/{req_id}/reject")
async def reject_registration_request(req_id: str, request: Request, body: RejectReqBody = RejectReqBody(), admin: dict = Depends(require_admin)):
    r = await db.registration_requests.find_one({"id": req_id})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
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
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    if u.get("role") in {"super_admin", "admin", "accounts_admin", "support_admin"}:
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted.")
    await db.users.delete_one({"id": user_id})
    await db.wallets.delete_many({"user_id": user_id})
    await log_audit(admin, "user_deleted", "user", user_id,
                    old_value={"distributor_id": u.get("distributor_id"), "name": u.get("full_name")}, request=request)
    return {"ok": True}


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
    amount: float
    reason: Optional[str] = None


@router.post("/wallet/credit")
async def admin_wallet_credit(body: WalletCreditBody, request: Request, admin: dict = Depends(require_admin)):
    did = (body.distributor_id or "").strip().upper()
    u = await db.users.find_one({"distributor_id": did})
    if not u:
        raise HTTPException(status_code=404, detail=f"Distributor {did} not found.")
    amt = round(float(body.amount or 0), 2)
    if amt <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than 0.")
    reason = (body.reason or "").strip() or "Manual admin credit"
    await add_wallet_transaction(u["id"], "MANUAL_ADMIN_CREDIT", amt, "CREDITED",
                                 reference=f"admin:{admin.get('distributor_id', '')}",
                                 direction="credit", description=reason)
    await create_notification(u["id"], "wallet", f"₹{int(amt)} credited",
                              f"{reason} — ₹{amt} added to your wallet.",
                              f"₹{int(amt)} क्रेडिट हुआ", f"{reason} — ₹{amt} आपके वॉलेट में जोड़े गए।")
    await log_audit(admin, "admin_wallet_credit", "user", u["id"],
                    new_value={"distributor_id": did, "amount": amt, "reason": reason}, request=request)
    w = await db.wallets.find_one({"user_id": u["id"]}, {"_id": 0, "available_balance": 1})
    return {"message": f"₹{amt} credited to {did}.", "distributor_id": did, "amount": amt,
            "available_balance": round(float((w or {}).get("available_balance", 0)), 2)}


class AdminPwBody(BaseModel):
    password: Optional[str] = None


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, body: AdminPwBody, request: Request, admin: dict = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    new_pw = (body.password or "").strip() or ("Anj" + "".join(secrets.choice("23456789") for _ in range(5)))
    if len(new_pw) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    await db.users.update_one({"id": user_id}, {"$set": {"password_hash": hash_password(new_pw), "updated_at": now_iso()}})
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
    "registrations": ("users", {"role": {"$in": ["distributor", "customer"]}},
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
