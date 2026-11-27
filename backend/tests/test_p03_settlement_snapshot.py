"""Programme 03 (B-023): immutable settlement order and bank snapshots.

Every settlement records, at creation, the order basis it was checked against (eligible orders with their net ledger amounts,
held orders with reasons, non-order entries, the balance figures) and the payee bank details in minimal masked form, plus a
digest over the whole snapshot. Nothing changes it afterwards; it verifies at every step; a later bank-detail change blocks
payment of a settlement requested against the old details. Maker-checker, eligibility and amounts are unchanged.
In-process, THROWAWAY database. Run in its own process: `pytest tests/test_p03_settlement_snapshot.py -n 0`.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": os.environ.get("DB_NAME", "homegenies_p03_snapshot_test"), "JWT_SECRET": "p03snap-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from delivery_helper import deliver  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import ledger as L  # noqa: E402
import settlement_snapshot as SS  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
LONG_AGO = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
ACCT = "998877665544"


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()

            async def user(mobile, role, did, status="green"):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status, "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u
            S["cust"] = await user("9100003601", "distributor", "P3C", "red")
            S["fin"], S["fin2"] = await user("9100003602", "accounts_admin", "P3FIN"), await user("9100003603", "super_admin", "P3SUP")
            S["fin3"] = await user("9100003608", "accounts_admin", "P3FIN3")
            S["supp"] = await user("9100003604", "support_admin", "P3SUPP")
            await db.business_settings.update_one({"id": "business_settings"}, {"$set": {"gst_percent": 5.0, "cod_fee": 0.0}}, upsert=True)
        client.portal.call(seed)
        r = client.put("/api/admin/finance/policy", headers=_hdr("fin"), json={"active": True, "require_dual_approval": True, "min_settlement": 1})
        assert r.status_code == 200, r.text
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _vendor(c, key):
    async def go():
        u = {"id": new_id(), "distributor_id": "V" + new_id()[:6].upper(), "full_name": key, "mobile": "93" + f"{abs(hash(key)) % 10**8:08d}",
             "email": None, "password_hash": hash_password("Pass-1234x"), "role": "vendor", "status": "green", "account_status": "active",
             "created_at": now_iso(), "updated_at": now_iso()}
        await db.users.insert_one(dict(u))
        v = {"id": new_id(), "user_id": u["id"], "vendor_code": u["distributor_id"], "business_name": f"Vendor {key}", "status": "approved",
             "categories": ["Sarees"], "bank_account_name": f"Holder {key}", "bank_account": ACCT, "ifsc": "SBIN0001234",
             "created_at": now_iso(), "updated_at": now_iso()}
        await db.vendors.insert_one(dict(v))
        S["u" + key], S["v" + key] = u, v
    _run(c, go)


def _money(c, key, price, delivered=True):
    async def mk():
        v = S["v" + key]
        p = {"id": new_id(), "sku": f"S-{new_id()[:8]}", "name": "x", "images": [], "mrp": price + 100, "selling_price": price, "gst_percent": 5,
             "stock": 1000, "category": "Sarees", "options": [], "vendor_id": v["id"], "vendor_name": v["business_name"], "is_active": True,
             "approval_status": "approved", "created_at": now_iso()}
        await db.products.insert_one(dict(p))
        return p
    p = _run(c, mk)
    r = c.post("/api/orders", json={"items": [{"product_id": p["id"], "quantity": 1}], "address": ADDR, "payment_method": "online"},
               headers=_hdr("cust"))
    assert r.status_code == 200, r.text
    o = r.json()
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending",
                                                        "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    if delivered:
        _run(c, lambda: deliver(db, o["id"], LONG_AGO))
    return o


def _create(c, key, who="fin", amount=None):
    body = {"vendor_id": S["v" + key]["id"]}
    if amount is not None:
        body["amount"] = amount
    return c.post("/api/admin/finance/settlements", headers=_hdr(who), json=body)


def _act(c, sid, who, action, **kw):
    return c.post(f"/api/admin/finance/settlements/{sid}/action", headers=_hdr(who), json={"action": action, **kw})


def _doc(c, sid):
    return _run(c, lambda: db.settlements.find_one({"id": sid}, {"_id": 0}))


def _bank_change(c, key, acct, ifsc="HDFC0004321", holder=None):
    r = c.post("/api/vendor/me/bank-change", headers=_hdr("u" + key),
               json={"bank_account_name": holder or f"Holder {key}", "bank_account": acct, "ifsc": ifsc, "reason": "Moved to a new bank"})
    assert r.status_code == 200, r.text
    d = c.post(f"/api/admin/vendor-change-requests/{r.json()['id']}/decision", headers=_hdr("fin"), json={"decision": "approve"})
    assert d.status_code == 200, d.text


# ================================================================ what is recorded
def test_snapshot_records_the_exact_order_basis(c):
    _vendor(c, "A")
    a1, a2 = _money(c, "A", 400.0), _money(c, "A", 250.0)
    held = _money(c, "A", 100.0, delivered=False)                    # paid, not delivered: held
    _run(c, lambda: L.post_entry(S["vA"]["id"], L.ADJUSTMENT, -1234, f"adj:{new_id()}", actor=S["fin"]["id"], reason="test adjustment"))
    bal = _run(c, lambda: L.balances(S["vA"]["id"]))
    r = _create(c, "A")
    assert r.status_code == 200, r.text
    body = r.json()
    snap = body["snapshot"]
    assert body["amount_paise"] == bal["available_for_settlement_paise"]                # the amount rule is unchanged
    b = snap["basis"]
    assert b["requested_paise"] == body["amount_paise"] and b["available_for_settlement_paise"] == bal["available_for_settlement_paise"]
    assert b["orders_total_paise"] + b["non_order_paise"] == b["eligible_paise"] and b["non_order_paise"] == -1234
    by = {x["order_id"]: x["amount_paise"] for x in snap["orders"]}
    assert set(by) == {a1["id"], a2["id"]} and snap["orders_count"] == 2 and snap["orders_truncated"] is False
    entries = _run(c, lambda: db.vendor_ledger.find({"vendor_id": S["vA"]["id"]}, {"_id": 0}).to_list(None))
    for oid in (a1["id"], a2["id"]):
        assert by[oid] == sum(e["amount_paise"] for e in entries if e.get("order_id") == oid)      # net of commission, exact paise
    assert [h["order_id"] for h in snap["held"]] == [held["id"]] and snap["held"][0]["reason"] == "not_delivered"
    assert snap["orders_digest"] == SS._orders_digest(sorted(snap["orders"], key=lambda x: x["order_id"]))
    assert body["snapshot_digest"] == SS.digest(snap) and body["snapshot_summary"]["verified"] is True


def test_bank_snapshot_is_minimal_and_never_holds_the_full_account(c):
    _vendor(c, "B")
    _money(c, "B", 300.0)
    sid = _create(c, "B").json()["id"]
    d = _doc(c, sid)
    assert d["snapshot"]["bank"] == {"present": True, "account_holder": "Holder B", "ifsc": "SBIN0001234", "account_masked": "XXXX5544",
                                     "account_last4": "5544", "bank_change_id": None}
    assert ACCT not in json.dumps(d)
    audit = _run(c, lambda: db.audit_logs.find({"entity_id": sid}, {"_id": 0}).to_list(10))
    assert audit and ACCT not in json.dumps(audit)
    for who in ("fin", "supp"):
        listing = c.get("/api/admin/finance/settlements", headers=_hdr(who)).json()
        assert ACCT not in json.dumps(listing)
    row = [x for x in c.get("/api/admin/finance/settlements", headers=_hdr("supp")).json()["items"] if x["id"] == sid][0]
    assert "bank" not in row["snapshot_summary"] and "snapshot" not in row            # support sees no payee bank details
    row = [x for x in c.get("/api/admin/finance/settlements", headers=_hdr("fin")).json()["items"] if x["id"] == sid][0]
    assert row["snapshot_summary"]["bank"]["account_masked"] == "XXXX5544" and "snapshot" not in row
    assert c.get(f"/api/admin/finance/settlements/{sid}", headers=_hdr("supp")).status_code == 403
    detail = c.get(f"/api/admin/finance/settlements/{sid}", headers=_hdr("fin")).json()
    assert detail["snapshot"]["bank"]["account_masked"] == "XXXX5544" and ACCT not in json.dumps(detail)
    mine = c.get("/api/vendor/finance/settlements", headers=_hdr("uB")).json()["items"]
    assert mine and "snapshot" not in mine[0] and "snapshot_digest" not in mine[0]


# ================================================================ immutability
def test_snapshot_never_changes_through_the_lifecycle(c):
    _vendor(c, "C")
    _money(c, "C", 500.0)
    sid = _create(c, "C").json()["id"]
    first = _doc(c, sid)
    assert _act(c, sid, "fin2", "approve").status_code == 200
    _money(c, "C", 700.0)                                            # the ledger moves on after the request
    assert _act(c, sid, "fin3", "mark_paid", reference="UTR-P3-0001").status_code == 200
    last = _doc(c, sid)
    assert last["status"] == "paid" and last["snapshot"] == first["snapshot"] and last["snapshot_digest"] == first["snapshot_digest"]
    assert SS.verify(last) is True
    assert _run(c, lambda: db.vendor_ledger.count_documents({"source_key": f"settle:{sid}"})) == 1


def test_bank_change_after_request_blocks_payment_and_snapshot_keeps_the_old_details(c):
    _vendor(c, "D")
    _money(c, "D", 500.0)
    sid = _create(c, "D").json()["id"]
    before = _doc(c, sid)["snapshot"]
    assert _act(c, sid, "fin2", "approve").status_code == 200
    _bank_change(c, "D", "111122223333")
    r = _act(c, sid, "fin3", "mark_paid", reference="UTR-P3-0002")
    assert r.status_code == 409 and "bank details changed" in r.json()["detail"]
    d = _doc(c, sid)
    assert d["status"] == "approved" and d["snapshot"] == before and d["snapshot"]["bank"]["account_masked"] == "XXXX5544"
    assert _run(c, lambda: db.vendor_ledger.count_documents({"source_key": f"settle:{sid}"})) == 0      # nothing paid
    assert _act(c, sid, "fin", "reject", note="Bank details changed; re-request").status_code == 200
    new = _create(c, "D")
    assert new.status_code == 200
    nb = new.json()["snapshot"]["bank"]
    assert nb["account_masked"] == "XXXX3333" and nb["ifsc"] == "HDFC0004321" and nb["bank_change_id"]
    nsid = new.json()["id"]
    assert _act(c, nsid, "fin2", "approve").status_code == 200
    assert _act(c, nsid, "fin3", "mark_paid", reference="UTR-P3-0003").status_code == 200


def test_bank_change_to_same_last4_is_still_detected(c):
    """A new account ending in the same four digits at the same IFSC is caught by the approved-change id."""
    _vendor(c, "E")
    _money(c, "E", 500.0)
    sid = _create(c, "E").json()["id"]
    assert _act(c, sid, "fin2", "approve").status_code == 200
    _bank_change(c, "E", "000000005544", ifsc="SBIN0001234", holder="Holder E")
    assert _act(c, sid, "fin3", "mark_paid", reference="UTR-P3-0004").status_code == 409


def test_tampered_snapshot_is_detected_and_blocks_payment(c):
    _vendor(c, "F")
    _money(c, "F", 500.0)
    sid = _create(c, "F").json()["id"]
    assert _act(c, sid, "fin2", "approve").status_code == 200
    _run(c, lambda: db.settlements.update_one({"id": sid}, {"$set": {"snapshot.basis.available_for_settlement_paise": 99999999}}))
    assert SS.verify(_doc(c, sid)) is False
    r = _act(c, sid, "fin3", "mark_paid", reference="UTR-P3-0005")
    assert r.status_code == 409 and "does not verify" in r.json()["detail"]
    issues = {i["settlement_id"]: i["issue"] for i in _run(c, lambda: SS.audit())["issues"]}
    assert issues.get(sid) == "snapshot_digest_mismatch"
    row = [x for x in c.get("/api/admin/finance/settlements", headers=_hdr("fin")).json()["items"] if x["id"] == sid][0]
    assert row["snapshot_summary"]["verified"] is False


def test_legacy_settlement_without_snapshot_behaves_as_before(c):
    _vendor(c, "G")
    _money(c, "G", 500.0)
    bal = _run(c, lambda: L.balances(S["vG"]["id"]))
    sid = new_id()
    _run(c, lambda: db.settlements.insert_one({"id": sid, "number": "STLLEGACY", "vendor_id": S["vG"]["id"], "vendor_name": "Vendor G",
                                               "amount_paise": bal["available_for_settlement_paise"], "currency": "INR", "status": "requested",
                                               "policy_version": 1, "note": "", "created_by": S["fin"]["id"], "approved_by": None,
                                               "paid_by": None, "reference": "", "events": [], "created_at": now_iso(), "updated_at": now_iso()}))
    assert _act(c, sid, "fin2", "approve").status_code == 200
    _bank_change(c, "G", "444455556666")                              # no snapshot: no bank comparison (unchanged behaviour)
    assert _act(c, sid, "fin3", "mark_paid", reference="UTR-P3-0006").status_code == 200
    row = [x for x in c.get("/api/admin/finance/settlements", headers=_hdr("fin")).json()["items"] if x["id"] == sid][0]
    assert row["snapshot_summary"] == {"present": False}
    assert _run(c, lambda: SS.audit())["legacy_without_snapshot"] >= 1


# ================================================================ concurrency
def test_concurrent_creation_makes_one_settlement_with_one_snapshot(c):
    _vendor(c, "H")
    _money(c, "H", 500.0)
    codes = list(ThreadPoolExecutor(max_workers=4).map(lambda _: _create(c, "H", amount=100).status_code, range(4)))
    assert codes.count(200) == 1 and all(x == 409 for x in codes if x != 200)
    rows = _run(c, lambda: db.settlements.find({"vendor_id": S["vH"]["id"]}, {"_id": 0}).to_list(10))
    assert len(rows) == 1 and SS.verify(rows[0]) is True and rows[0]["snapshot"]["basis"]["requested_paise"] == 10000


def test_concurrent_payment_pays_once_and_keeps_the_snapshot(c):
    _vendor(c, "I")
    _money(c, "I", 500.0)
    sid = _create(c, "I").json()["id"]
    snap = _doc(c, sid)["snapshot"]
    assert _act(c, sid, "fin2", "approve").status_code == 200
    codes = list(ThreadPoolExecutor(max_workers=4).map(
        lambda i: _act(c, sid, ("fin", "fin3")[i % 2], "mark_paid", reference=f"UTR-P3-RACE-{i}").status_code, range(4)))
    assert codes.count(200) == 1
    assert _run(c, lambda: db.vendor_ledger.count_documents({"source_key": f"settle:{sid}"})) == 1
    assert _doc(c, sid)["snapshot"] == snap


def test_large_basis_keeps_totals_and_digest_when_the_list_is_capped(c, monkeypatch):
    _vendor(c, "J")
    for price in (100.0, 200.0, 300.0):
        _money(c, "J", price)
    monkeypatch.setattr(SS, "MAX_ORDERS_STORED", 2)
    snap = _create(c, "J").json()["snapshot"]
    assert snap["orders_count"] == 3 and len(snap["orders"]) == 2 and snap["orders_truncated"] is True
    detail = _run(c, lambda: L.eligible_detail(S["vJ"]["id"]))
    assert snap["orders_digest"] == SS._orders_digest(detail["eligible"])
    assert snap["basis"]["orders_total_paise"] == sum(x["amount_paise"] for x in detail["eligible"])


def test_eligible_detail_matches_the_existing_eligibility_numbers(c):
    """The refactor keeps `_eligible_paise` (used by balances) exactly as before."""
    for key in ("A", "C", "J"):
        vid = S["v" + key]["id"]
        d = _run(c, lambda: L.eligible_detail(vid))
        e, held = _run(c, lambda: L._eligible_paise(vid))
        assert (e, held) == (d["eligible_paise"], d["held_orders"])
        assert d["eligible_paise"] == d["non_order_paise"] + sum(x["amount_paise"] for x in d["eligible"])
