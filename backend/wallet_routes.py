"""Wallet, referral, KYC, withdrawals, notifications, dashboard for distributors."""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone, timedelta

from core import (db, now_iso, new_id, get_current_user, get_settings, get_or_create_wallet,
                  add_wallet_transaction, create_notification, log_audit)

router = APIRouter(prefix="/api", tags=["distributor"])


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
        "commission": settings.get("referral_commission", 100.0),
        "total_referrals": count,
        "active_referrals": active,
    }


MAX_TEAM_LEVEL = 8


@router.get("/team")
async def team(user: dict = Depends(get_current_user)):
    """8-level team hierarchy (Level 1 → Level 8) built from referral_relationships,
    with team size and income earned by the current user attributed to each level."""
    seen = {user["id"]}
    frontier = [user["id"]]
    level_rels = {}  # level -> list of relationship docs (deduped)
    for lvl in range(1, MAX_TEAM_LEVEL + 1):
        if not frontier:
            break
        rels = await db.referral_relationships.find(
            {"sponsor_id": {"$in": frontier}}, {"_id": 0}).to_list(10000)
        new_rels, next_frontier = [], []
        for r in rels:
            rid = r.get("referred_user_id")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            new_rels.append(r)
            next_frontier.append(rid)
        if not new_rels:
            break
        level_rels[lvl] = new_rels
        frontier = next_frontier

    all_ids = [r["referred_user_id"] for rels in level_rels.values() for r in rels]
    users_map = {u["id"]: u for u in await db.users.find(
        {"id": {"$in": all_ids}},
        {"_id": 0, "id": 1, "full_name": 1, "distributor_id": 1, "status": 1,
         "created_at": 1, "city": 1, "state": 1, "photo": 1}).to_list(len(all_ids) or 1)}

    # income earned by this user, grouped per member they were credited for
    income_by_member = {}
    comms = await db.commissions.find(
        {"sponsor_id": user["id"]}, {"_id": 0, "referred_user_id": 1, "amount": 1}).to_list(5000)
    for c in comms:
        rid = c.get("referred_user_id")
        income_by_member[rid] = income_by_member.get(rid, 0.0) + c.get("amount", 0.0)

    # direct downline count for each member
    downline_map = {}
    if all_ids:
        agg = await db.referral_relationships.aggregate([
            {"$match": {"sponsor_id": {"$in": all_ids}}},
            {"$group": {"_id": "$sponsor_id", "c": {"$sum": 1}}},
        ]).to_list(len(all_ids))
        downline_map = {g["_id"]: g["c"] for g in agg}

    levels_out, total_members, total_active, total_income = [], 0, 0, 0.0
    for lvl in range(1, MAX_TEAM_LEVEL + 1):
        rels = level_rels.get(lvl, [])
        members, lvl_income = [], 0.0
        for r in sorted(rels, key=lambda x: x.get("created_at") or "", reverse=True):
            u = users_map.get(r["referred_user_id"])
            if not u:
                continue
            inc = income_by_member.get(r["referred_user_id"], 0.0)
            lvl_income += inc
            members.append({
                "full_name": u.get("full_name"), "distributor_id": u.get("distributor_id"),
                "status": u.get("status"), "photo": u.get("photo"),
                "city": u.get("city"), "state": u.get("state"),
                "joined_at": r.get("created_at"),
                "commission_paid": r.get("commission_paid", False),
                "downline_count": downline_map.get(r["referred_user_id"], 0),
                "income": inc,
            })
        active = sum(1 for m in members if m["status"] == "green")
        total_members += len(members)
        total_active += active
        total_income += lvl_income
        levels_out.append({"level": lvl, "count": len(members), "active": active,
                           "income": lvl_income, "members": members})

    root = {"full_name": user.get("full_name"), "distributor_id": user.get("distributor_id"),
            "status": user.get("status"), "photo": user.get("photo")}
    l1 = levels_out[0]["members"] if levels_out else []
    return {"root": root, "levels": levels_out, "members": l1,
            "total": total_members, "active": total_active,
            "direct": len(l1), "total_income": total_income}


# ---------------- KYC ----------------
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
        raise HTTPException(status_code=403, detail="Activate your account (GREEN) to request withdrawals.")
    settings = await get_settings()
    # No minimum withdrawal amount — user may request any amount within available balance.
    if settings.get("require_kyc_for_withdrawal", True):
        kyc = await db.kyc_records.find_one({"user_id": user["id"]})
        if not kyc or kyc.get("status") != "verified":
            raise HTTPException(status_code=400, detail="Complete and verify your KYC before withdrawing.")
    wallet = await get_or_create_wallet(user["id"])
    if body.amount > wallet["available_balance"]:
        raise HTTPException(status_code=400, detail="Insufficient available balance.")

    # move to pending (debit available, add pending) via ledger
    await add_wallet_transaction(user["id"], "WITHDRAWAL", body.amount, "DEBITED",
                                 description="Withdrawal request (held)", direction="debit")
    await add_wallet_transaction(user["id"], "WITHDRAWAL", body.amount, "PENDING",
                                 description="Withdrawal pending admin review")
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
    commissions = await db.commissions.find({"sponsor_id": user["id"]},
                                             {"_id": 0, "amount": 1, "created_at": 1}).to_list(2000)
    for c in commissions:
        if (c.get("created_at") or "")[:10] == today:
            today_income += c.get("amount", 0.0)

    ref_count = await db.referral_relationships.count_documents({"sponsor_id": user["id"]})
    active_team = await db.users.count_documents({"sponsor_user_id": user["id"], "status": "green"})
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
        "settings": {"activation_amount": settings.get("activation_amount"),
                     "referral_commission": settings.get("referral_commission"),
                     "currency_symbol": settings.get("currency_symbol", "₹")},
        "wallet": {"available_balance": wallet["available_balance"], "pending_balance": wallet["pending_balance"],
                   "total_earned": wallet["total_earned"], "total_withdrawn": wallet["total_withdrawn"]},
        "stats": {"total_income": total_income, "today_income": today_income, "total_orders": total_orders,
                  "referral_count": ref_count, "active_team": active_team},
        "recent_orders": recent_orders,
        "recent_transactions": txns,
        "notifications": notif,
        "income_series": series,
    }
