"""Phase 3B.4: commission role eligibility (distributor AND green), vendor conversion, finance reports, negative wallets and
withdrawal payment safety. Integration: THROWAWAY MongoDB. Run in its own process: `pytest tests/test_role_eligibility_wallets.py -n 0`.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_role_wallets_test", "JWT_SECRET": "role-wallets-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import admin_routes  # noqa: E402
import shop_routes  # noqa: E402
from commission import distribute_sale_commissions, release_due_points  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
from wallet_reconcile import expected_aggregates  # noqa: E402

S = {}
ADDR = {"full_name": "A", "mobile": "9000000000", "line1": "x", "city": "c", "state": "s", "pincode": "110001"}
ROLES = {"vendor": "vendor", "vendor_staff": "vendor_staff", "super_admin": "super_admin", "admin": "admin",
         "accounts_admin": "accounts_admin", "support_admin": "support_admin"}
OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _u(key, role="distributor", status="green", sponsor=None):
    uid = new_id()
    S[key] = uid
    return {"id": uid, "distributor_id": ("E" + uid[:7]).upper(), "full_name": key, "mobile": "7" + f"{abs(hash(uid)) % 10**9:09d}",
            "email": f"{key}-{uid[:5]}@example.com", "password_hash": hash_password("x" * 12), "role": role, "status": status,
            "account_status": "active", "sponsor_user_id": sponsor, "created_at": now_iso(), "updated_at": now_iso()}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            docs = []
            for key, role in {**ROLES, "green": "distributor", "red": "distributor"}.items():
                up = _u(f"{key}_up")                                          # an eligible distributor above
                me = _u(key, role, "red" if key == "red" else "green", sponsor=up["id"])
                d1 = _u(f"{key}_d1", sponsor=me["id"])                        # role under test as referrer
                d2 = _u(f"{key}_d2", sponsor=d1["id"])                        # role under test as team
                docs += [up, me, d1, d2]
            conv_up = _u("conv_up")
            conv = _u("conv", sponsor=conv_up["id"])
            docs += [conv_up, conv, _u("conv_d1", sponsor=conv["id"]), _u("buyer"), _u("hg"), _u("fin", "accounts_admin"),
                     _u("sup", "super_admin"), _u("adm", "admin"), _u("support", "support_admin")]
            await db.users.insert_many(docs)
            await db.kyc_records.insert_one({"user_id": S["hg"], "status": "verified"})
            await db.products.insert_one({"id": "P1", "sku": "P1", "name": "Saree", "images": [], "mrp": 1100, "selling_price": 1000,
                                          "gst_percent": 5, "stock": 100000, "category": "Sarees", "options": [], "vendor_id": None,
                                          "is_active": True, "approval_status": "approved", "created_at": now_iso()})
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _did(c, key):
    return _run(c, lambda: db.users.find_one({"id": S[key]}))["distributor_id"]


def _shop(c, ref_key, buyer="buyer"):
    """A real order through POST /api/orders with a share code, then paid and distributed."""
    r = c.post("/api/orders", json={"items": [{"product_id": "P1", "quantity": 1}], "address": ADDR, "payment_method": "online",
                                    "seller_ref": _did(c, ref_key)}, headers=_hdr(S[buyer]))
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"payment_status": "paid", "paid_at": now_iso()}}))
    o = _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))
    b = _run(c, lambda: db.users.find_one({"id": S[buyer]}, {"_id": 0}))
    _run(c, lambda: distribute_sale_commissions(o, b))
    return o


def _comms(c, oid):
    return {(x["type"], x["user_id"]): x for x in _run(c, lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10))}


# ================================================================ role eligibility, every role in every position
def test_a_green_distributor_earns_in_every_position(c):
    o = _shop(c, "green")
    assert o["seller_user_id"] == S["green"] and ("COMMISSION_DIRECT", S["green"]) in _comms(c, o["id"])
    assert ("COMMISSION_REFERRAL", S["green"]) in _comms(c, _shop(c, "green_d1")["id"])
    assert ("COMMISSION_TEAM", S["green"]) in _comms(c, _shop(c, "green_d2")["id"])
    assert _run(c, lambda: db.commission_plans.find_one({"_id": o["id"]}))["eligibility_rule"] == "distributor_green_v1"


@pytest.mark.parametrize("key", ["red", *ROLES])
def test_ineligible_roles_earn_nothing_new_and_their_share_is_not_redirected(c, key):
    o = _shop(c, key)                                                        # as share-link seller
    assert o.get("seller_user_id") is None and _comms(c, o["id"]) == {}     # no attribution, so no commission at all
    ref = _comms(c, _shop(c, f"{key}_d1")["id"])                             # as referrer
    if key == "red":   # unchanged pre-3B.4 behaviour: the chain stops at a red (non-green) referrer, so no team share either
        assert set(ref) == {("COMMISSION_DIRECT", S[f"{key}_d1"])}
    else:              # a green non-distributor referrer is skipped; the team upline keeps its share, nothing is redirected
        assert set(ref) == {("COMMISSION_DIRECT", S[f"{key}_d1"]), ("COMMISSION_TEAM", S[f"{key}_up"])}
        assert ref[("COMMISSION_TEAM", S[f"{key}_up"])]["amount_paise"] == 5000
    assert ref[("COMMISSION_DIRECT", S[f"{key}_d1"])]["amount_paise"] == 30000
    team = _comms(c, _shop(c, f"{key}_d2")["id"])                            # as team
    assert set(team) == {("COMMISSION_DIRECT", S[f"{key}_d2"]), ("COMMISSION_REFERRAL", S[f"{key}_d1"])}


def test_an_ineligible_seller_on_an_existing_order_earns_nothing_at_distribution_either(c):
    """Defence in depth: even an order already attributed to a vendor (historical data) earns no new direct commission."""
    oid = new_id()
    o = {"id": oid, "order_number": "RE-" + oid[:5], "user_id": S["buyer"], "seller_user_id": S["vendor"], "payment_method": "online",
         "payment_status": "paid", "status": "delivered", "subtotal": 1000.0, "subtotal_paise": 100000, "total": 1050.0, "total_paise": 105000,
         "fulfilments": [], "items": [], "paid_at": now_iso(), "created_at": now_iso()}
    _run(c, lambda: db.orders.insert_one(dict(o)))
    b = _run(c, lambda: db.users.find_one({"id": S["buyer"]}, {"_id": 0}))
    _run(c, lambda: distribute_sale_commissions(o, b))
    assert _comms(c, oid) == {} and _run(c, lambda: db.orders.find_one({"id": oid}))["commission_note"] == "seller_not_approved"


def test_own_purchase_protection_still_holds(c):
    o = _shop(c, "green_d1", buyer="green")                                 # the buyer is the seller's referrer
    assert set(_comms(c, o["id"])) == {("COMMISSION_DIRECT", S["green_d1"]), ("COMMISSION_TEAM", S["green_up"])}


# ================================================================ distributor converted to vendor
def test_conversion_stops_new_earnings_and_leaves_earlier_commissions_untouched(c):
    before_direct = _shop(c, "conv")
    before_ref = _shop(c, "conv_d1")
    earlier = {k: v for k, v in _run(c, lambda: db.commissions.find({"user_id": S["conv"]}, {"_id": 0}).to_list(10)) and
               {x["id"]: x for x in _run(c, lambda: db.commissions.find({"user_id": S["conv"]}, {"_id": 0}).to_list(10))}.items()}
    assert len(earlier) == 2 and ("COMMISSION_DIRECT", S["conv"]) in _comms(c, before_direct["id"])
    assert ("COMMISSION_REFERRAL", S["conv"]) in _comms(c, before_ref["id"])
    wallet_before = _run(c, lambda: db.wallets.find_one({"user_id": S["conv"]}, {"_id": 0, "pending_balance_paise": 1}))
    assert c.post("/api/admin/vendors/invite", headers=_hdr(S["adm"]), json={"identifier": _did(c, "conv")}).status_code == 200
    after_direct = _shop(c, "conv")
    after_ref = _shop(c, "conv_d1")
    assert after_direct.get("seller_user_id") is None and _comms(c, after_direct["id"]) == {}
    assert set(_comms(c, after_ref["id"])) == {("COMMISSION_DIRECT", S["conv_d1"]), ("COMMISSION_TEAM", S["conv_up"])}
    now = {x["id"]: x for x in _run(c, lambda: db.commissions.find({"user_id": S["conv"]}, {"_id": 0}).to_list(10))}
    assert now == earlier                                                    # nothing recalculated, reversed or replayed
    assert _run(c, lambda: db.wallets.find_one({"user_id": S["conv"]}, {"_id": 0, "pending_balance_paise": 1})) == wallet_before


# ================================================================ read-only finance reports
def _snapshot(c):
    return (_run(c, lambda: db.commissions.count_documents({})), _run(c, lambda: db.wallets.find({}, {"_id": 0, "applied_ops": 0}).sort("user_id", 1).to_list(1000)),
            _run(c, lambda: db.wallet_transactions.count_documents({})))


def test_historical_commissions_to_non_distributors_are_listed_read_only_and_finance_only(c):
    oid = new_id()                                                           # a commission frozen before enforcement existed
    _run(c, lambda: db.commission_plans.insert_one({"_id": oid, "order_id": oid, "order_number": "HIST-1", "items": [], "base": 1000.0,
                                                    "base_paise": 100000, "window": 7, "created_at": OLD, "completed_at": OLD}))
    _run(c, lambda: db.commissions.insert_one({"_id": f"dist:{oid}:COMMISSION_DIRECT", "id": f"dist:{oid}:COMMISSION_DIRECT", "order_id": oid,
                                               "order_number": "HIST-1", "user_id": S["vendor"], "type": "COMMISSION_DIRECT", "status": "RELEASED",
                                               "amount_paise": 30000, "amount": 300.0, "created_at": OLD, "released_at": OLD}))
    before = _snapshot(c)
    r = c.get("/api/admin/finance/non-distributor-commissions", headers=_hdr(S["fin"]))
    assert r.status_code == 200
    row = next(i for i in r.json()["items"] if i["order_id"] == oid)
    assert row["recipient_role"] == "vendor" and row["status"] == "RELEASED" and row["amount_paise"] == 30000 and row["order_number"] == "HIST-1"
    assert row["created_before_enforcement"] is True and row["frozen"] is True
    conv_rows = [i for i in r.json()["items"] if i["user_id"] == S["conv"]]
    assert conv_rows and all(i["recipient_role"] == "vendor" and i["created_before_enforcement"] is False for i in conv_rows)
    assert _snapshot(c) == before
    for who in ("adm", "support", "hg"):
        assert c.get("/api/admin/finance/non-distributor-commissions", headers=_hdr(S[who])).status_code == 403
        assert c.get("/api/admin/finance/negative-wallets", headers=_hdr(S[who])).status_code == 403


# ================================================================ negative wallets and withdrawal payment safety
def _w(c, key="hg"):
    w = _run(c, lambda: db.wallets.find_one({"user_id": S[key]}, {"_id": 0})) or {}
    return {f: w.get(f + "_paise", 0) for f in ("pending_balance", "available_balance", "total_earned", "total_withdrawn")}


def _sale(c, key="hg", sub=1000.0, release=True):
    oid = new_id()
    sp = round(sub * 100)
    o = {"id": oid, "order_number": "NW-" + oid[:5], "user_id": S["buyer"], "seller_user_id": S[key], "payment_method": "online",
         "payment_status": "paid", "status": "delivered", "subtotal": sub, "subtotal_paise": sp, "total": sub * 1.05, "total_paise": round(sp * 1.05),
         "fulfilments": [], "items": [], "refunded_paise": 0, "refunded_amount": 0.0, "paid_at": now_iso(), "created_at": now_iso()}
    _run(c, lambda: db.orders.insert_one(dict(o)))
    b = _run(c, lambda: db.users.find_one({"id": S["buyer"]}, {"_id": 0}))
    _run(c, lambda: distribute_sale_commissions(o, b))
    if release:
        _run(c, lambda: db.commissions.update_many({"order_id": oid}, {"$set": {"created_at": OLD}}))
        _run(c, release_due_points)
    return oid


def _refund(c, oid):
    return _run(c, lambda: shop_routes.reverse_order_financials(oid, {"id": S["fin"]}, None, reference="RF-" + new_id()[:6], reason="t"))


def _withdraw(c, amount, key="hg"):
    return c.post("/api/withdrawals", headers=_hdr(S[key]), json={"amount": amount})


def _review(c, wid, action, who="fin"):
    body = {"action": action, "note": "test"}
    if action == "mark_paid":
        body["payout_reference"] = "UTR-" + wid[:12]
        approved = _run(c, lambda: db.withdrawal_requests.find_one({"id": wid}))
        if approved and approved.get("status") in ("pending", "under_review"):   # Phase 3B.4.1: approval (by another user) comes first
            assert c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S["sup"]), json={"action": "approve"}).status_code == 200
    return c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S[who]), json=body)


def _approve(c, wid, who="sup"):
    assert c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S[who]), json={"action": "approve"}).status_code == 200


def _pay_model(wid):
    return admin_routes.WithdrawalReview(action="mark_paid", payout_reference="UTR-" + wid[:12])


def _consistent(c, key="hg"):
    rows = _run(c, lambda: db.wallet_transactions.find({"user_id": S[key]}, {"_id": 0}).to_list(5000))
    exp = expected_aggregates(rows)
    act = _w(c, key)
    return {f: (exp[f], act[f]) for f in exp if exp[f] != act[f]}


def _drain(c):
    """Bring hg's wallet back to zero available for an isolated scenario (withdraw and pay whatever is available)."""
    a = _w(c)["available_balance"]
    if a > 0:
        wid = _withdraw(c, a / 100).json()["id"]
        assert _review(c, wid, "mark_paid").status_code == 200


