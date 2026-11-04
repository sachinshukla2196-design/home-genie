"""Phase 3B.1: activation review (RED -> GREEN) and commission recipient integrity. Integration: needs a THROWAWAY MongoDB.

Run in its own process: `pytest tests/test_activation.py -n 0`.
"""
import asyncio
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_activation_test", "JWT_SECRET": "activation-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import activation_routes  # noqa: E402
from commission import distribute_sale_commissions  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Activation-Pass-1234"
S = {}
COD_EVIDENCE = {"type": "courier_confirmation", "reference": "AWB-ACT-1", "recorded_by": "x", "verified_by_system": False}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _person(key, role="distributor", status="green", sponsor=None):
    uid = new_id()
    S[key] = uid
    return {"id": uid, "distributor_id": "A" + uid[:7].upper(), "full_name": key, "mobile": "9" + f"{abs(hash(uid)) % 10**9:09d}",
            "email": f"{key}-{uid[:6]}@example.com", "password_hash": hash_password(PW), "role": role, "status": status,
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
            people = [team, referrer, seller, _person("buyer"), _person("admin", role="admin"), _person("super", role="super_admin"),
                      _person("finance", role="accounts_admin"), _person("support", role="support_admin"), _person("vendor", role="vendor"),
                      _person("other", role="distributor")]
            await db.users.insert_many([dict(u) for u in people])
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _red(c, key):
    p = _person(key, status="red")
    c.portal.call(lambda: db.users.insert_one(dict(p)))
    return p["id"]


def _order(c, user_id, subtotal=2500.0, method="online", pstatus="paid", seller=None, **extra):
    oid = new_id()
    sub_p = round(subtotal * 100)
    total_p = sub_p + round(sub_p * 0.05) + (4900 if method == "cod" else 0)
    o = {"id": oid, "order_number": "AC-" + oid[:6].upper(), "user_id": user_id, "seller_user_id": seller,
         "payment_method": method, "payment_status": pstatus, "status": "processing", "subtotal": sub_p / 100, "subtotal_paise": sub_p,
         "total": total_p / 100, "total_paise": total_p, "fulfilments": [], "items": [], "refunded_paise": 0, "refunded_amount": 0.0,
         "paid_at": now_iso(), "created_at": now_iso(), **extra}
    if method == "cod" and "cod_collection" not in extra and pstatus == "paid":
        o["cod_collection"] = {**COD_EVIDENCE, "expected_paise": total_p, "collected_paise": total_p}
    c.portal.call(lambda: db.orders.insert_one(dict(o)))
    return oid


def _approve(c, who, uid, oid, note=""):
    return c.post(f"/api/admin/activations/{uid}/approve", headers=_hdr(S[who]), json={"order_id": oid, "note": note})


def _user(c, uid):
    return c.portal.call(lambda: db.users.find_one({"id": uid}, {"_id": 0}))


# ================================================================ activation: eligibility and approval
def test_a_red_user_with_a_qualifying_online_order_is_listed_for_review_and_not_activated_automatically(c):
    uid = _red(c, "r-online")
    oid = _order(c, uid, 2500.0)
    items = c.get("/api/admin/activations", headers=_hdr(S["admin"])).json()["items"]
    row = next(i for i in items if i["user"]["id"] == uid)
    assert row["qualifying_orders"][0]["order_id"] == oid and row["qualifying_orders"][0]["subtotal"] == 2500.0
    assert _user(c, uid)["status"] == "red"                                  # reaching 2,500 does not activate


def test_below_threshold_and_gst_inclusive_amounts_do_not_qualify(c):
    uid = _red(c, "r-below")
    small = _order(c, uid, 2499.99)                                          # total (with GST) is above 2,500, the subtotal is not
    assert _order_total(c, small) > 2500
    assert all(i["user"]["id"] != uid for i in c.get("/api/admin/activations", headers=_hdr(S["admin"])).json()["items"])
    r = _approve(c, "admin", uid, small)
    assert r.status_code == 409 and "subtotal_below_minimum" in r.text
    assert _user(c, uid)["status"] == "red"


def _order_total(c, oid):
    return c.portal.call(lambda: db.orders.find_one({"id": oid}))["total"]


@pytest.mark.parametrize("case", ["held", "short", "unproven", "manual"])
def test_cod_that_is_not_fully_proven_does_not_qualify(c, case):
    uid = _red(c, "r-cod-" + case)
    if case == "held":
        oid = _order(c, uid, method="cod", pstatus="cod_discrepancy")
    elif case == "short":
        oid = _order(c, uid, method="cod")
        c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$set": {"cod_collection.collected_paise": 100000}}))
    elif case == "unproven":
        oid = _order(c, uid, method="cod")
        c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$unset": {"cod_collection": ""}}))
    else:
        oid = _order(c, uid, method="cod", cod_collection={**COD_EVIDENCE, "type": "manual_exception", "expected_paise": 1, "collected_paise": 1})
    assert _approve(c, "admin", uid, oid).status_code == 409
    assert _user(c, uid)["status"] == "red"


def test_cod_with_proven_full_collection_qualifies_and_approval_records_everything(c):
    uid = _red(c, "r-cod-ok")
    oid = _order(c, uid, method="cod")
    r = _approve(c, "admin", uid, oid, note="Verified")
    assert r.status_code == 200 and r.json()["status"] == "green", r.text
    u = _user(c, uid)
    a = u["activation"]
    assert u["status"] == "green" and a["order_id"] == oid and a["subtotal_paise"] == 250000 and a["approved_by"] == S["admin"] and a["approved_at"]
    assert a["evidence"]["kind"] == "cod_collection" and a["evidence"]["evidence_reference"] == "AWB-ACT-1" and a["evidence"]["verified_by_system"] is False
    assert c.portal.call(lambda: db.activation_history.count_documents({"user_id": uid})) == 1
    assert c.portal.call(lambda: db.audit_logs.count_documents({"action": "homegenie_activated", "entity_id": uid})) >= 1


def test_duplicate_approval_changes_nothing(c):
    uid = _red(c, "r-dup")
    oid = _order(c, uid)
    assert _approve(c, "admin", uid, oid).status_code == 200
    first = _user(c, uid)["activation"]
    again = _approve(c, "super", uid, oid)
    assert again.status_code == 200 and again.json().get("already") is True
    assert _user(c, uid)["activation"] == first
    assert c.portal.call(lambda: db.activation_history.count_documents({"user_id": uid})) == 1


def test_two_concurrent_approvals_activate_once(c):
    uid = _red(c, "r-race")
    oid = _order(c, uid)
    admin = {"id": S["admin"], "role": "admin"}
    sup = {"id": S["super"], "role": "super_admin"}

    async def race():
        return await asyncio.gather(activation_routes.approve_activation(uid, None, admin=admin, body={"order_id": oid}),
                                    activation_routes.approve_activation(uid, None, admin=sup, body={"order_id": oid}))
    results = c.portal.call(race)
    assert sorted(bool(r.get("already")) for r in results) == [False, True]
    u = _user(c, uid)
    assert u["status"] == "green" and u["activation"]["approved_by"] in (S["admin"], S["super"])
    assert c.portal.call(lambda: db.activation_history.count_documents({"user_id": uid})) == 1


def test_an_already_green_user_is_not_changed(c):
    before = _user(c, S["seller"])
    oid = _order(c, S["seller"])
    r = _approve(c, "admin", S["seller"], oid)
    assert r.json().get("already") is True
    assert _user(c, S["seller"]) == before


def test_only_admin_and_super_admin_can_approve_and_you_cannot_approve_yourself(c):
    uid = _red(c, "r-auth")
    oid = _order(c, uid)
    for who in ("finance", "support", "vendor", "other", "buyer"):
        assert _approve(c, who, uid, oid).status_code == 403, who
    assert c.get("/api/admin/activations", headers=_hdr(S["finance"])).status_code == 403
    assert _user(c, uid)["status"] == "red"
    c.portal.call(lambda: db.users.update_one({"id": S["admin"]}, {"$set": {"status": "red"}}))
    try:
        own = _order(c, S["admin"])
        assert _approve(c, "admin", S["admin"], own).status_code == 403
    finally:
        c.portal.call(lambda: db.users.update_one({"id": S["admin"]}, {"$set": {"status": "green"}}))


def test_another_users_order_or_a_bad_body_cannot_activate(c):
    uid = _red(c, "r-wrong")
    theirs = _order(c, S["buyer"])
    assert _approve(c, "admin", uid, theirs).status_code == 404
    assert c.post(f"/api/admin/activations/{uid}/approve", headers=_hdr(S["admin"]), json={}).status_code == 422
    assert _user(c, uid)["status"] == "red"


def test_users_cannot_make_themselves_green_through_profile_updates(c):
    uid = _red(c, "r-self")
    r = c.put("/api/admin/users/" + uid, headers=_hdr(uid), json={"status": "green"})
    assert r.status_code in (401, 403)
    assert _user(c, uid)["status"] == "red"


# ================================================================ activation never creates or replays commission
def test_approval_does_not_replay_commission_for_the_activation_order(c):
    uid = _red(c, "r-noreplay")
    seller = c.portal.call(lambda: db.users.find_one({"id": S["seller"]}, {"_id": 0}))
    oid = _order(c, uid, seller=S["seller"])
    buyer = _user(c, uid)
    order = c.portal.call(lambda: db.orders.find_one({"id": oid}, {"_id": 0}))
    res = c.portal.call(lambda: distribute_sale_commissions(order, buyer))      # the commission event, while the buyer is still RED
    n_before = c.portal.call(lambda: db.commissions.count_documents({"order_id": oid}))
    assert _approve(c, "admin", uid, oid).status_code == 200
    green_buyer = _user(c, uid)
    again = c.portal.call(lambda: distribute_sale_commissions(order, green_buyer))
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": oid})) == n_before == 3 and seller
    assert again.get("credited") == 0 and res.get("credited") == 3


def test_an_order_whose_plan_was_frozen_for_a_red_seller_is_not_replayed_after_activation(c):
    uid = _red(c, "r-red-seller")
    buyer_order = _order(c, S["buyer"], seller=uid)
    order = c.portal.call(lambda: db.orders.find_one({"id": buyer_order}, {"_id": 0}))
    buyer = _user(c, S["buyer"])
    assert c.portal.call(lambda: distribute_sale_commissions(order, buyer)).get("credited") == 0      # seller RED at the event
    oid = _order(c, uid)
    assert _approve(c, "admin", uid, oid).status_code == 200
    assert c.portal.call(lambda: distribute_sale_commissions(order, buyer)).get("credited") == 0      # later GREEN does not retro-pay
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": buyer_order})) == 0


# ================================================================ own-purchase protection
def _paid_order(c, buyer_key, seller_key="seller"):
    oid = _order(c, S[buyer_key], 1000.0, seller=S[seller_key])
    return oid, c.portal.call(lambda: db.orders.find_one({"id": oid}, {"_id": 0})), c.portal.call(lambda: db.users.find_one({"id": S[buyer_key]}, {"_id": 0}))


def _types(c, oid):
    return sorted(x["type"] for x in c.portal.call(lambda: db.commissions.find({"order_id": oid}, {"_id": 0, "type": 1}).to_list(10)))


def test_a_normal_buyer_leaves_all_three_commissions_intact(c):
    oid, order, buyer = _paid_order(c, "buyer")
    assert c.portal.call(lambda: distribute_sale_commissions(order, buyer))["credited"] == 3
    assert _types(c, oid) == ["COMMISSION_DIRECT", "COMMISSION_REFERRAL", "COMMISSION_TEAM"]


def test_the_referral_recipient_earns_nothing_on_their_own_purchase_and_it_is_not_redirected(c):
    oid, order, buyer = _paid_order(c, "referrer")                           # buyer is the seller's sponsor
    assert c.portal.call(lambda: distribute_sale_commissions(order, buyer))["credited"] == 2
    assert _types(c, oid) == ["COMMISSION_DIRECT", "COMMISSION_TEAM"]
    assert not any(x["user_id"] == S["referrer"] for x in c.portal.call(lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10)))
    plan = c.portal.call(lambda: db.commission_plans.find_one({"_id": oid}))
    assert sorted(i["percent"] for i in plan["items"]) == [5.0, 30.0]
    assert sorted(i["amount_paise"] for i in plan["items"]) == [5000, 30000]          # 5% and 30% of 1,000.00; the 10% is simply unpaid


