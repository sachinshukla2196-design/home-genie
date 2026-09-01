"""Admin panel routes: dashboard, users, products, orders, KYC, withdrawals,
commissions, activations, settings, audit logs, reports (with CSV export)."""
import io
import csv
import secrets
from core import hash_password, next_distributor_id, get_or_create_wallet
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from core import (db, now_iso, new_id, require_admin, get_settings,
                  add_wallet_transaction, create_notification, log_audit,
                  clean_user, mask_aadhaar)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------- Dashboard ----------------
@router.get("/dashboard")
async def admin_dashboard(admin: dict = Depends(require_admin)):
    settings = await get_settings()
    today = datetime.now(timezone.utc).date().isoformat()

    total_users = await db.users.count_documents({"role": {"$in": ["distributor", "customer"]}})
    red_users = await db.users.count_documents({"status": "red"})
    green_users = await db.users.count_documents({"status": "green"})
    pending_kyc = await db.kyc_records.count_documents({"status": "pending"})
    pending_wd = await db.withdrawal_requests.count_documents({"status": {"$in": ["pending", "under_review"]}})

    def today_q(field="created_at"):
        return {field: {"$regex": f"^{today}"}}

    today_regs = await db.users.count_documents({"created_at": {"$regex": f"^{today}"}})
    today_acts = await db.activation_records.count_documents({"created_at": {"$regex": f"^{today}"}})
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
    category: str = "General"
    is_active: bool = True
    is_activation_product: bool = False


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
    return await db.orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)


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
    await db.orders.update_one({"id": order_id}, {"$set": {"status": body.status, "updated_at": now_iso()}})
    await create_notification(o["user_id"], "order", "Order update",
                              f"Your order {o['order_number']} is now {body.status}.",
                              "ऑर्डर अपडेट", f"आपका ऑर्डर {o['order_number']} अब {body.status} है।")
    await log_audit(admin, "order_status_changed", "order", order_id,
                    old_value={"status": o["status"]}, new_value={"status": body.status}, request=request)
    return {"ok": True}


# ---------------- Payments ----------------
@router.get("/payments")
async def admin_payments(admin: dict = Depends(require_admin)):
    return await db.payment_transactions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


# ---------------- Activations / Referrals / Commissions ----------------
@router.get("/activations")
async def admin_activations(admin: dict = Depends(require_admin)):
    return await db.activation_records.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.get("/referrals")
async def admin_referrals(admin: dict = Depends(require_admin)):
    return await db.referral_relationships.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.get("/commissions")
async def admin_commissions(admin: dict = Depends(require_admin)):
    return await db.commissions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


