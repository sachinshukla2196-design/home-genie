"""Phase 3B.3: commission model integrity, funding detection, short-COD paths, settings controls. Integration: THROWAWAY MongoDB.

Run in its own process: `pytest tests/test_commission_model.py -n 0`.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_commission_model_test", "JWT_SECRET": "commission-model-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
from commission import distribute_sale_commissions, release_due_points, release_commission_now, resume_distribution  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
FULL_COD = {"type": "courier_confirmation", "reference": "AWB-CM", "recorded_by": "x", "verified_by_system": False}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _person(key, role="distributor", status="green", sponsor=None):
    uid = new_id()
    S[key] = uid
    return {"id": uid, "distributor_id": "Q" + uid[:7].upper(), "full_name": key, "mobile": "9" + f"{abs(hash(uid)) % 10**9:09d}",
            "email": f"{key}-{uid[:6]}@example.com", "password_hash": hash_password("x" * 12), "role": role, "status": status,
            "account_status": "active", "sponsor_user_id": sponsor, "created_at": now_iso(), "updated_at": now_iso()}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            team = _person("team")
            referrer = _person("referrer", sponsor=team["id"])
            seller = _person("seller", sponsor=referrer["id"])
            loop = _person("loop")
            loop["sponsor_user_id"] = loop["id"]                     # corrupt self-sponsoring record: the same person in two positions
            loop_seller = _person("loop_seller", sponsor=loop["id"])
            people = [team, referrer, seller, loop, loop_seller, _person("buyer"), _person("admin", role="admin"),
                      _person("super", role="super_admin"), _person("finance", role="accounts_admin"), _person("support", role="support_admin")]
            await db.users.insert_many([dict(u) for u in people])
            for vid, pct in (("V20", 20.0), ("V50", 50.0)):
                await db.vendor_agreements.insert_one({"id": new_id(), "vendor_id": vid, "status": "approved", "effective_from": "2020-01-01",
                                                       "commission_pct": pct, "fixed_fee_paise": 0, "version": 1})
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _order(c, buyer="buyer", seller="seller", sub=1000.0, method="online", vendor=None, cod=None, pstatus="paid"):
    oid = new_id()
    sp = round(sub * 100)
    total = sp + sp // 20
    items = [{"product_id": "p", "vendor_id": vendor, "total_paise": sp, "total": sub, "quantity": 1}] if vendor else []
    o = {"id": oid, "order_number": "CM-" + oid[:6].upper(), "user_id": S[buyer], "seller_user_id": S[seller], "payment_method": method,
         "payment_status": pstatus, "status": "delivered", "subtotal": sub, "subtotal_paise": sp, "total": total / 100, "total_paise": total,
         "fulfilments": [], "items": items, "refunded_paise": 0, "refunded_amount": 0.0, "paid_at": now_iso(), "created_at": now_iso()}
    if method == "cod":
        o["cod_collection"] = cod if cod is not None else {**FULL_COD, "expected_paise": total, "collected_paise": total}
    _run(c, lambda: db.orders.insert_one(dict(o)))
    return o


def _distribute(c, o, buyer="buyer"):
    b = _run(c, lambda: db.users.find_one({"id": S[buyer]}, {"_id": 0}))
    return _run(c, lambda: distribute_sale_commissions(o, b))


def _comms(c, oid):
    return _run(c, lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10))


def _plan(c, oid):
    return _run(c, lambda: db.commission_plans.find_one({"_id": oid}))


def _age(c, oid):
    _run(c, lambda: db.commissions.update_many({"order_id": oid}, {"$set": {"created_at": OLD}}))


# ================================================================ the formula itself is unchanged
def test_thirty_ten_five_on_the_pre_gst_subtotal_stacks_on_every_eligible_sale(c):
    for _ in range(2):                                                         # recurring, not first purchase only
        o = _order(c)
        assert _distribute(c, o)["credited"] == 3
        assert sorted((x["type"], x["amount_paise"]) for x in _comms(c, o["id"])) == [
            ("COMMISSION_DIRECT", 30000), ("COMMISSION_REFERRAL", 10000), ("COMMISSION_TEAM", 5000)]


def test_a_frozen_plan_keeps_its_rates_after_a_settings_change_and_new_orders_use_the_new_rates(c):
    o = _order(c)
    _distribute(c, o)
    assert c.put("/api/admin/settings", headers=_hdr(S["super"]), json={"commission_direct_pct": 25.0}).status_code == 200
    try:
        assert _run(c, lambda: resume_distribution(o["id"]))["credited"] == 0
        assert next(x for x in _comms(c, o["id"]) if x["type"] == "COMMISSION_DIRECT")["amount_paise"] == 30000
        n = _order(c)
        _distribute(c, n)
        assert next(x for x in _comms(c, n["id"]) if x["type"] == "COMMISSION_DIRECT")["amount_paise"] == 25000
    finally:
        assert c.put("/api/admin/settings", headers=_hdr(S["super"]), json={"commission_direct_pct": 30.0}).status_code == 200


# ================================================================ funding detection (flag only; nothing is clipped)
def test_company_owned_merchandise_is_recorded_as_sufficiently_funded(c):
    o = _order(c)
    _distribute(c, o)
    f = _plan(c, o["id"])["funding"]
    assert f["company_lines_paise"] == 100000 and f["platform_revenue_paise"] == 100000 and f["commission_paise"] == 45000
    assert f["sufficient"] is True and f["residual_paise"] == 55000 and f["cost_of_goods"] == "not_modelled"


@pytest.mark.parametrize("vendor,fee,sufficient", [("V20", 20000, False), ("V50", 50000, True), ("VNONE", 0, False)])
def test_vendor_merchandise_is_assessed_against_the_agreed_platform_fee_and_commission_is_never_clipped(c, vendor, fee, sufficient):
    o = _order(c, vendor=vendor)
    _distribute(c, o)
    f = _plan(c, o["id"])["funding"]
    assert f["vendor_lines_paise"] == 100000 and f["vendor_platform_fee_paise"] == fee and f["sufficient"] is sufficient
    assert f["residual_paise"] == fee - 45000
    assert f["vendors_without_agreement"] == (["VNONE"] if vendor == "VNONE" else [])
    assert sum(x["amount_paise"] for x in _comms(c, o["id"])) == 45000          # the earned commission is paid in full


def test_the_funding_report_lists_insufficient_plans_for_finance_only(c):
    o = _order(c, vendor="V20")
    _distribute(c, o)
    r = c.get("/api/admin/finance/commission-funding", headers=_hdr(S["finance"]))
    assert r.status_code == 200 and any(i["order_id"] == o["id"] for i in r.json()["items"])
    assert all(i["funding"]["sufficient"] is False for i in r.json()["items"])
    for who in ("admin", "support", "buyer"):
        assert c.get("/api/admin/finance/commission-funding", headers=_hdr(S[who])).status_code == 403


def test_a_historical_plan_without_a_snapshot_is_counted_as_unassessed_and_never_recalculated(c):
    o = _order(c)
    _run(c, lambda: db.commission_plans.insert_one({"_id": o["id"], "order_id": o["id"], "order_number": o["order_number"], "items": [],
                                                    "base_paise": 100000, "base": 1000.0, "window": 7, "created_at": now_iso(), "completed_at": None}))
    _distribute(c, o)
    assert "funding" not in _plan(c, o["id"]) and _comms(c, o["id"]) == []
    assert c.get("/api/admin/finance/commission-funding", headers=_hdr(S["finance"])).json()["unassessed_plans"] >= 1


# ================================================================ short and unproven COD: no path creates or releases commission
def _legacy_cod_commissions(c, mutate):
    """Commission created while COD was fully proven (or by a legacy path), then the order's evidence no longer proves it."""
    o = _order(c, method="cod")
    assert _distribute(c, o)["credited"] == 3
    _age(c, o["id"])
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": mutate}))
    return o


