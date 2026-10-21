"""HomeGenie Points wallet, sharing links, identity records, withdrawals, notifications, dashboard."""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone, timedelta

from core import (db, now_iso, new_id, get_current_user, get_settings, get_or_create_wallet,
                  add_wallet_transaction, create_notification, log_audit)

router = APIRouter(prefix="/api", tags=["homegenie"])


def _mask(val: str, keep: int = 4) -> str:
    if not val:
        return ""
    val = str(val)
    if len(val) <= keep:
        return "*" * len(val)
    return "*" * (len(val) - keep) + val[-keep:]


# ---------------- Wallet ----------------
@router.get("/wallet")
async def get_wallet(user: dict = Depends(get_current_user)):
    w = await get_or_create_wallet(user["id"])
    w.pop("_id", None)
    return w


@router.get("/wallet/transactions")
async def wallet_txns(user: dict = Depends(get_current_user)):
    return await db.wallet_transactions.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(300)


# ---------------- Referral ----------------
@router.get("/referral")
async def referral_info(user: dict = Depends(get_current_user)):
    settings = await get_settings()
    count = await db.referral_relationships.count_documents({"sponsor_id": user["id"]})
    active = await db.users.count_documents({"sponsor_user_id": user["id"], "status": "green"})
    return {
        "distributor_id": user.get("distributor_id"),
        "referral_code": user.get("distributor_id"),
        "eligible": user.get("status") == "green",
        "direct_pct": settings.get("commission_direct_pct", 30.0),
        "total_referrals": count,
        "active_referrals": active,
    }




class KycBody(BaseModel):
    pan: str
    aadhaar: str
    account_holder_name: str
    bank_account: str
    ifsc: str
    bank_name: str = ""


@router.get("/kyc")
async def get_kyc(user: dict = Depends(get_current_user)):
    k = await db.kyc_records.find_one({"user_id": user["id"]}, {"_id": 0})
    if not k:
        return {"status": "not_started"}
    return {
        "status": k["status"],
        "pan": _mask(k.get("pan"), 4),
        "aadhaar": _mask(k.get("aadhaar"), 4),
        "account_holder_name": k.get("account_holder_name"),
        "bank_account": _mask(k.get("bank_account"), 4),
        "ifsc": k.get("ifsc"),
        "bank_name": k.get("bank_name"),
        "rejection_reason": k.get("rejection_reason"),
        "submitted_at": k.get("submitted_at"),
    }


@router.post("/kyc")
async def submit_kyc(body: KycBody, request: Request, user: dict = Depends(get_current_user)):
    pan = body.pan.strip().upper()
    if len(pan) != 10:
        raise HTTPException(status_code=400, detail="Enter a valid 10-character PAN.")
    if len(body.aadhaar.strip().replace(" ", "")) != 12:
        raise HTTPException(status_code=400, detail="Enter a valid 12-digit Aadhaar number.")
    rec = {
        "user_id": user["id"], "distributor_id": user.get("distributor_id"),
        "pan": pan, "aadhaar": body.aadhaar.strip().replace(" ", ""),
        "aadhaar_verified": False,
        "account_holder_name": body.account_holder_name.strip(),
        "bank_account": body.bank_account.strip(), "ifsc": body.ifsc.strip().upper(),
        "bank_name": body.bank_name.strip(),
        "status": "pending", "rejection_reason": None,
        "submitted_at": now_iso(), "updated_at": now_iso(),
    }
    existing = await db.kyc_records.find_one({"user_id": user["id"]})
    if existing:
        rec["id"] = existing.get("id", new_id())
        await db.kyc_records.update_one({"user_id": user["id"]}, {"$set": rec})
    else:
        rec["id"] = new_id()
        rec["created_at"] = now_iso()
        await db.kyc_records.insert_one(dict(rec))
    await db.users.update_one({"id": user["id"]}, {"$set": {"kyc_status": "pending", "updated_at": now_iso()}})
    await create_notification(user["id"], "kyc", "KYC submitted",
                              "Your KYC has been submitted and is under review.",
                              "केवाईसी जमा हुई", "आपकी केवाईसी समीक्षा हेतु जमा कर दी गई है।")
    await log_audit(user, "kyc_submitted", "kyc", user["id"], request=request)
    return {"status": "pending", "message": "KYC submitted for review."}


# ---------------- Withdrawals ----------------
class WithdrawBody(BaseModel):
    amount: float = Field(gt=0)


@router.get("/withdrawals")
async def my_withdrawals(user: dict = Depends(get_current_user)):
    return await db.withdrawal_requests.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.post("/withdrawals")
