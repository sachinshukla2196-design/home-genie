"""HomeGenie Points wallet, sharing links, identity records, withdrawals, notifications, dashboard."""
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone, timedelta

from pymongo.errors import DuplicateKeyError

from money import to_paise, paise_to_float, paise_of
from core import (db, now_iso, new_id, get_current_user, get_settings, get_or_create_wallet, create_notification,
                  log_audit)

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


@router.get("/commissions/statement")
async def my_commission_statement(user: dict = Depends(get_current_user)):
    """Batch 5 (HG-02/HG-03): the member's own commission statement — every commission, net of reversals, with why it is
    still held. Amounts are integer paise; the release rule is delivery + the return window (owner decision 2)."""
    from eligibility import payout_block
    from money import paise_to_float
    rows = await db.commissions.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)
    orders = {o["id"]: o for o in await db.orders.find({"id": {"$in": list({r["order_id"] for r in rows})}}, {"_id": 0}).to_list(None)}
    items, totals = [], {"earned_paise": 0, "reversed_paise": 0, "released_paise": 0, "pending_paise": 0}
    for r in rows:
        amt, rev = paise_of(r, "amount_paise", "amount"), paise_of(r, "reversed_paise", "reversed_amount")   # C-21: legacy rows
        released = bool(r.get("released_at"))
        hold = None if released or r.get("status") == "REVERSED" else await payout_block(orders.get(r["order_id"]), hold_days=r.get("release_after_days") or 0)
        net = max(amt - rev, 0)
        totals["earned_paise"] += amt
        totals["reversed_paise"] += rev
        totals["released_paise" if released else "pending_paise"] += 0 if r.get("status") == "REVERSED" else net
        events = [x.get("event_id") for x in r.get("reversal_records") or [] if x.get("event_id")]
        reasons = []
        if events:
            async for ev in db.order_refunds.find({"id": {"$in": events}}, {"_id": 0, "reason": 1}):
                if ev.get("reason"):
                    reasons.append(ev["reason"])
        items.append({"id": r["id"], "order_number": r.get("order_number"), "type": r.get("type"), "status": r.get("status"),
                      "percent": r.get("percent"), "base_paise": paise_of(r, "base_paise", "base_amount") if (r.get("base_paise") or r.get("base_amount")) else None,
                      "amount_paise": amt, "reversed_paise": rev, "net_paise": net, "net": paise_to_float(net),
                      "created_at": r.get("created_at"), "released_at": r.get("released_at"), "held_because": hold,
                      "reversal_reasons": reasons or (["Order cancelled or refunded"] if rev else [])})
    return {"items": items, **totals, **{k[:-6]: paise_to_float(v) for k, v in totals.items()}}


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
        "eligible": user.get("role") == "distributor" and user.get("status") == "green",
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
        "status": "pending", "rejection_reason": None, "last_edited_by": None,
        "submitted_at": now_iso(), "updated_at": now_iso(),
    }
    existing = await db.kyc_records.find_one({"user_id": user["id"]})
    if existing:
        rec["id"] = existing.get("id", new_id())
        await db.kyc_records.update_one({"user_id": user["id"]}, {"$set": rec, "$inc": {"version": 1}})   # version: stale reviews refused
    else:
        rec["id"] = new_id()
        rec["created_at"] = now_iso()
        rec["version"] = 1
        try:
            await db.kyc_records.insert_one(dict(rec))
        except DuplicateKeyError:
            # W5: a concurrent submission (double click, two tabs) created the member's record first (unique index
            # kyc_records_user_unique); this submission updates that record exactly like a resubmission, never a second record.
            for k in ("id", "created_at", "version"):
                rec.pop(k, None)
            await db.kyc_records.update_one({"user_id": user["id"]}, {"$set": rec, "$inc": {"version": 1}})
    await db.users.update_one({"id": user["id"]}, {"$set": {"kyc_status": "pending", "updated_at": now_iso()}})
    await create_notification(user["id"], "kyc", "KYC submitted",
                              "Your KYC has been submitted and is under review.",
                              "केवाईसी जमा हुई", "आपकी केवाईसी समीक्षा हेतु जमा कर दी गई है।")
    await log_audit(user, "kyc_submitted", "kyc", user["id"], request=request)
    return {"status": "pending", "message": "KYC submitted for review."}


# ---------------- Withdrawals ----------------
class WithdrawBody(BaseModel):
    amount: float = Field(gt=0)
    # Programme 03 (B-022): an idempotency key chosen by the client for one withdrawal attempt and reused on every retry of it.
    # The same key returns the same request (never a second one); optional so older clients keep working.
    request_key: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{8,80}$")


@router.get("/withdrawals")
async def my_withdrawals(user: dict = Depends(get_current_user)):
    # a request that never reserved money (closed as not_reserved) is evidence for finance, not a withdrawal of the member's
    return await db.withdrawal_requests.find({"user_id": user["id"], "status": {"$ne": "not_reserved"}},
                                             {"_id": 0, "request_key": 0, "hold_op": 0}).sort("created_at", -1).to_list(200)


def _public_wr(wr: dict, **extra) -> dict:
    out = {k: v for k, v in wr.items() if k not in ("_id", "request_key", "hold_op")}
    out.update(extra)
    return out


