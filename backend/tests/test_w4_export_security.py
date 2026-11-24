"""Programme 02 / W4: reports and exports — access control, masking, formula-injection safety, size / date limits, audit, no stored
files. Numbers in test names follow the W4 brief's test list (1-30).

Integration, THROWAWAY MongoDB (`homegenies_w4_export_test`, dropped at the end). Run alone: `pytest tests/test_w4_export_security.py -n 0`.
"""
import csv
import io
import os
import tempfile

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_w4_export_test", "JWT_SECRET": "w4-export-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import admin_routes  # noqa: E402
import admin_order_ops  # noqa: E402
import db_indexes  # noqa: E402
import exports  # noqa: E402
import finance_routes  # noqa: E402
import vendor_routes  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402
from p01_harness import seed_world, hdr  # noqa: E402

S = {}
PAN, AADHAAR, ACCT, IFSC = "ABCDE1234F", "123412341234", "123456789012", "HDFC0001234"
MOBILE, EMAIL = "9811122233", "priya.w4@example.com"
EVIL = ["=HYPERLINK(\"http://evil.example\",\"x\")", "+cmd|' /C calc'!A0", "-2+3", "@SUM(1+1)", " =1+1", "\t=1", "＝1+1"]


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "W4")
            S["member"] = {"id": new_id(), "distributor_id": "W4MEM", "full_name": EVIL[0], "email": EMAIL, "mobile": MOBILE,
                           "role": "distributor", "status": "green", "state": "MH", "city": "Pune", "created_at": "2026-10-05T10:00:00+00:00"}
            await db.users.insert_one(dict(S["member"]))
            await db.kyc_records.insert_one({"id": new_id(), "user_id": S["member"]["id"], "pan": PAN, "aadhaar": AADHAAR, "bank_account": ACCT,
                                             "ifsc": IFSC, "account_holder_name": "Priya", "status": "pending", "version": 1, "submitted_at": now_iso()})
            await db.payment_transactions.insert_one({"session_id": "cs_test_SECRETSESSION123456", "order_id": "o1", "amount": 100.0,
                                                      "currency": "inr", "payment_status": "paid", "created_at": now_iso()})
            for vk in ("va", "vb"):
                for i in range(3):
                    await db.vendor_ledger.insert_one({"id": new_id(), "vendor_id": S[vk]["id"], "type": "ADJUSTMENT", "amount_paise": -12050 if i == 0 else 5000,
                                                       "reason": EVIL[i] if vk == "va" else f"vb-only-{i}", "source_key": f"w4:{vk}:{i}",
                                                       "posted_at": f"2026-10-0{i + 1}T10:00:00+00:00"})
                await db.products.insert_one({"id": new_id(), "sku": f"W4-{vk}", "name": EVIL[3] if vk == "va" else "VB secret product",
                                              "vendor_id": S[vk]["id"], "category": "Sarees", "mrp": 100, "selling_price": 90, "stock": 5,
                                              "images": [], "is_active": True, "approval_status": "approved", "created_at": now_iso()})
                await db.vendor_documents.insert_one({"id": new_id(), "vendor_id": S[vk]["id"], "type": "pan", "url": f"https://res.cloudinary.example/authenticated/s--sig--/{vk}.pdf",
                                                      "status": "submitted", "created_at": now_iso()})
            await db.orders.insert_one({"id": "w4-order-cust", "order_number": "=W4ORD1", "user_id": S["cust"]["id"], "payment_method": "online",
                                        "payment_status": "paid", "status": "processing", "total": 500, "total_paise": 50000, "items": [],
                                        "fulfilments": [], "address": {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road"},
                                        "created_at": "2026-10-06T10:00:00+00:00"})
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def H(k):
    return hdr(S[k]["id"])


def run(c, fn):
    return c.portal.call(fn)


def rows_of(text):
    return list(csv.reader(io.StringIO(text)))


def audits(c, action, report=None):
    q = {"action": action, **({"entity_id": report} if report else {})}
    return run(c, lambda: db.audit_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(50))


EXPORTS = ["/api/admin/reports/registrations/export", "/api/admin/order-ops/orders.csv", "/api/vendor/finance/statement.csv",
           "/api/vendor/reports/current.csv", "/api/vendor/products/export.csv"]


# =============================================================== access control (1-8)
@pytest.mark.parametrize("url", EXPORTS + ["/api/admin/reports/registrations", "/api/admin/kyc", "/api/admin/vendors/x/documents"])
def test_01_unauthenticated_requests_are_refused(c, url):
    assert c.get(url).status_code == 401


@pytest.mark.parametrize("who", ["cust", "cust2", "seller", "uva"])
def test_02_non_admin_roles_cannot_use_admin_reports(c, who):
    for url in ("/api/admin/reports/sales", "/api/admin/reports/sales/export", "/api/admin/order-ops/orders.csv"):
        assert c.get(url, headers=H(who)).status_code == 403


def test_03_vendor_a_only_ever_gets_its_own_statement_report_and_catalogue(c):
    st = c.get("/api/vendor/finance/statement.csv", params={"vendor_id": S["vb"]["id"]}, headers=H("uva"))   # a foreign id is ignored
    assert st.status_code == 200 and "vb-only" not in st.text and len(rows_of(st.text)) == 4
    rep = c.get("/api/vendor/reports/current.csv", params={"vendor_id": S["vb"]["id"], "range": "custom", "date_from": "2026-01-01"}, headers=H("uva"))
    assert rep.status_code == 200 and "VB secret product" not in rep.text
    prod = c.get("/api/vendor/products/export.csv", headers=H("uva"))
    assert prod.status_code == 200 and "VB secret product" not in prod.text and "W4-va" in prod.text
    assert c.get(f"/api/admin/finance/vendors/{S['vb']['id']}/ledger", headers=H("uva")).status_code == 403


def test_04_a_customer_cannot_read_another_customers_orders(c):
    assert c.get("/api/orders/w4-order-cust", headers=H("cust2")).status_code in (403, 404)
    assert "w4-order-cust" not in c.get("/api/orders", headers=H("cust2")).text
    assert c.get("/api/orders/w4-order-cust", headers=H("cust")).status_code == 200


def test_05_a_homegenie_member_sees_no_customer_contact(c):
    r = c.get("/api/homegenie/orders", headers=H("seller"))
    assert r.status_code == 200 and "9000011111" not in r.text and "1 Road" not in r.text
    assert c.get("/api/admin/users", headers=H("seller")).status_code == 403
    assert c.get("/api/admin/reports/registrations", headers=H("seller")).status_code == 403


def test_06_support_admin_cannot_export_finance_or_order_data(c):
    for url in ("/api/admin/reports/payments/export", "/api/admin/reports/wallet/export", "/api/admin/reports/registrations/export",
                "/api/admin/order-ops/orders.csv"):
        assert c.get(url, headers=H("support")).status_code == 403, url
    assert c.get("/api/admin/payment-events", headers=H("support")).status_code == 403
    refused = audits(c, "export_refused", "payments")
    assert refused and refused[0]["new_value"]["reason"] == "role" and refused[0]["new_value"]["role"] == "support_admin"


def test_07_accounts_admin_gets_identity_values_masked_and_cannot_open_onboarding(c):
    vid = S["va"]["id"]
    k = c.get("/api/admin/kyc", headers=H("fin")).text
    assert PAN not in k and AADHAAR not in k and ACCT not in k                                       # identity values masked
    assert c.get(f"/api/admin/vendors/{vid}/onboarding", headers=H("fin")).status_code == 403          # existing VIEW_ROLES rule
    # Existing, tested behaviour kept (test_vendor_authority): accounts_admin cannot REVIEW documents but may READ the listing.
    # Whether it should read identity-document links is owner decision D-16 (D16-W4-6) - not changed by W4.
    assert c.get(f"/api/admin/vendors/{vid}/documents", headers=H("fin")).status_code == 200


def test_08_hidden_buttons_are_not_the_control_direct_api_calls_are_refused(c):
    # the Reports screen hides Export from support_admin; the server refuses it anyway (and every admin role, incl. support, still views)
    assert c.get("/api/admin/reports/sales/export", headers=H("support")).status_code == 403
    for who in ("sup", "adm", "fin", "support"):
        assert c.get("/api/admin/reports/sales", headers=H(who)).status_code == 200
    for who in ("sup", "adm", "fin"):
        assert c.get("/api/admin/reports/sales/export", headers=H(who)).status_code == 200


# =============================================================== field masking (9-15)
@pytest.mark.parametrize("who", ["sup", "adm", "fin", "support"])
def test_09_to_12_kyc_listing_masks_pan_aadhaar_account_and_ifsc_for_every_role(c, who):
    rec = next(r for r in c.get("/api/admin/kyc", headers=H(who)).json() if r["user_id"] == S["member"]["id"])
    assert rec["pan"] != PAN and rec["pan"].endswith("X") and "1234" in rec["pan"]
    assert rec["aadhaar"] == "XXXX-XXXX-1234"
    assert rec["bank_account"] == "XXXX9012" and rec["ifsc"] == "HDFC*******"


def test_13_contact_is_masked_in_the_bulk_report_and_its_csv(c):
    view = c.get("/api/admin/reports/registrations", headers=H("sup")).json()
    row = next(r for r in view["rows"] if r["distributor_id"] == "W4MEM")
    assert row["mobile"] == "••••••2233" and row["email"] == "p•••@example.com" and set(view["masked"]) == {"email", "mobile"}
    text = c.get("/api/admin/reports/registrations/export", headers=H("sup")).text
    assert MOBILE not in text and EMAIL not in text and "••••••2233" in text


def test_14_identity_document_links_stay_with_admin_roles_and_out_of_exports(c):
    for who in ("cust", "seller", "uva"):
        assert c.get(f"/api/admin/vendors/{S['vb']['id']}/documents", headers=H(who)).status_code == 403
    assert "vb.pdf" in c.get(f"/api/admin/vendors/{S['vb']['id']}/documents", headers=H("adm")).text
    for url, who in zip(EXPORTS, ("sup", "fin", "uva", "uva", "uva")):
        assert ".pdf" not in c.get(url, headers=H(who)).text                       # no export carries document links
    assert "documents" not in c.get("/api/vendor/finance/summary", headers=H("uva")).text


def test_15_no_unmasking_in_the_other_format(c):
    for report, secret in (("registrations", MOBILE), ("registrations", EMAIL), ("payments", "SECRETSESSION")):
        assert secret not in c.get(f"/api/admin/reports/{report}", headers=H("sup")).text
        assert secret not in c.get(f"/api/admin/reports/{report}/export", headers=H("sup")).text
    pay = c.get("/api/admin/reports/payments", headers=H("sup")).json()["rows"][0]
    assert pay["session_id"].endswith("123456") and pay["session_id"].startswith("•")


# =============================================================== export integrity (16-25)
@pytest.mark.parametrize("value", EVIL)
def test_16_every_formula_start_is_neutralised(value):
    assert exports.csv_cell(value).startswith("'")


@pytest.mark.parametrize("value,expected", [(-120.5, -120.5), (0, 0), ("-120.00", "-120.00"), ("+919876543210", "+919876543210"),
                                            ("Saree - silk", "Saree - silk"), (None, ""), (True, True), ("'=x", "'=x")])
def test_16b_legitimate_values_are_never_corrupted(value, expected):
    assert exports.csv_cell(value) == expected


def test_16c_formula_values_are_neutralised_in_real_exports(c):
    reg = rows_of(c.get("/api/admin/reports/registrations/export", headers=H("sup")).text)
    assert any(cell.startswith("'=HYPERLINK") for r in reg for cell in r)
    st = rows_of(c.get("/api/vendor/finance/statement.csv", headers=H("uva")).text)
    reasons = [r[6] for r in st[1:]]
    assert reasons[0].startswith("'=") and reasons[1].startswith("'+") and reasons[2] == "'-2+3"
    assert st[1][4] == "-120.50" and st[1][5] == "-12050"                                   # negative money untouched
    prod = c.get("/api/vendor/products/export.csv", headers=H("uva")).text
    assert "'@SUM(1+1)" in prod
    orders = c.get("/api/admin/order-ops/orders.csv", headers=H("fin")).text
    assert "'=W4ORD1" in orders


def test_17_too_large_exports_are_refused_not_truncated(c, monkeypatch):
    monkeypatch.setattr(admin_routes, "REPORT_EXPORT_MAX", 1)
    r = c.get("/api/admin/reports/registrations/export", headers=H("sup"))
    assert r.status_code == 413 and "limit is 1" in r.json()["detail"]
    assert audits(c, "export_refused", "registrations")[0]["new_value"]["reason"] == "too_many_rows"
    monkeypatch.setattr(finance_routes, "STATEMENT_MAX_ROWS", 2)
    assert c.get("/api/vendor/finance/statement.csv", headers=H("uva")).status_code == 413
    assert c.get("/api/vendor/finance/statement.csv", params={"date_from": "2026-10-03"}, headers=H("uva")).status_code == 200
    monkeypatch.setattr(admin_order_ops, "EXPORT_MAX_ROWS", 0)
    assert c.get("/api/admin/order-ops/orders.csv", headers=H("fin")).status_code == 413
    monkeypatch.setattr(vendor_routes, "PRODUCT_EXPORT_MAX", 0)
    assert c.get("/api/vendor/products/export.csv", headers=H("uva")).status_code == 413


@pytest.mark.parametrize("params", [{"date_from": "2026-13-01"}, {"date_to": "2026-02-30"}, {"date_from": "yesterday"},
                                    {"date_from": "2026-10-09", "date_to": "2026-10-01"}])
def test_18_invalid_date_ranges_are_rejected(c, params):
    assert c.get("/api/admin/reports/sales", params=params, headers=H("sup")).status_code == 400
    assert c.get("/api/admin/reports/sales/export", params=params, headers=H("sup")).status_code == 400
    assert c.get("/api/vendor/finance/statement.csv", params=params, headers=H("uva")).status_code == 400


def test_18b_a_date_range_selects_exactly_its_rows(c):
    st = rows_of(c.get("/api/vendor/finance/statement.csv", params={"date_from": "2026-10-02", "date_to": "2026-10-02"}, headers=H("uva")).text)
    assert len(st) == 2 and st[1][0].startswith("2026-10-02")
    reg = c.get("/api/admin/reports/registrations", params={"date_from": "2026-10-05", "date_to": "2026-10-05"}, headers=H("sup")).json()
    assert [r["distributor_id"] for r in reg["rows"]] == ["W4MEM"] and reg["total"] == 1


def test_19_report_totals_are_complete_and_truncation_is_declared(c, monkeypatch):
    full = c.get("/api/admin/reports/registrations", headers=H("sup")).json()
    assert full["total"] == len(full["rows"]) and not full["truncated"]
    monkeypatch.setattr(admin_routes, "REPORT_VIEW_ROWS", 2)
    part = c.get("/api/admin/reports/registrations", headers=H("sup")).json()
    assert len(part["rows"]) == 2 and part["total"] == full["total"] and part["truncated"] is True


def test_19b_order_list_pages_cover_every_order_once(c):
    seen, page = [], 1
    while True:
        d = c.get("/api/admin/order-ops/orders", params={"page": page, "page_size": 1}, headers=H("sup")).json()
        seen += [x["id"] for x in d["items"]]
        if page >= d["pages"]:
            break
        page += 1
    assert len(seen) == len(set(seen)) == d["total"]


def test_20_vendor_b_sees_none_of_vendor_a(c):
    st = c.get("/api/vendor/finance/statement.csv", headers=H("uvb")).text
    assert all("vb-only" in r[6] for r in rows_of(st)[1:]) and "HYPERLINK" not in st


def test_21_exports_write_no_files_create_no_links_and_are_not_cacheable(c):
    files_before = run(c, lambda: db.files.count_documents({}))
    tmp_before = set(os.listdir(tempfile.gettempdir()))
    for url, who in zip(EXPORTS, ("sup", "fin", "uva", "uva", "uva")):
        r = c.get(url, headers=H(who))
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert r.headers["cache-control"] == "no-store" and r.headers["content-disposition"].startswith("attachment;")
        assert r.headers["x-export-id"].startswith("exp_") and "http" not in r.headers["x-export-id"]
    assert run(c, lambda: db.files.count_documents({})) == files_before
    assert not [f for f in set(os.listdir(tempfile.gettempdir())) - tmp_before if f.endswith(".csv")]


def test_22_there_is_no_stored_download_to_expire(c):
    """No export is stored or linked: the only way to a CSV is an authorised request that builds it. An export id cannot fetch it."""
    eid = c.get("/api/admin/reports/sales/export", headers=H("sup")).headers["x-export-id"]
    for path in (f"/api/exports/{eid}", f"/api/admin/exports/{eid}", f"/api/files/{eid}"):
        assert c.get(path, headers=H("sup")).status_code == 404
    import re
    paths = [getattr(r, "path", "") for r in server.app.routes]
    # a stored-download route would take an id AFTER an export segment (e.g. /exports/{id}); /reports/{report}/export names a report
    assert not [p for p in paths if re.search(r"export[^/]*/\{", p)]


def test_23_a_failed_export_downloads_nothing_and_is_recorded(c, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("disk full (simulated)")
    monkeypatch.setattr(exports, "csv_text", boom)
    r = c.get("/api/admin/reports/sales/export", headers=H("sup"))
    assert r.status_code == 500 and not r.headers["content-type"].startswith("text/csv")
    a = audits(c, "export_failed", "sales")[0]["new_value"]
    assert a["reason"] == "RuntimeError" and "disk full" not in str(a)


def test_24_every_export_leaves_one_audit_record_tied_to_the_response(c):
    r = c.get("/api/admin/reports/sales/export", params={"date_from": "2026-01-01"}, headers=H("fin"))
    rec = next(a for a in audits(c, "export_success", "sales") if a["new_value"]["export_id"] == r.headers["x-export-id"])
    v = rec["new_value"]
    assert rec["user_id"] == S["fin"]["id"] and v["role"] == "accounts_admin" and v["format"] == "csv"
    assert v["date_from"] == "2026-01-01" and v["rows"] == len(rows_of(r.text)) - 1 and rec["created_at"]
    for url, kind in (("/api/vendor/finance/statement.csv", "vendor_statement"), ("/api/vendor/reports/current.csv", "vendor_current_report"),
                      ("/api/vendor/products/export.csv", "vendor_products")):
        eid = c.get(url, headers=H("uva")).headers["x-export-id"]
        got = [a for a in audits(c, "export_success", kind) if a["new_value"]["export_id"] == eid]
        assert got and got[0]["new_value"]["scope"] == f"vendor:{S['va']['id']}"


def test_25_audit_records_hold_no_sensitive_values(c):
    c.get("/api/admin/order-ops/orders.csv", params={"q": f"{MOBILE} {EMAIL}"}, headers=H("fin"))
    recent = run(c, lambda: db.audit_logs.find({"entity": {"$in": ["export", "orders", "report"]}}, {"_id": 0}).to_list(500))
    blob = str(recent)
    for secret in (MOBILE, EMAIL, PAN, AADHAAR, ACCT, "SECRETSESSION", "Bearer", "password"):
        assert secret not in blob, secret
    assert any("••••••••33" in str(a.get("new_value")) for a in recent)        # the search shape is kept, the number is not


def test_25b_audit_records_cannot_be_deleted_or_edited_through_the_api(c):
    for who in ("sup", "adm", "fin", "support"):
        assert c.delete("/api/admin/audit-logs", headers=H(who)).status_code == 405
    writes = [r for r in server.app.routes if "audit" in getattr(r, "path", "") and getattr(r, "methods", set()) & {"PUT", "PATCH", "POST"}]
    assert writes == []


# =============================================================== regression (26-30)
def test_26_finance_reports_still_work_for_finance(c):
    for url in ("/api/admin/finance/system-integrity", "/api/admin/finance/negative-wallets", "/api/admin/payment-events"):
        assert c.get(url, headers=H("fin")).status_code == 200, url


def test_27_vendor_statement_amounts_are_exact(c):
    st = rows_of(c.get("/api/vendor/finance/statement.csv", headers=H("uva")).text)
    assert st[0] == ["posted_at", "entry_id", "type", "order_id", "amount_inr", "amount_paise", "reason", "reverses"]
    assert [r[5] for r in st[1:]] == ["-12050", "5000", "5000"]


def test_28_member_commission_statement_still_answers(c):
    r = c.get("/api/commissions/statement", headers=H("seller"))
    assert r.status_code == 200


def test_29_customer_order_history_still_lists_own_orders(c):
    assert "w4-order-cust" in c.get("/api/orders", headers=H("cust")).text


def test_30_admin_dashboard_and_report_screens_still_answer(c):
    assert c.get("/api/admin/dashboard", headers=H("sup")).status_code == 200
    for rep in admin_routes.REPORTS:
        r = c.get(f"/api/admin/reports/{rep}", headers=H("adm"))
        assert r.status_code == 200 and {"rows", "fields", "total", "truncated"} <= set(r.json())
    assert c.get("/api/admin/reports/nope", headers=H("adm")).status_code == 404


# =============================================================== readiness W4 (c) money from paise, (e) totals unchanged
def test_31_report_money_is_printed_from_exact_paise(c):
    async def seed():
        await db.orders.insert_one({"id": "w4-money-1", "order_number": "W4M1", "user_id": "x", "payment_status": "paid", "status": "delivered",
                                    "subtotal": 0.1 + 0.2, "subtotal_paise": 30, "gst_amount": 0.01, "gst_paise": 1, "total": 123.45000000001,
                                    "total_paise": 12345, "created_at": "2026-09-01T10:00:00+00:00"})
        await db.orders.insert_one({"id": "w4-money-2", "order_number": "W4M2", "user_id": "x", "payment_status": "paid", "status": "delivered",
                                    "subtotal": 10.5, "gst_amount": 0.5, "total": 11.0, "created_at": "2026-09-02T10:00:00+00:00"})   # legacy: no paise
    run(c, seed)
    rows = {r["order_number"]: r for r in c.get("/api/admin/reports/sales", params={"date_from": "2026-09-01", "date_to": "2026-09-02"},
                                                 headers=H("sup")).json()["rows"]}
    assert rows["W4M1"]["subtotal"] == "0.30" and rows["W4M1"]["gst_amount"] == "0.01" and rows["W4M1"]["total"] == "123.45"
    assert rows["W4M2"]["total"] == "11.00" and rows["W4M2"]["subtotal"] == "10.50"
    assert all(set(r) <= set(admin_routes.REPORTS["sales"][2]) for r in rows.values())                 # no helper keys leak
    csv_rows = rows_of(c.get("/api/admin/reports/sales/export", params={"date_from": "2026-09-01", "date_to": "2026-09-02"}, headers=H("sup")).text)
    assert {r[0]: r[4] for r in csv_rows[1:]} == {"W4M1": "123.45", "W4M2": "11.00"}


def test_32_report_totals_equal_the_stored_paise_totals(c):
    text = c.get("/api/admin/reports/sales/export", headers=H("fin")).text
    exported = sum(round(float(r[4]) * 100) for r in rows_of(text)[1:])
    stored = run(c, lambda: db.orders.aggregate([{"$match": {"payment_status": "paid"}},
                                                 {"$group": {"_id": None, "p": {"$sum": {"$ifNull": ["$total_paise", {"$round": [{"$multiply": ["$total", 100]}, 0]}]}}}}]).to_list(1))
    assert exported == int(stored[0]["p"])