def test_pending_clawback_is_safe_and_released_clawback_can_go_negative_then_future_earnings_net_it(c):
    _drain(c)
    start = _w(c)
    oid = _sale(c, release=False)
    _refund(c, oid)
    assert _w(c) == start                                                     # pending credited and fully taken back
    oid = _sale(c)
    wid = _withdraw(c, 300.0).json()["id"]
    _refund(c, oid)
    w = _w(c)
    assert w["available_balance"] == start["available_balance"] - 30000 and w["pending_balance"] == start["pending_balance"] + 30000
    assert _withdraw(c, 1.0).status_code == 400                              # no new withdrawal while negative
    rep = c.get("/api/admin/finance/negative-wallets", headers=_hdr(S["fin"])).json()["items"]
    row = next(i for i in rep if i["user_id"] == S["hg"])
    assert row["deficit_paise"] == 30000 and row["user"]["role"] == "distributor" and row["pending_balance_paise"] == w["pending_balance"]
    assert row["recent_clawbacks"] and any(x["id"] == wid for x in row["open_withdrawals"])
    # W7 closed: the reserved withdrawal cannot be paid now, and a retry of the refusal changes nothing
    for _ in range(2):
        r = _review(c, wid, "mark_paid")
        assert r.status_code == 409 and "cannot be paid" in r.text
        assert _w(c) == w and _run(c, lambda: db.withdrawal_requests.find_one({"id": wid}))["status"] == "approved"
    # future earnings net the deficit; then the reserved withdrawal is safe and can be paid once
    _sale(c, sub=2000.0)
    assert _w(c)["available_balance"] == start["available_balance"] + 30000
    assert _review(c, wid, "mark_paid").status_code == 200
    again = _review(c, wid, "mark_paid")
    assert again.status_code == 200 and again.json().get("already") is True
    final = _w(c)
    assert final["total_withdrawn"] == start["total_withdrawn"] + 30000 and final["pending_balance"] == start["pending_balance"]
    assert _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"withdrawal_paid:{wid}"})) == 1
    assert _consistent(c) == {}