async def request_withdrawal(body: WithdrawBody, request: Request, user: dict = Depends(get_current_user)):
    if user.get("status") != "green":
        raise HTTPException(status_code=403, detail="Your HomeGenie selling role must be approved before you can withdraw points.")
    settings = await get_settings()
    if not settings.get("points_withdrawal_enabled", True):
        raise HTTPException(status_code=400, detail="Point withdrawal is not enabled yet.")
    # No minimum withdrawal amount - any amount within the available balance may be requested.
    if settings.get("require_kyc_for_withdrawal", True):
        kyc = await db.kyc_records.find_one({"user_id": user["id"]})
        if not kyc or kyc.get("status") != "verified":
            raise HTTPException(status_code=400, detail="Verify your identity and bank details before withdrawing points.")
    await get_or_create_wallet(user["id"])
    # Atomic conditional debit: only succeeds if available_balance >= amount.
    moved = await db.wallets.update_one(
        {"user_id": user["id"], "available_balance": {"$gte": body.amount}},
        {"$inc": {"available_balance": -body.amount, "pending_balance": body.amount},
         "$set": {"updated_at": now_iso()}})
    if moved.modified_count != 1:
        raise HTTPException(status_code=400, detail="Insufficient available balance.")
    # informational ledger entry (aggregates already moved atomically above)
    await add_wallet_transaction(user["id"], "WITHDRAWAL", body.amount, "HELD",
                                 description="Withdrawal request (held)", direction="debit")
    req_no = new_id()[:8].upper()
    wr = {
        "id": new_id(), "request_number": f"WD{req_no}", "user_id": user["id"],
        "distributor_id": user.get("distributor_id"), "amount": body.amount,
        "status": "pending", "admin_note": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.withdrawal_requests.insert_one(dict(wr))
    await create_notification(user["id"], "withdrawal", "Withdrawal requested",
                              f"Your withdrawal of {settings.get('currency_symbol','₹')}{int(body.amount)} is pending review.",
                              "निकासी अनुरोध",
                              f"आपकी {settings.get('currency_symbol','₹')}{int(body.amount)} की निकासी समीक्षाधीन है।")
    await log_audit(user, "withdrawal_requested", "withdrawal", wr["id"],
                    new_value={"amount": body.amount}, request=request)
    wr.pop("_id", None)
    return wr


# ---------------- Notifications ----------------
@router.get("/notifications")
async def notifications(user: dict = Depends(get_current_user)):
    items = await db.notifications.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(100)
    unread = sum(1 for n in items if not n.get("read"))
    return {"items": items, "unread": unread}


@router.post("/notifications/{nid}/read")
async def mark_read(nid: str, user: dict = Depends(get_current_user)):
    await db.notifications.update_one({"id": nid, "user_id": user["id"]}, {"$set": {"read": True}})
    return {"ok": True}


@router.post("/notifications/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    await db.notifications.update_many({"user_id": user["id"]}, {"$set": {"read": True}})
    return {"ok": True}


# ---------------- Dashboard ----------------
@router.get("/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    settings = await get_settings()
    wallet = await get_or_create_wallet(user["id"])
    total_orders = await db.orders.count_documents({"user_id": user["id"]})
    recent_orders = await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)

    today = datetime.now(timezone.utc).date().isoformat()
    today_income = 0.0
    total_income = wallet["total_earned"]
    commissions = await db.commissions.find(
        {"user_id": user["id"], "status": {"$in": ["PENDING", "RELEASED", "PARTIALLY_REVERSED"]}},
        {"_id": 0, "amount": 1, "created_at": 1, "status": 1, "type": 1}).to_list(2000)
    for c in commissions:
        if (c.get("created_at") or "")[:10] == today:
            today_income += c.get("amount", 0.0)

    ref_count = await db.referral_relationships.count_documents({"sponsor_id": user["id"]})
    sales_count = await db.orders.count_documents({"seller_user_id": user["id"], "payment_status": "paid"})
    pending_comm = sum(c.get("amount", 0.0) for c in commissions if c.get("status") == "PENDING")
    team_sales = sum(c.get("amount", 0.0) for c in commissions
                     if c.get("type") in ("COMMISSION_REFERRAL", "COMMISSION_TEAM"))
    txns = await db.wallet_transactions.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(5)
    notif = await db.notifications.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(5)

    # 7-day income series
    series = []
    for i in range(6, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).date().isoformat()
        amt = sum(c.get("amount", 0.0) for c in commissions if (c.get("created_at") or "")[:10] == day)
        series.append({"date": day[5:], "income": amt})

    return {
        "user": {"distributor_id": user.get("distributor_id"), "full_name": user.get("full_name"),
                 "status": user.get("status"), "kyc_status": user.get("kyc_status")},
        "settings": {"currency_symbol": settings.get("currency_symbol", "₹")},
        "wallet": {"available_balance": wallet["available_balance"], "pending_balance": wallet["pending_balance"],
                   "total_earned": wallet["total_earned"], "total_withdrawn": wallet["total_withdrawn"]},
        "stats": {"total_income": total_income, "today_income": today_income, "total_orders": total_orders,
                  "referral_count": ref_count, "sales_count": sales_count,
                  "pending_commission": round(pending_comm, 2), "team_commission": round(team_sales, 2)},
        "plan": {"direct_pct": settings.get("commission_direct_pct", 30.0),
                 "referral_pct": settings.get("commission_referral_pct", 10.0),
                 "team_pct": settings.get("commission_team_pct", 5.0),
                 "return_window_days": settings.get("return_window_days", 7),
                 "point_value": settings.get("point_value", 1.0),
                 "withdrawal_enabled": settings.get("points_withdrawal_enabled", True)},
        "recent_orders": recent_orders,
        "recent_transactions": txns,
        "notifications": notif,
        "income_series": series,
    }