@pytest.mark.parametrize("mutate", [
    {"cod_collection.collected_paise": 50000, "cod_collected_paise": 50000, "cod_short_collected": True},  # short
    {"cod_collection.type": "manual_exception"},
    {"cod_collection": None},                                                                                 # legacy, no evidence
])
def test_cron_and_manual_release_never_release_unproven_or_short_cod(c, mutate):
    o = _legacy_cod_commissions(c, mutate)
    _run(c, release_due_points)
    assert all(x["released_at"] is None for x in _comms(c, o["id"]))
    for x in _comms(c, o["id"]):
        assert _run(c, lambda: release_commission_now(x["id"]))["ok"] is False
    assert _run(c, lambda: db.wallet_transactions.count_documents({"reference": o["id"], "type": "POINTS_RELEASED"})) == 0


@pytest.mark.parametrize("kind", ["short", "held", "manual", "legacy"])
def test_distribution_and_resume_never_create_commission_for_unproven_cod(c, kind):
    total = 105000
    cod = {"short": {**FULL_COD, "expected_paise": total, "collected_paise": 50000},
           "manual": {**FULL_COD, "type": "manual_exception", "expected_paise": total, "collected_paise": total},
           "held": None, "legacy": {}}[kind]
    o = _order(c, method="cod", cod=cod or {}, pstatus="cod_discrepancy" if kind == "held" else "paid")
    assert _distribute(c, o)["reason"] == "cod_collection_not_proven"
    assert _run(c, lambda: resume_distribution(o["id"]))["credited"] == 0 and _comms(c, o["id"]) == []