def test_the_team_recipient_earns_nothing_on_their_own_purchase(c):
    oid, order, buyer = _paid_order(c, "team")
    assert c.portal.call(lambda: distribute_sale_commissions(order, buyer))["credited"] == 2
    assert _types(c, oid) == ["COMMISSION_DIRECT", "COMMISSION_REFERRAL"]


def test_the_direct_recipient_earns_nothing_on_their_own_purchase_even_if_attribution_were_forced(c):
    oid, order, buyer = _paid_order(c, "seller")
    assert c.portal.call(lambda: distribute_sale_commissions(order, buyer))["credited"] == 0
    assert _types(c, oid) == []


def test_retry_after_a_skipped_recipient_does_not_duplicate_or_redirect(c):
    oid, order, buyer = _paid_order(c, "referrer")
    c.portal.call(lambda: distribute_sale_commissions(order, buyer))
    again = c.portal.call(lambda: distribute_sale_commissions(order, buyer))
    assert again.get("credited") == 0 and _types(c, oid) == ["COMMISSION_DIRECT", "COMMISSION_TEAM"]
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": oid})) == 2


def test_the_cod_proof_guard_still_applies_to_a_cod_order_with_a_legitimate_buyer(c):
    oid = _order(c, S["buyer"], 1000.0, method="cod", seller=S["seller"], cod_collection={**COD_EVIDENCE, "type": "manual_exception", "expected_paise": 1, "collected_paise": 1})
    order = c.portal.call(lambda: db.orders.find_one({"id": oid}, {"_id": 0}))
    buyer = _user(c, S["buyer"])
    assert c.portal.call(lambda: distribute_sale_commissions(order, buyer))["reason"] == "cod_collection_not_proven"


