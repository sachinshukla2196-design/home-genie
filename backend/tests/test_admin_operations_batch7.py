"""Batch 7 — Admin Operations screen contract: every list the screen calls answers for an admin with the fields the screen
reads, and the new duplicate-payment endpoints work (finance only; recording the refund lifts the payout hold).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_admin_operations_batch7.py -n 0`).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_admin_ops_batch7_test", "JWT_SECRET": "batch7-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
from eligibility import payout_block  # noqa: E402

S = {}


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
            for key, mob, role in (("super", "9100008001", "super_admin"), ("fin", "9100008002", "accounts_admin"),
                                   ("sup", "9100008003", "support_admin"), ("vu", "9100008004", "vendor")):
                u = {"id": new_id(), "distributor_id": key.upper() + "8", "full_name": key, "mobile": mob, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "VD8", "business_name": "Ops Vendor", "status": "approved",
                      "bank_account": "123456789012", "ifsc": "SBIN0000001", "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
            long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
            S["o"] = {"id": new_id(), "order_number": "ORD-OPS1", "user_id": new_id(), "payment_status": "paid", "payment_method": "online",
                      "status": "delivered", "delivered_at": long_ago, "total": 500.0, "total_paise": 50000, "items": [], "fulfilments": [],
                      "duplicate_payments": [{"session_id": "cs_dup1", "provider": "stripe", "amount": 500.0, "reason": "order_already_paid",
                                              "status": "refund_due", "detected_at": now_iso()}], "has_duplicate_payment": True,
                      "created_at": long_ago, "updated_at": now_iso()}
            await db.orders.insert_one(dict(S["o"]))
            await db.orders.insert_one({"id": new_id(), "order_number": "ORD-COD1", "payment_status": "cod_discrepancy", "payment_method": "cod",
                                        "status": "confirmed", "cod_discrepancy": {"expected_paise": 50000, "collected_paise": 40000, "status": "open"},
                                        "items": [], "fulfilments": [], "created_at": now_iso(), "updated_at": now_iso()})
            await db.refund_cases.insert_one({"id": new_id(), "number": "RFD-OPS1", "order_id": S["o"]["id"], "kind": "cancel",
                                              "status": "awaiting_review", "amount_paise": 1000, "source_key": "ops:1", "created_at": now_iso()})
            await db.return_cases.insert_one({"id": new_id(), "number": "RTN-OPS1", "order_id": S["o"]["id"], "kind": "return",
                                              "status": "contested", "reason": "damaged", "created_at": now_iso()})
            await db.vendor_change_requests.insert_one({"id": new_id(), "vendor_id": S["v"]["id"], "kind": "bank", "status": "pending",
                                                        "payload": {"bank_account": "998877665544", "ifsc": "HDFC0001234",
                                                                    "bank_account_name": "Ops Vendor"}, "created_at": now_iso()})
            await db.support_tickets.insert_one({"id": new_id(), "number": "TCK-OPS1", "vendor_id": S["v"]["id"], "subject": "Payout question",
                                                 "category": "finance", "status": "open", "messages": [], "created_at": now_iso()})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


@pytest.mark.parametrize("url,params,keys", [
    ("/api/admin/refund-cases", {"state": "open"}, {"id", "number", "amount_paise", "status", "kind"}),
    ("/api/admin/returns", {"status": "contested"}, {"id", "number", "status", "kind"}),
    ("/api/admin/finance/vendors", {}, {"id", "business_name", "balances"}),
    ("/api/admin/finance/cod-discrepancies", {}, {"id", "order_number", "cod_discrepancy"}),
    ("/api/admin/vendor-change-requests", {"status": "pending"}, {"id", "vendor", "payload"}),
    ("/api/admin/support/tickets", {"status": "open"}, {"id", "subject", "status", "category"}),
    ("/api/admin/payments/duplicates", {}, {"order_id", "order_number", "session_id", "provider", "amount", "reason"}),
    ("/api/admin/finance/approvals", {"status": "pending"}, set()),
])
def test_every_operations_list_returns_the_fields_the_screen_reads(c, url, params, keys):
    r = c.get(url, params=params, headers=_hdr("super"))
    assert r.status_code == 200, r.text
    data = r.json()
    rows = data if isinstance(data, list) else data["items"]
    if keys:
        assert rows and keys <= set(rows[0]), (url, set(rows[0]) if rows else None)


def test_vendor_balances_carry_the_eligibility_figures(c):
    v = next(x for x in c.get("/api/admin/finance/vendors", headers=_hdr("fin")).json()["items"] if x["id"] == S["v"]["id"])
    assert {"available_for_settlement_paise", "awaiting_eligibility_paise", "settlement_in_progress_paise"} <= set(v["balances"])


def test_change_request_list_masks_the_new_account(c):
    row = c.get("/api/admin/vendor-change-requests", headers=_hdr("super")).json()["items"][0]
    assert "998877665544" not in str(row) and row["payload"]["bank_account"].endswith("5544")


def test_duplicate_payments_are_finance_only_and_recording_the_refund_lifts_the_hold(c):
    assert c.get("/api/admin/payments/duplicates", headers=_hdr("sup")).status_code == 403
    order = lambda: _run(c, lambda: db.orders.find_one({"id": S["o"]["id"]}, {"_id": 0}))   # noqa: E731
    o1 = order()
    assert _run(c, lambda: payout_block(o1)) == "duplicate_payment_refund_due"
    body = {"session_id": "cs_dup1", "reference": "RFND-GW-0001"}
    assert c.post(f"/api/admin/payments/duplicates/{S['o']['id']}/refunded", json=body, headers=_hdr("sup")).status_code == 403
    assert c.post(f"/api/admin/payments/duplicates/{S['o']['id']}/refunded", json={**body, "reference": "x"}, headers=_hdr("fin")).status_code == 422
    assert c.post(f"/api/admin/payments/duplicates/{S['o']['id']}/refunded", json=body, headers=_hdr("fin")).status_code == 200
    assert c.post(f"/api/admin/payments/duplicates/{S['o']['id']}/refunded", json=body, headers=_hdr("fin")).status_code == 409
    d = order()["duplicate_payments"][0]
    assert d["status"] == "refunded" and d["refund_reference"] == "RFND-GW-0001" and d["refunded_by"] == S["fin"]["id"]
    o2 = order()
    # the duplicate-payment hold is lifted (this order is still held for its open refund case and contested return)
    assert _run(c, lambda: payout_block(o2)) == "open_return_or_refund"
    assert c.get("/api/admin/payments/duplicates", headers=_hdr("fin")).json()["items"] == []