def test_proven_full_cod_releases_through_the_cron(c):
    o = _order(c, method="cod")
    _distribute(c, o)
    _age(c, o["id"])
    _run(c, release_due_points)
    assert all(x["released_at"] for x in _comms(c, o["id"]))


def test_cron_and_manual_release_racing_release_once(c):
    o = _order(c)
    _distribute(c, o)
    _age(c, o["id"])
    d = next(x for x in _comms(c, o["id"]) if x["type"] == "COMMISSION_DIRECT")

    async def race():
        return await asyncio.gather(release_due_points(), release_commission_now(d["id"]), release_commission_now(d["id"]), return_exceptions=True)
    _run(c, race)
    assert _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"release:{d['id']}"})) == 1
    ops = _run(c, lambda: db.wallets.find_one({"user_id": S["seller"]}, {"applied_ops": 1}))["applied_ops"]
    assert ops.count(f"release:{d['id']}") == 1


# ================================================================ own purchase in every position, retries and refunds
def test_buyer_in_two_positions_earns_nothing_and_nothing_is_redirected(c):
    o = _order(c, buyer="loop", seller="loop_seller")                         # loop is both referrer and team
    assert _distribute(c, o, buyer="loop")["credited"] == 1
    assert [(x["type"], x["user_id"]) for x in _comms(c, o["id"])] == [("COMMISSION_DIRECT", S["loop_seller"])]
    assert _distribute(c, o, buyer="loop")["credited"] == 0 and len(_comms(c, o["id"])) == 1


def test_a_refund_after_a_skipped_recipient_claws_back_only_what_was_paid(c):
    o = _order(c, buyer="referrer")
    assert _distribute(c, o, buyer="referrer")["credited"] == 2
    res = _run(c, lambda: shop_routes.reverse_order_financials(o["id"], {"id": S["super"]}, None, reference="CM-RF", reason="t"))
    assert res["reversed"] == 2
    assert sorted(x["status"] for x in _comms(c, o["id"])) == ["REVERSED", "REVERSED"]
    assert not any(x["user_id"] == S["referrer"] for x in _comms(c, o["id"]))


# ================================================================ settings: one authoritative formula, changed only by finance and only validly
@pytest.mark.parametrize("who", ["admin", "support"])
def test_non_finance_admins_cannot_change_money_policy_but_can_save_other_settings(c, who):
    before = c.get("/api/admin/settings", headers=_hdr(S["super"])).json()
    for field, value in (("commission_direct_pct", 31.0), ("return_window_days", 0), ("require_kyc_for_withdrawal", False),
                         ("points_withdrawal_enabled", not before["points_withdrawal_enabled"]), ("gst_percent", 12.0)):
        assert c.put("/api/admin/settings", headers=_hdr(S[who]), json={field: value}).status_code == 403, field
    same = {k: before[k] for k in ("commission_direct_pct", "commission_referral_pct", "commission_team_pct", "gst_percent")}
    assert c.put("/api/admin/settings", headers=_hdr(S[who]), json={**same, "company_phone": "0000"}).status_code == 200   # unchanged values pass
    after = c.get("/api/admin/settings", headers=_hdr(S["super"])).json()
    assert all(after[k] == before[k] for k in same) and after["require_kyc_for_withdrawal"] == before["require_kyc_for_withdrawal"]


@pytest.mark.parametrize("bad", [{"commission_direct_pct": 150.0}, {"commission_referral_pct": -10.0}, {"gst_percent": 101.0},
                                 {"commission_direct_pct": 60.0, "commission_referral_pct": 30.0, "commission_team_pct": 20.0},
                                 {"return_window_days": -1}, {"return_window_days": 400}, {"point_value": 0}, {"cod_fee": -1}])
def test_invalid_money_settings_are_refused_even_for_finance(c, bad):
    before = c.get("/api/admin/settings", headers=_hdr(S["super"])).json()
    assert c.put("/api/admin/settings", headers=_hdr(S["finance"]), json=bad).status_code == 422
    after = c.get("/api/admin/settings", headers=_hdr(S["super"])).json()
    assert all(after[k] == before[k] for k in bad)


def test_finance_can_make_a_valid_change_and_it_is_audited(c):
    assert c.put("/api/admin/settings", headers=_hdr(S["finance"]), json={"cod_fee": 50.0}).status_code == 200
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "settings_updated", "user_id": S["finance"], "new_value.cod_fee": 50.0})) >= 1
    assert c.put("/api/admin/settings", headers=_hdr(S["finance"]), json={"cod_fee": 49.0}).status_code == 200