# ================================================================ Phase 3B.2: orders that stop qualifying
@pytest.mark.parametrize("change", [{"payment_status": "refunded", "refunded_paise": 262500}, {"payment_status": "partially_refunded", "refunded_paise": 1000},
                                    {"status": "cancelled"}, {"needs_refund": True}])
def test_an_order_that_is_refunded_cancelled_or_needs_refund_cannot_be_used_to_approve(c, change):
    uid = _red(c, "r-late-" + "-".join(change))
    oid = _order(c, uid)
    c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$set": change}))
    assert _approve(c, "admin", uid, oid).status_code == 409
    assert _user(c, uid)["status"] == "red"
    assert all(i["user"]["id"] != uid for i in c.get("/api/admin/activations", headers=_hdr(S["admin"])).json()["items"])


def test_a_refund_after_approval_leaves_the_user_green_and_unchanged_documented_current_behaviour(c):
    """No owner rule defines deactivation on refund, so none is invented: the approval stands and keeps its original record."""
    uid = _red(c, "r-refund-after")
    oid = _order(c, uid)
    assert _approve(c, "admin", uid, oid).status_code == 200
    record = _user(c, uid)["activation"]
    c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$set": {"payment_status": "refunded", "refunded_paise": 262500}}))
    u = _user(c, uid)
    assert u["status"] == "green" and u["activation"] == record
    assert _approve(c, "admin", uid, oid).json().get("already") is True