async def _finish_existing(wr: dict, amount_p: int, request: Request, user: dict, settings: dict) -> dict:
    """A retry with a key that already has a request: never a second request. Different amount -> 409."""
    import withdrawal_intents as wi
    if int(wr.get("amount_paise") or -1) != amount_p:
        raise HTTPException(status_code=409, detail="This withdrawal request was already submitted with a different amount. "
                                                    "Refresh the page and submit a new request.")
    if wr.get("status") == wi.RESERVING:
        await wi.settle(wr, actor=user, request=request, settings=settings)
        wr = await db.withdrawal_requests.find_one({"id": wr["id"]}, {"_id": 0})
    if wr.get("status") == wi.NOT_RESERVED:
        raise HTTPException(status_code=400, detail="Insufficient available balance.")
    if wr.get("status") == wi.RESERVING:
        raise HTTPException(status_code=503, detail="Your withdrawal request is still being processed. Try again in a moment.")
    return _public_wr(wr, already=True)


@router.post("/withdrawals")
async def request_withdrawal(body: WithdrawBody, request: Request, user: dict = Depends(get_current_user)):
    """Programme 03 (B-022): the request is written first (status reserving), then the money is held at most once on the wallet,
    then its ledger row is ensured and the request opens as pending. A crash at any point is finished by a retry with the same
    request_key or by the withdrawal_request_repair sweep; see withdrawal_intents. Eligibility rules are unchanged."""
    import withdrawal_intents as wi
    if user.get("role") != "distributor" or user.get("status") != "green":
        raise HTTPException(status_code=403, detail="Your HomeGenie selling role must be approved before you can withdraw points.")
    settings = await get_settings()
    if not settings.get("points_withdrawal_enabled", True):
        raise HTTPException(status_code=400, detail="Point withdrawal is not enabled yet.")
    # No minimum withdrawal amount - any amount within the available balance may be requested.
    if settings.get("require_kyc_for_withdrawal", True):
        kyc = await db.kyc_records.find_one({"user_id": user["id"]})
        if not kyc or kyc.get("status") != "verified":
            raise HTTPException(status_code=400, detail="Verify your identity and bank details before withdrawing points.")
    amount_p = to_paise(body.amount)
    if amount_p <= 0:
        raise HTTPException(status_code=400, detail="Enter a valid amount.")
    key = body.request_key
    if key:
        prior = await db.withdrawal_requests.find_one({"user_id": user["id"], "request_key": key}, {"_id": 0})
        if prior:
            return await _finish_existing(prior, amount_p, request, user, settings)
    wallet = await get_or_create_wallet(user["id"])
    if paise_of(wallet, "available_balance_paise", "available_balance") < amount_p:      # fast refusal; the hold re-checks atomically
        raise HTTPException(status_code=400, detail="Insufficient available balance.")
    wd_id, now = new_id(), now_iso()
    wr = {
        "id": wd_id, "request_number": f"WD{new_id()[:8].upper()}", "user_id": user["id"],
        "distributor_id": user.get("distributor_id"), "amount": paise_to_float(amount_p), "amount_paise": amount_p,
        "status": wi.RESERVING, "hold_op": wi.hold_op(wd_id), "admin_note": None, "created_at": now, "updated_at": now,
    }
    if key:
        wr["request_key"] = key
    from money_guard import ensure as _money_guard
    await _money_guard("wallet", "withdrawals")
    try:
        await db.withdrawal_requests.insert_one(dict(wr))
    except DuplicateKeyError:                                     # a concurrent retry with the same key created it first
        prior = await db.withdrawal_requests.find_one({"user_id": user["id"], "request_key": key}, {"_id": 0})
        if not prior:
            raise
        return await _finish_existing(prior, amount_p, request, user, settings)
    status = await wi.settle(wr, actor=user, request=request, settings=settings)
    if status == wi.NOT_RESERVED:
        raise HTTPException(status_code=400, detail="Insufficient available balance.")
    if status == wi.RESERVING:
        raise HTTPException(status_code=503, detail="Your withdrawal request is still being processed. Try again in a moment.")
    cur = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0}) or wr
    return _public_wr(cur)


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
@router.get("/badge")
async def my_badge(user: dict = Depends(get_current_user)):
    from badges import monthly_badge
    return await monthly_badge(user["id"])


def _public_name(full_name: str) -> str:
    """First name + last initial, so the leaderboard never exposes a full identity."""
    parts = (full_name or "").split()
    if not parts:
        return "HomeGenie"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


@router.get("/leaderboard")
async def leaderboard(user: dict = Depends(get_current_user)):
    """Top HomeGenies by this month's paid sales through their share link (pre-GST),
    the same metric the monthly badges use. Real orders only, no seeded rows."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    rows = await db.orders.aggregate([
        {"$match": {"seller_user_id": {"$nin": [None, ""]}, "payment_status": "paid",
                    "created_at": {"$regex": f"^{month}"}}},
        {"$group": {"_id": "$seller_user_id", "sales": {"$sum": "$subtotal"}, "orders": {"$sum": 1}}},
        {"$sort": {"sales": -1}},
        {"$limit": 500},
    ]).to_list(500)

    ids = [r["_id"] for r in rows]
    people = {u["id"]: u for u in await db.users.find(
        {"id": {"$in": ids}}, {"_id": 0, "id": 1, "full_name": 1, "city": 1}).to_list(len(ids) or 1)}

    ranked = [{"rank": i + 1, "name": _public_name(people.get(r["_id"], {}).get("full_name")),
               "city": people.get(r["_id"], {}).get("city") or "",
               "sales": round(float(r["sales"] or 0), 2), "orders": r["orders"],
               "is_me": r["_id"] == user["id"]} for i, r in enumerate(rows)]
    me = next((r for r in ranked if r["is_me"]), None)
    return {"month": month, "top": ranked[:10], "me": me, "total_sellers": len(ranked)}


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
        "badge": await __import__("badges").monthly_badge(user["id"]),
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
