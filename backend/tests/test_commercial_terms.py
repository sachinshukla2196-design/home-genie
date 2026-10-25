"""Commercial agreements and vendor finance (Phase 6): versioning, effective dates, calculations, vendor access, settlement transitions.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_commercial_terms.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_commercial_test", "JWT_SECRET": "commercial-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger as L  # noqa: E402
import commercial_terms as CT  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Vendor-Pass-123"
ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _day(offset=0):
    return (datetime.now(timezone.utc).date() + timedelta(days=offset)).isoformat()


def _paid_order(vid, pid, total_paise, paid_day=0, status="delivered"):
    paid_at = (datetime.now(timezone.utc) + timedelta(days=paid_day)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()
    line = {"product_id": pid, "name": "Commercial item", "sku": "COM", "vendor_id": vid, "quantity": 1, "total_paise": total_paise, "total": total_paise / 100}
    return {"id": new_id(), "order_number": "COM" + new_id()[:8].upper(), "user_id": new_id(), "payment_method": "online", "payment_status": "paid",
            "status": status, "created_at": paid_at, "paid_at": paid_at, "total_paise": total_paise, "total": total_paise / 100,
            "items": [line], "fulfilments": [{"vendor_id": vid, "status": status, "events": []}], "address": ADDR, "needs_refund": False}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()      # the migration step: startup no longer creates indexes

            async def user(mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password(PW), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name, code):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": code, "business_name": name, "status": "approved",
                     "categories": ["Sarees"], "bank_account": "111122223333", "bank_account_name": name, "ifsc": "SBIN0000001",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v

            S["fin1"] = await user("9100003001", "accounts_admin", "CFA1")
            S["fin2"] = await user("9100003002", "super_admin", "CFA2")
            S["cust"] = await user("9100003003", "distributor", "CCUS")
            S["ua"] = await user("9100003004", "vendor", "CVA")
            S["va"] = await vendor(S["ua"], "Terms Store A", "VC000001")
            S["ub"] = await user("9100003005", "vendor", "CVB")
            S["vb"] = await vendor(S["ub"], "Terms Store B", "VC000002")
            S["pa"] = new_id()
            await db.products.insert_one({"id": S["pa"], "vendor_id": S["va"]["id"], "name": "Terms item", "sku": "TI-1", "stock": 5,
                                          "low_stock_threshold": 5, "is_active": True, "approval_status": "approved", "archived": False,
                                          "category": "Sarees", "created_at": now_iso(), "updated_at": now_iso()})
            await db.finance_policy.update_one({"id": "settlement_policy"}, {"$set": {"id": "settlement_policy", "active": True, "version": 1,
                                                "require_dual_approval": True, "min_settlement_paise": 0, "cod_overdue_days": 7,
                                                "notes": "test", "updated_by": None, "updated_at": now_iso()}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _draft(c, fin, offset, pct, fee=0, who_vendor="va"):
    r = c.post(f"/api/admin/finance/vendors/{S[who_vendor]['id']}/agreements", headers=_hdr(S[fin]["id"]),
               json={"commission_pct": pct, "fixed_fee_paise": fee, "settlement_schedule": "monthly", "effective_from": _day(offset), "notes": "t"})
    assert r.status_code == 200, r.text
    return r.json()


def _approve(c, fin, aid):
    return c.post(f"/api/admin/finance/agreements/{aid}/approve", headers=_hdr(S[fin]["id"]))


def _post(c, order):
    c.portal.call(lambda: db.orders.insert_one(dict(order)))
    c.portal.call(lambda: L.post_order_collected(order))


def _commissions(c, oid):
    return c.portal.call(lambda: db.vendor_ledger.find({"order_id": oid, "type": "COMMISSION"}, {"_id": 0}).to_list(20))


# ====================================================================== versioning and approval
def test_agreements_are_versioned_and_need_a_different_approver(c):
    v1 = _draft(c, "fin1", 0, 5.25, 1000)
    assert v1["version"] == 1 and v1["status"] == "draft"
    assert _approve(c, "fin1", v1["id"]).status_code == 403                    # the creator cannot approve their own draft
    assert _approve(c, "fin2", v1["id"]).status_code == 200
    assert _approve(c, "fin2", v1["id"]).status_code == 400                    # an approved version is never re-approved
    v2 = _draft(c, "fin1", 30, 3.0)
    assert v2["version"] == 2
    clash = _draft(c, "fin1", 0, 4.0)
    assert _approve(c, "fin2", clash["id"]).status_code == 409                 # two approved versions cannot start the same day
    assert c.post(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["fin1"]["id"]),
                  json={"commission_pct": 1, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": _day(-3)}).status_code == 400   # no past dates
    assert c.post(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["fin1"]["id"]),
                  json={"commission_pct": 101, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": _day(1)}).status_code == 422
    listed = c.get(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["fin2"]["id"])).json()["agreements"]
    assert [a["version"] for a in listed] == sorted([a["version"] for a in listed], reverse=True)


# ====================================================================== effective dates and calculations
def test_commission_uses_the_version_in_force_on_the_order_date(c):
    before = _paid_order(S["va"]["id"], S["pa"], 100000, paid_day=-1)           # before v1 starts today
    _post(c, before)
    assert _commissions(c, before["id"]) == []
    today = _paid_order(S["va"]["id"], S["pa"], 100000, paid_day=0)              # v1: 5.25% plus Rs 10 per order
    _post(c, today)
    entry = _commissions(c, today["id"])[0]
    assert entry["amount_paise"] == -(round(100000 * 0.0525) + 1000) == -6250
    assert entry["meta"]["version"] == 1 and entry["meta"]["commission_pct"] == 5.25 and entry["meta"]["fixed_fee_paise"] == 1000


def test_commission_is_never_more_than_the_sale_and_rounds_half_up():
    a = {"commission_pct": 33.33, "fixed_fee_paise": 0}
    assert CT.commission_for(a, 1) == 0 and CT.commission_for(a, 3) == 1
    assert CT.commission_for({"commission_pct": 50, "fixed_fee_paise": 1000}, 500) == 500         # fee cannot exceed the sale
    assert CT.commission_for({"commission_pct": 2.5, "fixed_fee_paise": 0}, 1001) == 25           # 25.025 rounds to 25


def test_historical_commissions_keep_their_version_when_a_newer_one_starts(c):
    v2 = c.get(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["fin2"]["id"])).json()["agreements"]
    v2 = next(a for a in v2 if a["version"] == 2)
    assert _approve(c, "fin1", v2["id"]).status_code == 403                    # wrong approver again
    assert _approve(c, "fin2", v2["id"]).status_code == 200
    later = _paid_order(S["va"]["id"], S["pa"], 200000, paid_day=35)            # after v2 starts (3%)
    _post(c, later)
    assert _commissions(c, later["id"])[0]["meta"]["version"] == 2
    today_entry = c.portal.call(lambda: db.vendor_ledger.find_one({"vendor_id": S["va"]["id"], "type": "COMMISSION", "meta.version": 1}, {"_id": 0}))
    assert today_entry is not None and today_entry["amount_paise"] == -6250                    # unchanged by v2


def test_balances_show_commissions_and_net_payable(c):
    bal = c.portal.call(lambda: L.balances(S["va"]["id"]))
    assert bal["commissions_paise"] < 0
    assert bal["vendor_payable_paise"] == bal["eligible_sales_paise"] + bal["sale_reversals_paise"] + bal["refunds_paise"] + bal["adjustments_paise"] + bal["commissions_paise"]


def test_cancelling_an_unfulfilled_order_returns_its_commission(c):
    o = _paid_order(S["va"]["id"], S["pa"], 50000, paid_day=0, status="accepted")
    _post(c, o)                                                              # the sale and its commission are recorded
    assert sum(r["amount_paise"] for r in _commissions(c, o["id"])) < 0
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"fulfilments.0.status": "rejected"}}))
    o["fulfilments"][0]["status"] = "rejected"
    c.portal.call(lambda: L.post_sale_reversal(o, S["va"]["id"]))              # the vendor did not fulfil it
    assert sum(r["amount_paise"] for r in _commissions(c, o["id"])) == 0      # charge and return net to nothing


# ====================================================================== vendor access
def test_vendors_read_and_accept_terms_but_cannot_change_or_approve_them(c):
    terms = c.get("/api/vendor/finance/terms", headers=_hdr(S["ua"]["id"])).json()
    assert terms["current"] is not None and terms["current"]["version"] == 1
    assert all("approved_by" not in a and "created_by" not in a for a in terms["agreements"])
    v1 = next(a for a in terms["agreements"] if a["version"] == 1)
    assert c.post(f"/api/vendor/finance/terms/{v1['id']}/accept", headers=_hdr(S["ua"]["id"])).status_code == 200
    assert c.post(f"/api/vendor/finance/terms/{v1['id']}/accept", headers=_hdr(S["ua"]["id"])).status_code == 409
    assert c.post(f"/api/vendor/finance/terms/{v1['id']}/accept", headers=_hdr(S["ub"]["id"])).status_code == 404   # B cannot accept A's terms
    assert c.get("/api/vendor/finance/terms", headers=_hdr(S["ub"]["id"])).json()["agreements"] == []           # B sees none of A's
    assert c.post(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["ua"]["id"]),
                  json={"commission_pct": 0, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": _day(60)}).status_code == 403
    assert _approve(c, "ua", v1["id"]).status_code == 403
    assert c.get(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["ua"]["id"])).status_code == 403


# ====================================================================== settlements and duplicate payouts
def _settlement(c, fin="fin1", amount=None):
    body = {"vendor_id": S["va"]["id"], "note": "Monthly payout"}
    if amount is not None:
        body["amount"] = amount
    return c.post("/api/admin/finance/settlements", headers=_hdr(S[fin]["id"]), json=body)


def test_settlement_moves_through_approval_and_payment_with_a_different_admin_each_time(c):
    r = _settlement(c, "fin1", amount=100.0)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    assert _settlement(c, "fin1", amount=50.0).status_code == 409             # one open payout per vendor at a time
    act = lambda who, action, **kw: c.post(f"/api/admin/finance/settlements/{sid}/action", headers=_hdr(S[who]["id"]), json={"action": action, "note": "Checked", **kw})
    assert act("fin1", "approve").status_code == 403                          # creator cannot approve
    assert act("fin2", "approve").status_code == 200
    assert act("fin2", "mark_paid", reference="UTR123456").status_code == 403  # approver cannot pay
    assert act("fin1", "mark_paid", reference="UTR123456").status_code == 200
    assert act("fin1", "mark_paid", reference="UTR123456").status_code == 400  # already completed: no second payout
    assert act("fin2", "reject", note="Too late now").status_code == 400      # a completed payout cannot be rejected


def test_vendors_see_their_payouts_without_admin_identities_and_cannot_act_on_them(c):
    rows = c.get("/api/vendor/finance/settlements", headers=_hdr(S["ua"]["id"])).json()["items"]
    assert rows and rows[0]["status"] == "paid" and rows[0].get("reference") == "UTR123456"
    text = str(rows)
    assert S["fin1"]["id"] not in text and S["fin2"]["id"] not in text
    assert "approved_by" not in rows[0] and "paid_by" not in rows[0] and "created_by" not in rows[0]
    sid = rows[0]["id"]
    assert c.post(f"/api/admin/finance/settlements/{sid}/action", headers=_hdr(S["ua"]["id"]), json={"action": "mark_paid", "reference": "SELF123", "note": "x"}).status_code == 403
    assert c.post("/api/admin/finance/vendors/" + S["va"]["id"] + "/adjustments", headers=_hdr(S["ua"]["id"]), json={"amount": 500, "reason": "Credit me"}).status_code == 403
    assert c.post("/api/vendor/finance/settlements", headers=_hdr(S["ua"]["id"]), json={"amount": 1}).status_code in (404, 405)


def test_vendor_b_cannot_see_or_settle_vendor_a(c):
    assert c.get("/api/vendor/finance/settlements", headers=_hdr(S["ub"]["id"])).json()["items"] == []
    sid = c.get("/api/vendor/finance/settlements", headers=_hdr(S["ua"]["id"])).json()["items"][0]["id"]
    assert c.post(f"/api/admin/finance/settlements/{sid}/action", headers=_hdr(S["ub"]["id"]), json={"action": "approve", "note": "x"}).status_code == 403