def test_the_activation_screen_and_endpoints_refuse_accounts_admin_by_direct_url(c):
    uid = _red(c, "r-fin-refused")
    oid = _order(c, uid)
    assert c.get("/api/admin/activations", headers=_hdr(S["finance"])).status_code == 403
    assert _approve(c, "finance", uid, oid).status_code == 403
    assert _user(c, uid)["status"] == "red"


def test_no_other_admin_route_can_set_a_distributor_green(c):
    uid = _red(c, "r-bypass")
    for path, method, body in ((f"/api/admin/users/{uid}", "put", {"status": "green"}), (f"/api/admin/users/{uid}", "put", {"role": "admin"})):
        r = getattr(c, method)(path, headers=_hdr(S["super"]), json=body)
        assert r.status_code in (200, 422)
        assert _user(c, uid)["status"] == "red" and _user(c, uid)["role"] == "distributor"


def test_vendor_role_conversion_is_separate_from_distributor_activation(c):
    """Inviting an account as a vendor changes its role (an intentional vendor grant). It is not an activation: the account
    leaves the distributor activation workflow, which then neither lists nor approves it."""
    uid = _red(c, "r-vendor-conv")
    did = _user(c, uid)["distributor_id"]
    oid = _order(c, uid)
    r = c.post("/api/admin/vendors/invite", headers=_hdr(S["admin"]), json={"identifier": did})
    assert r.status_code == 200, r.text
    u = _user(c, uid)
    assert u["role"] == "vendor" and "activation" not in u                    # no activation record was created
    assert _approve(c, "admin", uid, oid).status_code == 404                   # no longer a distributor
    assert all(i["user"]["id"] != uid for i in c.get("/api/admin/activations", headers=_hdr(S["admin"])).json()["items"])
