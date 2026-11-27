"""Programme 03: the financial reconciliation framework (reconciliation.py, GET /api/admin/finance/reconciliation).

A clean system reports ok in every domain; one injected defect per domain is reported in that domain (and only there);
the report never writes anything (every collection is fingerprinted before and after); it is finance-only and carries
no personal data. In-process, THROWAWAY database. Run in its own process: `pytest tests/test_p03_reconciliation.py -n 0`.
"""
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": os.environ.get("DB_NAME", "homegenies_p03_recon_test"), "JWT_SECRET": "p03recon-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from delivery_helper import deliver  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import ledger as L  # noqa: E402
import reconciliation  # noqa: E402
import withdrawal_intents as wi  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id, wallet_apply  # noqa: E402

ADDR = {"full_name": "Kiran Das", "mobile": "9000033333", "line1": "3 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
LONG_AGO = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
PII = ("kiran", "9000033333", "@example.com", "998877665544")


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role, status in (("cust", "customer", "customer"), ("hg", "distributor", "green"), ("fin", "accounts_admin", "green"),
                                      ("fin2", "super_admin", "green"), ("supp", "support_admin", "green"), ("vu", "vendor", "green")):
                u = {"id": new_id(), "distributor_id": "RC" + key.upper(), "full_name": key, "mobile": f"91000380{len(S):02d}",
                     "email": f"{key}@example.com", "password_hash": hash_password("Pass-1234x"), "role": role, "status": status,
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            await db.kyc_records.insert_one({"user_id": S["hg"]["id"], "status": "verified"})
            await wallet_apply(S["hg"]["id"], {"available_balance": 50000, "total_earned": 50000})
            await db.wallet_transactions.insert_one({"id": new_id(), "user_id": S["hg"]["id"], "type": "MANUAL_ADMIN_CREDIT", "direction": "credit",
                                                     "status": "CREDITED", "amount": 500.0, "amount_paise": 50000, "created_at": now_iso()})
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "RCV", "business_name": "Recon Vendor", "status": "approved",
                      "categories": ["Sarees"], "bank_account_name": "Recon Vendor", "bank_account": "998877665544", "ifsc": "SBIN0001234",
                      "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
            await db.products.insert_one({"id": "rcP", "sku": "RC-P", "name": "Saree", "images": [], "mrp": 900, "selling_price": 800,
                                          "gst_percent": 5, "stock": 100, "category": "Sarees", "options": [], "vendor_id": S["v"]["id"],
                                          "vendor_name": "Recon Vendor", "is_active": True, "approval_status": "approved", "created_at": now_iso()})
        client.portal.call(seed)
        assert client.put("/api/admin/finance/policy", headers=_hdr("fin"), json={"active": True, "require_dual_approval": True,
                                                                                   "min_settlement": 1}).status_code == 200
        # normal activity in every domain: a paid + delivered order, a member withdrawal, a settlement paid by two people
        o = _paid_order(client)
        _run(client, lambda: deliver(db, o["id"], LONG_AGO))
        r = client.post("/api/withdrawals", headers=_hdr("hg"), json={"amount": 120, "request_key": "recon-" + new_id()})
        assert r.status_code == 200, r.text
        sid = client.post("/api/admin/finance/settlements", headers=_hdr("fin"), json={"vendor_id": S["v"]["id"]}).json()["id"]
        assert client.post(f"/api/admin/finance/settlements/{sid}/action", headers=_hdr("fin2"), json={"action": "approve"}).status_code == 200
        assert client.post(f"/api/admin/finance/settlements/{sid}/action", headers=_hdr("fin"),
                           json={"action": "mark_paid", "reference": "UTR-RC-1"}).status_code == 200
        S["settlement"] = sid
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _paid_order(c):
    r = c.post("/api/orders", json={"items": [{"product_id": "rcP", "quantity": 1}], "address": ADDR, "payment_method": "online"},
               headers=_hdr("cust"))
    assert r.status_code == 200, r.text
    o = r.json()
    sid = "cs_rc_" + o["id"][:10]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "provider": "stripe", "status": "initiated",
                                                        "payment_status": "pending", "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    o["session_id"] = sid
    return o


def _report(c, domain=None):
    r = c.get("/api/admin/finance/reconciliation", params={"domain": domain} if domain else {}, headers=_hdr("fin"))
    assert r.status_code == 200, r.text
    return r.json()


def _fingerprint(c):
    async def go():
        out = {}
        for name in sorted(await db.list_collection_names()):
            docs = await db[name].find({}).to_list(None)
            out[name] = sorted(json.dumps(d, default=str, sort_keys=True) for d in docs)
        return out
    return _run(c, go)


# ================================================================ clean system
def test_clean_system_is_ok_in_every_domain(c):
    rep = _report(c)
    assert set(rep["domains"]) == set(reconciliation.DOMAINS) and rep["read_only"] is True
    bad = {k: (d["status"], {x: d["checks"].get(x) for x in d.get("attention_checks", [])}, d["issues"][:3])
           for k, d in rep["domains"].items() if d["status"] != "ok"}
    assert bad == {} and rep["status"] == "ok"
    assert rep["domains"]["withdrawals"]["checks"]["keyed_checked"] >= 1
    assert rep["domains"]["settlements"]["checks"]["with_snapshot"] >= 1


def test_report_writes_nothing(c):
    before = _fingerprint(c)
    _report(c)
    _run(c, lambda: reconciliation.run())
    assert _fingerprint(c) == before


def test_report_is_finance_only_and_has_no_personal_data(c):
    for who in ("supp", "hg", "vu", "cust"):
        assert c.get("/api/admin/finance/reconciliation", headers=_hdr(who)).status_code == 403
    assert c.get("/api/admin/finance/reconciliation", params={"domain": "nope"}, headers=_hdr("fin")).status_code == 400
    text = json.dumps(_report(c)).lower()
    assert not any(p in text for p in PII)


# ================================================================ one defect per domain is found in that domain
def _only(rep, domain):
    flagged = {k for k, d in rep["domains"].items() if d["status"] != "ok"}
    assert flagged == {domain}, {k: rep["domains"][k]["issues"][:3] for k in flagged}
    return rep["domains"][domain]


def _restore(c, coll, flt, doc):
    _run(c, lambda: db[coll].replace_one(flt, doc))


def test_payment_status_mismatch_is_found(c):
    o = _paid_order(c)
    tx = _run(c, lambda: db.payment_transactions.find_one({"session_id": o["session_id"]}))
    _run(c, lambda: db.payment_transactions.update_one({"session_id": o["session_id"]}, {"$set": {"payment_status": "pending"}}))
    try:
        d = _only(_report(c), "payments")
        assert d["checks"]["status_mismatch"] == 1 and d["issues"][0]["issue"] == "order_paid_attempt_not_paid"
    finally:
        _restore(c, "payment_transactions", {"_id": tx["_id"]}, tx)


def test_gateway_amount_mismatch_is_found(c):
    o = _paid_order(c)
    _run(c, lambda: db.payment_transactions.update_one({"session_id": o["session_id"]}, {"$set": {"gateway_amount_paise": 1}}))
    try:
        d = _only(_report(c, "payments"), "payments")
        assert any(i["issue"] == "gateway_amount_differs_from_order_total" for i in d["issues"])
    finally:
        _run(c, lambda: db.payment_transactions.update_one({"session_id": o["session_id"]}, {"$unset": {"gateway_amount_paise": ""}}))


def test_captured_but_unapplied_payment_is_found(c):
    r = c.post("/api/orders", json={"items": [{"product_id": "rcP", "quantity": 1}], "address": ADDR, "payment_method": "online"},
               headers=_hdr("cust")).json()
    sid = "cs_rc_orphan_" + r["id"][:6]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": r["id"], "user_id": r["user_id"],
                                                        "amount": r["total"], "status": "completed", "payment_status": "paid",
                                                        "created_at": now_iso()}))
    try:
        d = _report(c, "payments")["domains"]["payments"]
        assert d["status"] == "attention" and d["checks"]["captured_unapplied"] == 1
    finally:
        _run(c, lambda: db.payment_transactions.delete_one({"session_id": sid}))
        _run(c, lambda: db.orders.update_one({"id": r["id"]}, {"$set": {"status": "cancelled", "payment_status": "expired"}}))


