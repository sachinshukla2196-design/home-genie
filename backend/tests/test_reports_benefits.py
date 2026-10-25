"""Current reports, advancement and benefit approval (Phase 7): date boundaries, totals, exports, isolation and approvals.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_reports_benefits.py -n 0`.
"""
import csv
import io
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_reports_benefits_test", "JWT_SECRET": "reports-benefits-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger as L  # noqa: E402
import vendor_benefits as VB  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Vendor-Pass-123"
ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _noon(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(hour=12, minute=0, second=0, microsecond=0)


def _order(vid, pid, days_ago, total=100000, status="delivered", dispatch_after_hours=None, payment="online"):
    placed = _noon(days_ago)
    events = []
    if dispatch_after_hours is not None:
        events = [{"status": "dispatched", "at": (placed + timedelta(hours=dispatch_after_hours)).isoformat(), "by": "x", "note": ""}]
    line = {"product_id": pid, "name": "Report item", "sku": "RPT-1", "vendor_id": vid, "quantity": 1, "total_paise": total, "total": total / 100}
    return {"id": new_id(), "order_number": "RPT" + new_id()[:8].upper(), "user_id": new_id(), "payment_method": payment, "payment_status": "paid",
            "status": status, "created_at": placed.isoformat(), "paid_at": placed.isoformat(), "total_paise": total, "total": total / 100,
            "items": [line], "fulfilments": [{"vendor_id": vid, "status": status, "events": events}], "address": ADDR, "needs_refund": False}


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

            S["fin1"] = await user("9100004001", "accounts_admin", "RFA1")
            S["fin2"] = await user("9100004002", "super_admin", "RFA2")
            S["cust"] = await user("9100004003", "distributor", "RCUS")
            S["ua"] = await user("9100004004", "vendor", "RVA")
            S["va"] = await vendor(S["ua"], "Report Store A", "VR000001")
            S["ub"] = await user("9100004005", "vendor", "RVB")
            S["vb"] = await vendor(S["ub"], "Report Store B", "VR000002")
            S["pa"], S["pb"] = new_id(), new_id()
            base = {"stock": 5, "low_stock_threshold": 5, "is_active": True, "approval_status": "approved", "archived": False, "category": "Sarees",
                    "created_at": now_iso(), "updated_at": now_iso()}
            await db.products.insert_many([{**base, "id": S["pa"], "vendor_id": S["va"]["id"], "name": "Alpha Saree", "sku": "AL-1"},
                                           {**base, "id": S["pb"], "vendor_id": S["vb"]["id"], "name": "Beta Saree", "sku": "BE-1"}])
            orders = [
                _order(S["va"]["id"], S["pa"], 0, 100000),                                    # today
                _order(S["va"]["id"], S["pa"], 6, 200000, dispatch_after_hours=10),            # first day of the 7-day window
                _order(S["va"]["id"], S["pa"], 7, 300000),                                    # just outside 7 days
                _order(S["va"]["id"], S["pa"], 29, 400000),                                   # first day of the 30-day window
                _order(S["va"]["id"], S["pa"], 30, 500000),                                   # just outside 30 days
                _order(S["vb"]["id"], S["pb"], 1, 70000),                                     # vendor B, must never appear for A
            ]
            await db.orders.insert_many(orders)
            await db.stock_movements.insert_many([
                {"id": new_id(), "product_id": S["pa"], "variant_sku": None, "delta": 4, "before": 1, "after": 5, "reason": "Supplier delivery",
                 "actor_id": S["ua"]["id"], "created_at": _noon(0).isoformat()},
                {"id": new_id(), "product_id": S["pa"], "variant_sku": None, "delta": -2, "before": 5, "after": 3, "reason": "Damaged",
                 "actor_id": S["ua"]["id"], "created_at": _noon(0).isoformat()},
                {"id": new_id(), "product_id": S["pb"], "variant_sku": None, "delta": 9, "before": 0, "after": 9, "reason": "Vendor B only",
                 "actor_id": S["ub"]["id"], "created_at": _noon(0).isoformat()}])
            await db.settlements.insert_many([
                {"id": new_id(), "number": "STL-R1", "vendor_id": S["va"]["id"], "amount_paise": 150000, "status": "paid", "reference": "UTRREP1",
                 "created_at": _noon(0).isoformat(), "paid_at": _noon(0).isoformat(), "created_by": S["fin1"]["id"], "approved_by": S["fin2"]["id"],
                 "paid_by": S["fin2"]["id"], "events": []},
                {"id": new_id(), "number": "STL-R2", "vendor_id": S["vb"]["id"], "amount_paise": 99900, "status": "requested", "reference": "",
                 "created_at": _noon(0).isoformat(), "paid_at": None, "created_by": S["fin1"]["id"], "events": []}])
        client.portal.call(seed)
        for o in client.portal.call(lambda: db.orders.find({"fulfilments.vendor_id": S["va"]["id"]}, {"_id": 0}).to_list(50)):
            client.portal.call(lambda o=o: L.post_order_collected(o))
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _report(c, who="ua", **params):
    return c.get("/api/vendor/reports/current", headers=_hdr(S[who]["id"]), params=params or {"range": "30d"})


# ====================================================================== date boundaries and totals
def test_review_window_is_inclusive_and_ends_today():
    f, t = VB.review_window(7)
    today = datetime.now(timezone.utc).date()
    assert t == today.isoformat() and f == (today - timedelta(days=6)).isoformat()


def test_seven_day_and_thirty_day_ranges_include_their_first_day_and_exclude_the_day_before(c):
    seven = _report(c, range="7d").json()
    assert seven["sales"]["orders"] == 2                                           # today and 6 days ago; 7 days ago is outside
    assert seven["sales"]["order_value_paise"] == 100000 + 200000
    thirty = _report(c, range="30d").json()
    assert thirty["sales"]["orders"] == 4                                          # 29 days ago included, 30 days ago excluded
    assert thirty["sales"]["order_value_paise"] == 100000 + 200000 + 300000 + 400000


def test_custom_range_is_inclusive_of_both_ends(c):
    d6 = (datetime.now(timezone.utc).date() - timedelta(days=6)).isoformat()
    d7 = (datetime.now(timezone.utc).date() - timedelta(days=7)).isoformat()
    r = _report(c, range="custom", date_from=d7, date_to=d6).json()
    assert r["sales"]["orders"] == 2                                               # the 7-day-old and 6-day-old orders, both ends included
    assert r["sales"]["order_value_paise"] == 300000 + 200000


def test_report_totals_match_the_dashboard_for_the_same_range(c):
    dash = c.get("/api/vendor/dashboard", headers=_hdr(S["ua"]["id"]), params={"range": "30d"}).json()
    rep = _report(c).json()
    assert rep["sales"]["order_value_paise"] == dash["sales"]["order_value_paise"]
    assert rep["orders_by_status"] == dash["orders_by_status"]


# ====================================================================== dispatch, stock, settlements, commissions
def test_dispatch_time_is_measured_from_payment_only_where_the_event_exists(c):
    d = _report(c, range="7d").json()["dispatch"]
    assert d["dispatched_orders"] == 1 and d["measured_orders"] == 1
    assert d["average_hours_to_dispatch"] == 10.0


def test_stock_movements_are_totalled_and_belong_to_this_vendor_only(c):
    m = _report(c, range="7d").json()["stock_movements"]
    assert m["movements"] == 2 and m["added"] == 4 and m["removed"] == 2     # removals reported as a positive quantity
    assert {r["product_id"] for r in m["rows"]} == {S["pa"]} and "Vendor B only" not in str(m)


def test_settlement_history_shows_references_and_never_admin_identities(c):
    rows = _report(c).json()["settlement_rows"]
    assert [r["number"] for r in rows] == ["STL-R1"]
    text = str(rows)
    assert S["fin1"]["id"] not in text and S["fin2"]["id"] not in text and "STL-R2" not in text and rows[0]["reference"] == "UTRREP1"


def test_commission_is_reported_as_not_applicable_until_an_agreement_is_approved(c):
    r = _report(c).json()
    assert r["commission"]["available"] is False


def test_csv_export_is_the_vendors_own_data_with_formula_safe_cells(c):
    r = c.get("/api/vendor/reports/current.csv", headers=_hdr(S["ua"]["id"]), params={"range": "30d"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    flat = [cell for row in rows for cell in row]
    assert "UTRREP1" in flat and "Alpha Saree" in flat and "Beta Saree" not in r.text and "STL-R2" not in r.text
    assert "order_value_inr,10000.00" in r.text                                      # 1,000 + 2,000 + 3,000 + 4,000 rupees (the 30-day-old order is outside)
    other = c.get("/api/vendor/reports/current.csv", headers=_hdr(S["ub"]["id"]), params={"range": "30d"}).text
    assert "Alpha Saree" not in other and "Beta Saree" in other and "UTRREP1" not in other


def test_no_orders_gives_empty_values_not_invented_metrics(c):
    adv = c.get("/api/vendor/reports/advancement", headers=_hdr(S["ub"]["id"]), params={"range": "today"}).json()
    assert adv["kpis"]["orders"] == 0 and adv["kpis"]["cancellation_rate"] is None and adv["kpis"]["average_order_value_paise"] is None
    assert adv["ratings"]["available"] is False and adv["milestones"]["available"] is False


# ====================================================================== benefits: eligibility and approval
def _programme(c, key="fast_growth", orders=1):
    body = {"key": key, "title": "Consistent orders", "review_days": 7, "benefit_text": "Priority listing review (no money changes).",
            "criteria": [{"metric": "orders", "value": orders}, {"metric": "cancellation_rate", "value": 20}]}
    r = c.post("/api/admin/benefits/programmes", headers=_hdr(S["fin1"]["id"]), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_eligibility_is_calculated_from_the_review_window_and_unmet_criteria_are_listed(c):
    _programme(c)
    a = c.get("/api/vendor/advancement/eligibility", headers=_hdr(S["ua"]["id"])).json()["programmes"][0]
    assert a["eligible"] is True and a["criteria"][0]["measured"] == 2 and a["criteria"][0]["met"] is True
    b = c.get("/api/vendor/advancement/eligibility", headers=_hdr(S["ub"]["id"])).json()["programmes"][0]
    assert b["eligible"] is True                                                 # B has one order in the window
    _programme(c, key="many_orders", orders=50)
    s_ = c.get("/api/vendor/advancement/eligibility", headers=_hdr(S["ua"]["id"])).json()["programmes"][1]
    assert s_["eligible"] is False and s_["criteria"][0]["met"] is False and s_["criteria"][0]["measured"] == 2


def test_benefit_needs_a_proposal_and_a_different_approver_and_changes_no_money(c):
    prog = c.get("/api/admin/benefits/programmes", headers=_hdr(S["fin1"]["id"])).json()["programmes"][0]
    before = c.portal.call(lambda: db.vendor_ledger.count_documents({"vendor_id": S["va"]["id"]}))
    g = c.post("/api/admin/benefits/proposals", headers=_hdr(S["fin1"]["id"]), json={"vendor_id": S["va"]["id"], "programme_id": prog["id"], "note": "Solid record"})
    assert g.status_code == 200 and g.json()["status"] == "proposed" and g.json()["evaluation"]["eligible"] is True
    assert c.post("/api/admin/benefits/proposals", headers=_hdr(S["fin1"]["id"]), json={"vendor_id": S["va"]["id"], "programme_id": prog["id"]}).status_code == 409
    gid = g.json()["id"]
    assert c.post(f"/api/admin/benefits/proposals/{gid}/decide", headers=_hdr(S["fin1"]["id"]), json={"action": "approve"}).status_code == 403
    assert c.post(f"/api/admin/benefits/proposals/{gid}/decide", headers=_hdr(S["fin2"]["id"]), json={"action": "reject", "note": "x"}).status_code == 400
    assert c.post(f"/api/admin/benefits/proposals/{gid}/decide", headers=_hdr(S["fin2"]["id"]), json={"action": "request_review", "note": "Check the cancellations"}).status_code == 200
    assert c.post(f"/api/admin/benefits/proposals/{gid}/decide", headers=_hdr(S["fin2"]["id"]), json={"action": "approve"}).status_code == 200
    approved = c.get("/api/vendor/advancement/eligibility", headers=_hdr(S["ua"]["id"])).json()["benefits"]
    row = next(x for x in approved if x["id"] == gid)
    assert row["status"] == "approved" and row["applied"] is False
    assert c.portal.call(lambda: db.vendor_ledger.count_documents({"vendor_id": S["va"]["id"]})) == before   # recording a benefit moves no money
    assert c.post(f"/api/admin/benefits/proposals/{gid}/decide", headers=_hdr(S["fin2"]["id"]), json={"action": "approve"}).status_code == 400


def test_an_ineligible_vendor_cannot_be_approved_and_a_vendor_cannot_propose_or_decide(c):
    prog = c.get("/api/admin/benefits/programmes", headers=_hdr(S["fin1"]["id"])).json()["programmes"][1]   # the strict one (50 orders)
    g = c.post("/api/admin/benefits/proposals", headers=_hdr(S["fin1"]["id"]), json={"vendor_id": S["va"]["id"], "programme_id": prog["id"]}).json()
    assert g["evaluation"]["eligible"] is False
    assert c.post(f"/api/admin/benefits/proposals/{g['id']}/decide", headers=_hdr(S["fin2"]["id"]), json={"action": "approve"}).status_code == 400
    assert c.post("/api/admin/benefits/proposals", headers=_hdr(S["ua"]["id"]), json={"vendor_id": S["va"]["id"], "programme_id": prog["id"]}).status_code == 403
    assert c.post(f"/api/admin/benefits/proposals/{g['id']}/decide", headers=_hdr(S["ua"]["id"]), json={"action": "approve"}).status_code == 403
    assert c.post("/api/admin/benefits/programmes", headers=_hdr(S["ua"]["id"]), json={"key": "mine", "title": "Mine", "review_days": 7,
                                                                                    "benefit_text": "Free money", "criteria": [{"metric": "orders", "value": 0}]}).status_code == 403
    assert c.get("/api/admin/benefits/programmes", headers=_hdr(S["cust"]["id"])).status_code == 403
    mine = c.get("/api/vendor/advancement/eligibility", headers=_hdr(S["ub"]["id"])).json()["benefits"]
    assert all(b["status"] != "approved" or b["programme_key"] != "fast_growth" for b in mine) and all(b["id"] != g["id"] for b in mine)
