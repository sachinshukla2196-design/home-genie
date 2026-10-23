"""Exact money: arithmetic, order totals, commissions, wallets, refunds, withdrawals and the paise migration.

Pure unit tests plus in-process flow tests on a THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import copy
import os
import random
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_money_test", "JWT_SECRET": "money-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
import money_migration as mm  # noqa: E402
from money import (to_paise, paise_to_float, mul_pct, mul_ratio, split_exact, fmt_inr, dec, paise_of)  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id, get_or_create_wallet, wallet_apply  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


# ============================================================ pure arithmetic
def test_rupees_to_paise_is_exact_and_half_up():
    assert to_paise(0.1 + 0.2) == 30                       # the classic float trap
    assert to_paise(1.005) == 101 and round(1.005, 2) == 1.0   # float round() gets this wrong; we do not
    assert to_paise(2.675) == 268 and round(2.675, 2) == 2.67
    assert to_paise("1234.56") == 123456 and to_paise(Decimal("0.005")) == 1 and to_paise(0) == 0 and to_paise(7) == 700
    assert to_paise(-1.005) == -101                         # half-up away from zero is consistent for negatives
    assert paise_to_float(123456) == 1234.56 and paise_to_float(5) == 0.05 and str(paise_to_float(10)) == "0.1"


@pytest.mark.parametrize("bad", ["abc", "", None, float("nan"), float("inf"), "1,000"])
def test_invalid_amounts_are_rejected_not_guessed(bad):
    with pytest.raises(ValueError):
        to_paise(bad)


def test_percentages_and_ratios_use_one_rounding_rule():
    assert mul_pct(9999, 30) == 3000 and mul_pct(9999, 10) == 1000 and mul_pct(9999, 5) == 500    # 2999.7, 999.9, 499.95
    assert mul_pct(10, 5) == 1 and mul_pct(9, 5) == 0 and mul_pct(1000, "7.5") == 75
    assert mul_ratio(1000, 1, 3) == 333 and mul_ratio(1000, 2, 3) == 667 and mul_ratio(5, 1, 2) == 3
    with pytest.raises(ValueError):
        mul_ratio(1, 1, 0)


def test_split_exact_never_loses_or_creates_a_paisa():
    rnd = random.Random(7)
    for _ in range(500):
        total, parts = rnd.randint(0, 10**7), rnd.randint(1, 9)
        shares = split_exact(total, parts)
        assert sum(shares) == total and max(shares) - min(shares) <= 1


def test_sums_of_many_float_amounts_drift_but_paise_never_do():
    amounts = [0.1] * 1000
    assert sum(amounts) != 100.0                            # floats really do drift
    assert sum(to_paise(a) for a in amounts) == 10000       # paise do not
    assert fmt_inr(123456789) == "₹1,234,567.89" and fmt_inr(-5) == "-₹0.05"
    assert paise_of({"total_paise": 250}, "total_paise", "total") == 250 and paise_of({"total": 2.5}, "total_paise", "total") == 250


# ============================================================ flows
def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()

            async def user(mobile, role, did, sponsor=None, status="green"):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status, "account_status": "active",
                     "sponsor_user_id": sponsor["id"] if sponsor else None, "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u
            S["team"] = await user("9100000501", "distributor", "HGTEAM")
            S["ref"] = await user("9100000502", "distributor", "HGREF", S["team"])
            S["seller"] = await user("9100000503", "distributor", "HGSEL", S["ref"])
            S["cust"] = await user("9100000504", "distributor", "HGC", status="red")
            S["admin"] = await user("9100000505", "super_admin", "HGADM")
            await db.business_settings.update_one({"id": "business_settings"}, {"$set": {"gst_percent": 5.0, "cod_fee": 0.0}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _product(c, sku, price, stock=100):
    async def mk():
        p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": price + 100, "selling_price": price, "gst_percent": 5,
             "stock": stock, "category": "Sarees", "options": [], "vendor_id": None, "vendor_name": None,
             "is_active": True, "approval_status": "approved", "created_at": now_iso()}
        await db.products.insert_one(dict(p))
        return p
    return c.portal.call(mk)


def _order(c, pid, qty, method="online", seller="HGSEL"):
    body = {"items": [{"product_id": pid, "quantity": qty}], "address": ADDR, "payment_method": method}
    if seller:
        body["seller_ref"] = seller
    r = c.post("/api/orders", json=body, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _pay(c, o):
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    c.portal.call(lambda: shop_routes._process_paid_order(sid))


def test_order_totals_are_exact_paise_and_floats_are_derived(c):
    p = _product(c, "M-1", 33.33)
    o = _order(c, p["id"], 3, method="cod")
    assert (o["subtotal_paise"], o["gst_paise"], o["total_paise"]) == (9999, 500, 10499)    # 5% of 99.99 = 4.9995 -> 5.00
    assert (o["subtotal"], o["gst_amount"], o["total"]) == (99.99, 5.0, 104.99)
    assert o["items"][0]["price_paise"] == 3333 and o["items"][0]["total_paise"] == 9999 and o["money_version"] == 2
    assert o["total"] == paise_to_float(o["total_paise"])


def test_totals_are_never_off_by_a_paisa_across_many_prices_and_quantities(c):
    rnd = random.Random(11)
    for k in range(40):
        price = round(rnd.uniform(1, 5000), 2)
        qty = rnd.randint(1, 9)
        p = _product(c, f"M-R{k}", price)
        o = _order(c, p["id"], qty, method="cod")
        sub = to_paise(price) * qty
        assert o["subtotal_paise"] == sub and o["gst_paise"] == mul_pct(sub, 5) and o["total_paise"] == sub + mul_pct(sub, 5)


def test_commissions_are_exact_paise_and_wallets_hold_them_exactly(c):
    p = _product(c, "M-2", 33.33)
    o = _order(c, p["id"], 3)                                  # base 99.99 -> 30% / 10% / 5%
    _pay(c, o)
    rows = {r["type"]: r for r in c.portal.call(lambda: db.commissions.find({"order_id": o["id"]}).to_list(10))}
    assert rows["COMMISSION_DIRECT"]["amount_paise"] == 3000 and rows["COMMISSION_REFERRAL"]["amount_paise"] == 1000
    assert rows["COMMISSION_TEAM"]["amount_paise"] == 500
    assert rows["COMMISSION_DIRECT"]["amount"] == 30.0 and rows["COMMISSION_DIRECT"]["base_paise"] == 9999
    w = c.portal.call(lambda: db.wallets.find_one({"user_id": S["seller"]["id"]}))
    assert w["pending_balance_paise"] == 3000 and w["pending_balance"] == 30.0
    # paise arithmetic is exact: the three credits plus the platform remainder cannot exceed what the rules say
    assert 3000 + 1000 + 500 == 4500                              # direct + referral + team, exactly


# ============================================================ wallets
def test_old_wallet_is_upgraded_lazily_without_touching_its_stored_floats(c):
    uid = new_id()
    legacy = {"id": new_id(), "user_id": uid, "available_balance": 100.1, "pending_balance": 0.30000000000000004,
              "total_earned": 250.55, "total_withdrawn": 0.0, "active": True, "created_at": now_iso(), "updated_at": now_iso()}
    c.portal.call(lambda: db.wallets.insert_one(dict(legacy)))
    w = c.portal.call(lambda: get_or_create_wallet(uid))
    assert w["available_balance"] == 100.1 and w["pending_balance"] == 0.3            # exact view
    raw = c.portal.call(lambda: db.wallets.find_one({"user_id": uid}))
    assert raw["available_balance_paise"] == 10010 and raw["pending_balance_paise"] == 30 and raw["total_earned_paise"] == 25055
    assert raw["pending_balance"] == 0.30000000000000004 and raw["available_balance"] == 100.1   # originals untouched
    c.portal.call(lambda: get_or_create_wallet(uid))                                    # idempotent
    assert c.portal.call(lambda: db.wallets.find_one({"user_id": uid}))["available_balance_paise"] == 10010


def test_thousand_small_credits_are_exact_in_paise(c):
    uid = new_id()
    c.portal.call(lambda: get_or_create_wallet(uid))
    async def many():
        for _ in range(1000):
            await wallet_apply(uid, {"available_balance": to_paise(0.1)})
    c.portal.call(many)
    w = c.portal.call(lambda: get_or_create_wallet(uid))
    assert c.portal.call(lambda: db.wallets.find_one({"user_id": uid}))["available_balance_paise"] == 10000
    assert w["available_balance"] == 100.0                                              # the view is exact even if the float counter drifted


def test_concurrent_debits_cannot_overdraw(c):
    uid = new_id()
    c.portal.call(lambda: get_or_create_wallet(uid))
    c.portal.call(lambda: wallet_apply(uid, {"available_balance": 10000}))
    def debit(_):
        return c.portal.call(lambda: wallet_apply(uid, {"available_balance": -1000, "pending_balance": 1000}, require_available=1000))
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(debit, range(20)))
    raw = c.portal.call(lambda: db.wallets.find_one({"user_id": uid}))
    assert results.count(True) == 10 and raw["available_balance_paise"] == 0 and raw["pending_balance_paise"] == 10000


def test_withdrawal_is_checked_in_exact_paise(c):
    u = S["seller"]
    c.portal.call(lambda: db.kyc_records.update_one({"user_id": u["id"]}, {"$set": {"user_id": u["id"], "status": "verified"}}, upsert=True))
    c.portal.call(lambda: db.wallets.delete_many({"user_id": u["id"]}))
    c.portal.call(lambda: db.wallets.insert_one({"id": new_id(), "user_id": u["id"], "available_balance": 100.1, "pending_balance": 0.0,
                                                 "total_earned": 100.1, "total_withdrawn": 0.0, "active": True,
                                                 "created_at": now_iso(), "updated_at": now_iso()}))
    h = _hdr(u["id"])
    assert c.post("/api/withdrawals", json={"amount": 100.11}, headers=h).status_code == 400      # one paisa too much
    r = c.post("/api/withdrawals", json={"amount": 100.10}, headers=h)
    assert r.status_code == 200 and r.json()["amount_paise"] == 10010
    raw = c.portal.call(lambda: db.wallets.find_one({"user_id": u["id"]}))
    assert raw["available_balance_paise"] == 0 and raw["pending_balance_paise"] == 10010
    assert c.post("/api/withdrawals", json={"amount": 0.01}, headers=h).status_code == 400
    assert c.post("/api/withdrawals", json={"amount": 0}, headers=h).status_code == 422


# ============================================================ refunds reconcile to the paisa
def test_partial_and_final_refunds_claw_back_exactly_what_was_credited(c):
    p = _product(c, "M-3", 33.33)
    pend = lambda uid: c.portal.call(lambda: db.wallets.find_one({"user_id": uid}) or {"pending_balance_paise": 0})["pending_balance_paise"]
    start = {u["id"]: pend(u["id"]) for u in (S["seller"], S["ref"], S["team"])}     # wallets already hold earlier tests' credits
    o = _order(c, p["id"], 3)                                  # total 104.99, base 99.99
    _pay(c, o)
    credited = {r["user_id"]: r["amount_paise"] for r in c.portal.call(lambda: db.commissions.find({"order_id": o["id"]}).to_list(10))}
    assert sum(credited.values()) == 4500
    refunded = 0
    for ref, amt in (("R1", 10.0), ("R2", 33.33), ("R3", 0.01), ("R4", None)):    # last one closes the order
        res = c.portal.call(lambda ref=ref, amt=amt: shop_routes.reverse_order_financials(o["id"], {"id": S["admin"]["id"]}, None, amt, ref, "t"))
        refunded += to_paise(res["refund_amount"])
    assert refunded == 10499
    order = c.portal.call(lambda: db.orders.find_one({"id": o["id"]}))
    assert order["refunded_paise"] == 10499 and order["payment_status"] == "refunded" and order["refunded_amount"] == 104.99
    for row in c.portal.call(lambda: db.commissions.find({"order_id": o["id"]}).to_list(10)):
        assert row["reversed_paise"] == row["amount_paise"] and row["status"] == "REVERSED"      # exactly, never 1 paisa short/over
    for uid in credited:
        assert pend(uid) == start[uid]                         # this order's credits were removed exactly, nothing else touched


def test_refund_cannot_exceed_the_order_and_duplicates_are_ignored(c):
    p = _product(c, "M-4", 100)
    o = _order(c, p["id"], 1)
    _pay(c, o)
    run = lambda ref, amt: c.portal.call(lambda: shop_routes.reverse_order_financials(o["id"], {"id": "a"}, None, amt, ref, "t"))
    assert run("X1", 50.0)["refund_amount"] == 50.0
    assert run("X1", 50.0).get("duplicate") is True                                              # same reference: no double refund
    assert run("X2", 999.0)["refund_amount"] == 55.0                                              # capped at what is left (105 - 50)
    assert run("X3", 1.0)["refund_amount"] == 0.0 and c.portal.call(lambda: db.orders.find_one({"id": o["id"]}))["refunded_paise"] == 10500


def test_admin_refund_endpoint_validates_in_paise(c):
    p = _product(c, "M-5", 100)
    o = _order(c, p["id"], 1)
    _pay(c, o)
    h = _hdr(S["admin"]["id"])
    assert c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "R", "amount": 105.01}, headers=h).status_code == 400
    assert c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "R", "amount": 0}, headers=h).status_code == 400
    assert c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "R2", "amount": 105.0}, headers=h).status_code == 200
    assert c.portal.call(lambda: db.orders.find_one({"id": o["id"]}))["status"] == "refunded"


# ============================================================ migration
LEGACY_ORDER = {"id": "legacy-o1", "order_number": "ORDLEG1", "user_id": "u", "subtotal": 99.99, "gst_amount": 5.0, "total": 104.99,
                "cod_fee": 0.0, "refunded_amount": 10.0, "status": "delivered", "payment_status": "partially_refunded",
                "items": [{"product_id": "p", "price": 33.33, "total": 99.99, "quantity": 3}]}


def _legacy_seed(c):
    async def seed():
        for coll in ("orders", "commissions", "wallet_transactions", "wallets", "withdrawal_requests", "order_refunds"):
            await db[coll].delete_many({"id": {"$regex": "^legacy-"}})
        await db.orders.insert_one(copy.deepcopy(LEGACY_ORDER))
        await db.commissions.insert_one({"id": "legacy-c1", "order_id": "legacy-o1", "amount": 30.0, "base_amount": 99.99, "reversed_amount": 3.0})
        await db.commissions.insert_one({"id": "legacy-c2", "order_id": "legacy-o1", "amount": 0.30000000000000004, "base_amount": 99.99})  # unclean float
        await db.wallet_transactions.insert_one({"id": "legacy-t1", "user_id": "u", "amount": 30.0})
        await db.wallets.insert_one({"id": "legacy-w1", "user_id": "legacy-u", "available_balance": 12.34, "pending_balance": 0.1,
                                     "total_earned": 99.9, "total_withdrawn": 0.0})
        await db.withdrawal_requests.insert_one({"id": "legacy-wd1", "user_id": "u", "amount": 500.0})
        await db.order_refunds.insert_one({"_id": "legacy-r1", "id": "legacy-r1", "order_id": "legacy-o1", "amount": 10.0})
    c.portal.call(seed)


def test_migration_dry_run_changes_nothing_and_flags_unclean_values(c):
    _legacy_seed(c)
    before = c.portal.call(lambda: db.orders.find_one({"id": "legacy-o1"}, {"_id": 0}))
    plan = c.portal.call(lambda: mm.plan(db))
    assert plan["orders"]["to_add"] >= 5 and plan["commissions"]["unclean_count"] >= 1
    assert any(u["id"] == "legacy-c2" for u in plan["commissions"]["unclean_values"])
    assert c.portal.call(lambda: db.orders.find_one({"id": "legacy-o1"}, {"_id": 0})) == before     # plan is read-only


def test_migration_is_additive_idempotent_and_reconciles(c):
    _legacy_seed(c)
    snap = lambda: {f"{k}:{i}": c.portal.call(lambda k=k, i=i: db[k].find_one({"id": i}, {"_id": 0})) for k, i in
                    (("orders", "legacy-o1"), ("commissions", "legacy-c1"), ("commissions", "legacy-c2"), ("wallet_transactions", "legacy-t1"),
                     ("wallets", "legacy-w1"), ("withdrawal_requests", "legacy-wd1"))}
    before = snap()
    added = c.portal.call(lambda: mm.apply(db, "test"))
    assert added["orders"] >= 5 and added["wallets"] >= 4
    after = snap()
    for k, doc in after.items():
        for field, value in before[k].items():
            if field == "items":
                assert [{a: b for a, b in it.items() if not a.endswith("_paise")} for it in doc[field]] == value   # items: originals kept
            else:
                assert doc[field] == value, (k, field)                          # EVERY original field is byte-for-byte unchanged
    o = after["orders:legacy-o1"]
    assert (o["subtotal_paise"], o["gst_paise"], o["total_paise"], o["cod_fee_paise"], o["refunded_paise"]) == (9999, 500, 10499, 0, 1000)
    assert o["items"][0]["price_paise"] == 3333 and o["items"][0]["total_paise"] == 9999
    assert after["commissions:legacy-c1"]["amount_paise"] == 3000 and after["commissions:legacy-c1"]["reversed_paise"] == 300
    assert after["commissions:legacy-c2"]["amount_paise"] == 30                              # 0.30000000000000004 -> 30 paise (float untouched)
    assert after["commissions:legacy-c2"]["amount"] == 0.30000000000000004
    assert after["wallets:legacy-w1"]["available_balance_paise"] == 1234 and after["wallets:legacy-w1"]["pending_balance_paise"] == 10
    assert c.portal.call(lambda: mm.apply(db, "again")) == {k: 0 for k in mm.FIELDS}      # second run adds nothing
    assert snap() == after
    rep = c.portal.call(lambda: mm.verify(db))
    assert rep["ok"] is True and rep["fields"]["orders.total"]["missing_paise"] == 0
    assert rep["fields"]["commissions.amount"]["unclean_values"] >= 1                        # reported, never silently hidden
    assert c.portal.call(lambda: db.money_migrations.count_documents({"kind": "money_paise_backfill"})) >= 2


def test_verify_fails_loudly_when_a_total_does_not_reconcile(c):
    _legacy_seed(c)
    c.portal.call(lambda: mm.apply(db, "t"))
    c.portal.call(lambda: db.orders.update_one({"id": "legacy-o1"}, {"$set": {"total_paise": 10498}}))   # corrupt one twin
    rep = c.portal.call(lambda: mm.verify(db))
    assert rep["ok"] is False and rep["fields"]["orders.total"]["ok"] is False