# ---------------- KYC review ----------------
@router.get("/kyc")
async def admin_kyc(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    recs = await db.kyc_records.find(q, {"_id": 0}).sort("submitted_at", -1).to_list(1000)
    return recs


class KycReview(BaseModel):
    action: str  # verify / reject
    reason: Optional[str] = ""


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
    if body.action == "approve":
        new_status = "approved"
    elif body.action == "mark_paid":
        new_status = "paid"
        # clear pending balance
        await db.wallets.update_one({"user_id": wr["user_id"]},
                                    {"$inc": {"pending_balance": -wr["amount"]},
                                     "$set": {"updated_at": now_iso()}})
        await add_wallet_transaction(wr["user_id"], "WITHDRAWAL", wr["amount"], "REVERSED",
                                     description="Withdrawal paid", direction="debit")
    elif body.action == "reject":
        new_status = "rejected"
        # refund held amount back to available
        await db.wallets.update_one({"user_id": wr["user_id"]},
                                    {"$inc": {"available_balance": wr["amount"], "pending_balance": -wr["amount"]},
                                     "$set": {"updated_at": now_iso()}})
        await add_wallet_transaction(wr["user_id"], "ADJUSTMENT", wr["amount"], "CREDITED",
                                     description="Withdrawal rejected - amount refunded", direction="credit")
    else:
        raise HTTPException(status_code=400, detail="Invalid action.")

    await db.withdrawal_requests.update_one({"id": wd_id},
                                            {"$set": {"status": new_status, "admin_note": body.note,
                                                      "updated_at": now_iso()}})
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
    activation_amount: Optional[float] = None
    activation_product_sku: Optional[str] = None
    referral_commission: Optional[float] = None
    withdrawal_minimum: Optional[float] = None
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


class ResetBody(BaseModel):
    confirm: str


@router.post("/maintenance/reset-data")
async def reset_data(body: ResetBody, request: Request, admin: dict = Depends(require_admin)):
    """DANGER: wipes all non-admin data (users, orders, payments, wallets, referrals...). Keeps admins, products, settings."""
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can reset data.")
    if body.confirm != "RESET":
        raise HTTPException(status_code=400, detail="Type RESET to confirm.")
    admin_roles = {"super_admin", "admin", "accounts_admin", "support_admin"}
    result = {"users": (await db.users.delete_many({"role": {"$nin": list(admin_roles)}})).deleted_count}
    for coll in ["orders", "payment_transactions", "commissions", "wallets", "wallet_transactions",
                 "referral_relationships", "activation_records", "withdrawal_requests",
                 "kyc_records", "notifications", "otp_sessions", "referral_codes", "login_attempts",
                 "registration_requests"]:
        result[coll] = (await db[coll].delete_many({})).deleted_count
    await log_audit(admin, "data_reset", "system", "all", new_value=result, request=request)
    return {"message": "All non-admin data cleared. Admins, products and settings preserved.", "deleted": result}


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
        "activation_status": "inactive",
        "mobile_verified": False, "email_verified": False,
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
    # Save the referral relationship permanently. Phase 1: NO commission is paid
    # here — the ₹100 direct referral is credited in Phase 2 on GREEN activation.
    sp_did = r.get("sponsor_id")
    if sp_did:
        sponsor = await db.users.find_one({"distributor_id": sp_did})
        if sponsor:
            await db.users.update_one({"id": user["id"]}, {"$set": {"sponsor_user_id": sponsor["id"]}})
            if not await db.referral_relationships.find_one({"referred_user_id": user["id"]}):
                await db.referral_relationships.insert_one({
                    "id": new_id(), "sponsor_id": sponsor["id"],
                    "sponsor_distributor_id": sponsor.get("distributor_id"),
                    "referred_user_id": user["id"], "referred_distributor_id": did,
                    "commission_paid": False, "created_at": now_iso(),
                })
    await db.registration_requests.update_one({"id": req_id},
        {"$set": {"status": "approved", "distributor_id": did, "approved_by": admin["id"], "approved_at": now_iso()}})
    await log_audit(admin, "registration_approved", "user", user["id"], new_value={"distributor_id": did}, request=request)
    return {"message": f"Approved. Distributor ID {did} created (RED, active).", "distributor_id": did}


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
    await log_audit(admin, "admin_reset_password", "user", user_id, request=request)
    return {"message": "Password reset successfully.", "password": new_pw,
            "distributor_id": u.get("distributor_id"), "email": u.get("email"), "full_name": u.get("full_name")}


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
        "id": new_id(), "user_id": admin.get("id"), "user_email": admin.get("email"),
        "action": "audit_logs_cleared", "entity": "system", "entity_id": "audit_logs",
        "old_value": {"deleted_count": count}, "new_value": None,
        "protected": True, "ip": ip, "created_at": now_iso(),
    })
    return {"ok": True, "deleted": count}


# ---------------- Reports ----------------
REPORTS = {
    "registrations": ("users", {"role": {"$in": ["distributor", "customer"]}},
                      ["distributor_id", "full_name", "email", "mobile", "status", "state", "city", "created_at"]),
    "activations": ("activation_records", {}, ["distributor_id", "order_id", "amount", "status", "activation_date"]),
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
