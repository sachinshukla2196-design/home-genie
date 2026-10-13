"""Rule 6 rank-based monthly incomes: Royalty (RD), Master Club (CD), Super Club (PD).
Each qualifier (EXACT rank at run time) earns rate% of their OWN team's monthly paid turnover
(subtotal excl GST, all downline levels). Idempotent per (user, category, month)."""
import math
from core import db, now_iso, add_wallet_transaction, create_notification
from income_config import resolve_rate
from wallet_routes import compute_rank, _personal_bv, MAX_TEAM_LEVEL

CLUB_RULES = [("ROYALTY", "RD", "Royalty Income"),
              ("MASTER_CLUB", "CD", "Master Club Income"),
              ("SUPER_CLUB", "PD", "Super Club Income")]


async def _downline_ids(user_id: str) -> list:
    seen, frontier, out = {user_id}, [user_id], []
    for _ in range(MAX_TEAM_LEVEL):
        if not frontier:
            break
        rels = await db.referral_relationships.find({"sponsor_id": {"$in": frontier}},
                                                    {"_id": 0, "referred_user_id": 1}).to_list(10000)
        frontier = [r["referred_user_id"] for r in rels if r.get("referred_user_id") and r["referred_user_id"] not in seen]
        seen.update(frontier)
        out.extend(frontier)
    return out


async def _month_turnover(user_ids: list, month: str) -> float:
    if not user_ids:
        return 0.0
    orders = await db.orders.find({"user_id": {"$in": user_ids}, "payment_status": "paid",
                                   "status": {"$nin": ["cancelled", "refunded", "reversed"]}},
                                  {"_id": 0, "subtotal": 1, "created_at": 1}).to_list(100000)
    return round(sum(float(o.get("subtotal") or 0) for o in orders if str(o.get("created_at", "")).startswith(month)), 2)


async def compute_club_income(month: str) -> dict:
    users = await db.users.find({"role": "distributor"}, {"_id": 0, "id": 1, "distributor_id": 1,
                                                          "full_name": 1, "status": 1}).to_list(100000)
    rules = {k: await resolve_rate(k) for k, _, _ in CLUB_RULES}
    allocations = []
    for u in users:
        rank = compute_rank(await _personal_bv(u["id"]))["code"]
        for key, rank_code, label in CLUB_RULES:
            if rank != rank_code or not rules[key]["enabled"]:
                continue
            team = await _downline_ids(u["id"])
            turnover = await _month_turnover(team, month)
            amount = math.floor(turnover * rules[key]["rate"]) / 100.0
            allocations.append({"user_id": u["id"], "distributor_id": u["distributor_id"], "name": u.get("full_name"),
                                "status": u.get("status"), "rank": rank, "category": key, "label": label,
                                "rate": rules[key]["rate"], "rule_version": rules[key]["version"],
                                "team_size": len(team), "team_turnover": turnover, "amount": round(amount, 2)})
    run = await db.monthly_income_runs.find_one({"id": f"CLUB:{month}"}, {"_id": 0})
    return {"month": month, "allocations": allocations, "qualifiers": len(allocations),
            "total_payout": round(sum(a["amount"] for a in allocations), 2),
            "status": (run or {}).get("status", "not_processed"), "processed_at": (run or {}).get("processed_at")}


async def distribute_club_income(month: str, processed_by: str) -> dict:
    calc = await compute_club_income(month)
    newly = 0
    for a in calc["allocations"]:
        ref = f"CLUB:{a['category']}:{month}"
        if a["amount"] <= 0 or await db.wallet_transactions.find_one({"user_id": a["user_id"], "type": a["category"], "reference": ref}):
            continue
        await add_wallet_transaction(a["user_id"], a["category"], a["amount"], "CREDITED", reference=ref,
                                     direction="credit", description=f"{a['label']} {month} ({a['rate']}% of team turnover ₹{a['team_turnover']})")
        await create_notification(a["user_id"], "income", f"₹{a['amount']} {a['label']}",
                                  f"{a['rate']}% of your team's {month} turnover ₹{a['team_turnover']}.",
                                  f"₹{a['amount']} {a['label']}", f"{month} टीम टर्नओवर ₹{a['team_turnover']} का {a['rate']}%।")
        newly += 1
    await db.monthly_income_runs.update_one({"id": f"CLUB:{month}"}, {"$set": {
        "id": f"CLUB:{month}", "month": month, "kind": "CLUB", "qualifiers": calc["qualifiers"],
        "total_payout": calc["total_payout"], "allocations": calc["allocations"], "status": "completed",
        "processed_at": now_iso(), "processed_by": processed_by, "newly_credited": newly}}, upsert=True)
    return {**calc, "status": "completed", "newly_credited": newly}