def test_rejecting_a_reserved_withdrawal_after_a_clawback_returns_the_reservation(c):
    _drain(c)
    start = _w(c)
    oid = _sale(c)
    wid = _withdraw(c, 300.0).json()["id"]
    _approve(c, wid)
    _refund(c, oid)
    assert _review(c, wid, "mark_paid").status_code == 409
    assert _review(c, wid, "reject").status_code == 200
    w = _w(c)
    assert w["available_balance"] == start["available_balance"] and w["pending_balance"] == start["pending_balance"]
    assert _review(c, wid, "mark_paid").status_code in (400, 409) and _review(c, wid, "reject").json().get("already") is True
    assert _w(c) == w and _consistent(c) == {}


def test_concurrent_pay_attempts_pay_once(c):
    _drain(c)
    start = _w(c)
    _sale(c)
    wid = _withdraw(c, 300.0).json()["id"]
    _approve(c, wid)
    fin = {"id": S["fin"], "role": "accounts_admin"}

    async def race():
        return await asyncio.gather(*[admin_routes.review_withdrawal(wid, _pay_model(wid), None, admin=fin)
                                      for _ in range(4)], return_exceptions=True)
    _run(c, race)
    w = _w(c)
    assert w["total_withdrawn"] == start["total_withdrawn"] + 30000 and w["pending_balance"] == start["pending_balance"]
    assert _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"withdrawal_paid:{wid}"})) == 1
    assert _run(c, lambda: db.withdrawal_requests.find_one({"id": wid}))["status"] == "paid" and _consistent(c) == {}