def test_wallet_drift_is_found(c):
    _run(c, lambda: wallet_apply(S["hg"]["id"], {"available_balance": 1}))
    try:
        d = _only(_report(c), "wallets")
        assert d["checks"]["aggregate_issues"] == 1 and "1_paise" in d["issues"][0]["issue"]
    finally:
        _run(c, lambda: wallet_apply(S["hg"]["id"], {"available_balance": -1}))


def test_withdrawal_without_its_ledger_row_is_found(c):
    wr = _run(c, lambda: db.withdrawal_requests.find_one({"user_id": S["hg"]["id"], "status": "pending"}))
    row = _run(c, lambda: db.wallet_transactions.find_one({"op_key": wi.hold_op(wr["id"])}))
    _run(c, lambda: db.wallet_transactions.delete_one({"_id": row["_id"]}))
    try:
        rep = _report(c)
        flagged = {k for k, d in rep["domains"].items() if d["status"] != "ok"}
        assert flagged == {"withdrawals", "wallets"}              # the missing row also breaks the wallet-vs-ledger identity
        assert rep["domains"]["withdrawals"]["issues"][0]["issue"] == "hold_ledger_missing"
    finally:
        _run(c, lambda: db.wallet_transactions.insert_one(row))


def test_stuck_withdrawal_request_is_found(c):
    wid = new_id()
    _run(c, lambda: db.withdrawal_requests.insert_one({"id": wid, "user_id": S["hg"]["id"], "amount_paise": 100, "amount": 1.0,
                                                        "status": "reserving", "hold_op": wi.hold_op(wid),
                                                        "created_at": "2000-01-01T00:00:00+00:00", "updated_at": now_iso()}))
    try:
        d = _only(_report(c), "withdrawals")
        assert d["checks"]["reserving_stuck"] == 1
    finally:
        _run(c, lambda: db.withdrawal_requests.delete_one({"id": wid}))