def test_concurrent_pay_and_reject_apply_exactly_one(c):
    _drain(c)
    start = _w(c)
    _sale(c)
    wid = _withdraw(c, 300.0).json()["id"]
    _approve(c, wid)
    fin = {"id": S["fin"], "role": "accounts_admin"}

    async def race():
        return await asyncio.gather(admin_routes.review_withdrawal(wid, _pay_model(wid), None, admin=fin),
                                    admin_routes.review_withdrawal(wid, admin_routes.WithdrawalReview(action="reject"), None, admin=fin),
                                    return_exceptions=True)
    _run(c, race)
    ops = _run(c, lambda: db.wallets.find_one({"user_id": S["hg"]}))["applied_ops"]
    assert (f"withdrawal_paid:{wid}" in ops) != (f"withdrawal_rejected:{wid}" in ops)
    status = _run(c, lambda: db.withdrawal_requests.find_one({"id": wid}))["status"]
    w = _w(c)
    if status == "paid":
        assert w["total_withdrawn"] == start["total_withdrawn"] + 30000 and w["available_balance"] == start["available_balance"]
    else:
        assert status == "rejected" and w["total_withdrawn"] == start["total_withdrawn"] and w["available_balance"] == start["available_balance"] + 30000
    assert w["pending_balance"] == start["pending_balance"] and _consistent(c) == {}


def test_a_refund_racing_a_payment_never_pays_unsafely_or_twice(c):
    _drain(c)
    start = _w(c)
    oid = _sale(c)
    wid = _withdraw(c, 300.0).json()["id"]
    _approve(c, wid)
    fin = {"id": S["fin"], "role": "accounts_admin"}

    async def race():
        return await asyncio.gather(
            shop_routes.reverse_order_financials(oid, fin, None, reference="RACE-" + new_id()[:6], reason="t"),
            admin_routes.review_withdrawal(wid, _pay_model(wid), None, admin=fin),
            return_exceptions=True)
    _run(c, race)
    status = _run(c, lambda: db.withdrawal_requests.find_one({"id": wid}))["status"]
    w = _w(c)
    paid_rows = _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"withdrawal_paid:{wid}"}))
    assert paid_rows == (1 if status == "paid" else 0)
    if status == "paid":     # paid while still covered; the later clawback is then netted like any other
        assert w["total_withdrawn"] == start["total_withdrawn"] + 30000 and w["available_balance"] == start["available_balance"] - 30000
    else:                    # the clawback landed first: payment refused, reservation still held
        assert status == "approved" and w["pending_balance"] == start["pending_balance"] + 30000
    assert _consistent(c) == {}