def test_tampered_settlement_snapshot_and_missing_ledger_entry_are_found(c):
    s = _run(c, lambda: db.settlements.find_one({"id": S["settlement"]}))
    _run(c, lambda: db.settlements.update_one({"id": S["settlement"]}, {"$set": {"snapshot.bank.account_masked": "XXXX0000"}}))
    entry = _run(c, lambda: db.vendor_ledger.find_one({"source_key": f"settle:{S['settlement']}"}))
    _run(c, lambda: db.vendor_ledger.delete_one({"_id": entry["_id"]}))
    try:
        rep = _report(c)
        d = rep["domains"]["settlements"]
        assert d["checks"]["snapshot_issues"] == 1 and d["checks"]["ledger_entry_missing"] == 1
        assert {i["issue"] for i in d["issues"]} == {"snapshot_digest_mismatch", "paid_without_ledger_entry"}
    finally:
        _restore(c, "settlements", {"_id": s["_id"]}, s)
        _run(c, lambda: db.vendor_ledger.insert_one(entry))


def test_overpaid_vendor_is_found(c):
    key = f"rc-overpay-{new_id()}"
    _run(c, lambda: L.post_entry(S["v"]["id"], L.SETTLEMENT_PAID, -10**9, key, actor="test", reason="injected"))
    try:
        d = _only(_report(c), "vendor_ledger")
        assert d["checks"]["vendors_overpaid"] == 1
    finally:
        _run(c, lambda: db.vendor_ledger.delete_one({"source_key": key}))


def test_refund_obligation_without_case_is_found(c):
    o = _paid_order(c)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"needs_refund": True}}))
    try:
        d = _report(c, "refunds")["domains"]["refunds"]
        assert d["status"] == "attention" and d["checks"]["obligations_without_case"] == 1
    finally:
        _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$unset": {"needs_refund": ""}}))


def test_incomplete_completion_is_found(c):
    o = _paid_order(c)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"completion_due": True}}))
    try:
        d = _only(_report(c), "commissions")
        assert d["checks"]["completion_due"] == 1
    finally:
        _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$unset": {"completion_due": ""}}))


def test_negative_stock_is_found(c):
    _run(c, lambda: db.products.update_one({"id": "rcP"}, {"$inc": {"stock": -1000}}))
    try:
        d = _only(_report(c), "stock")
        assert d["checks"]["stock_negative"] == 1 and d["issues"] == [{"product_id": "rcP", "issue": "negative_stock"}]
    finally:
        _run(c, lambda: db.products.update_one({"id": "rcP"}, {"$inc": {"stock": 1000}}))


def test_one_failing_domain_never_hides_the_others(c, monkeypatch):
    async def boom():
        raise RuntimeError("broken check")
    monkeypatch.setitem(reconciliation.DOMAINS, "stock", boom)
    rep = _run(c, lambda: reconciliation.run())
    assert rep["domains"]["stock"]["status"] == "error" and rep["status"] == "error"
    assert all(d["status"] == "ok" for k, d in rep["domains"].items() if k != "stock")


def test_cancelled_order_with_money_in_and_no_refund_record_is_found(c):
    """Audit P03-A01/A02/A03: a paid order cancelled without an obligation marker or case is invisible to the marker sweep."""
    o = _paid_order(c)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled", "cancel_reason": "customer_cancelled"}}))
    try:
        d = _report(c, "refunds")["domains"]["refunds"]
        assert d["status"] == "attention" and d["checks"]["unrecorded_cancelled_money"] == 1
        assert d["issues"][0]["issue"] == "cancelled_with_money_in_and_no_refund_record"
    finally:
        _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "processing"}, "$unset": {"cancel_reason": ""}}))


def test_system_is_clean_again_after_every_injection(c):
    assert _report(c)["status"] == "ok"
