"""HOME GENIES — local DEMO environment for manual testing (Admin, Vendor and HomeGenie panels).

    seed     python scripts/demo_environment.py seed      builds the demo data through the REAL API routes (in-process)
    cleanup  python scripts/demo_environment.py cleanup   shows what would be removed (dry run)
             python scripts/demo_environment.py cleanup --apply   removes every record carrying this batch's demo marker

SAFETY
- Runs ONLY against the isolated local test MongoDB (127.0.0.1:27018) and a database whose name ends in "_demo_test".
  It refuses anything else, so it can never touch production or Atlas.
- No payment gateway is contacted: payments use the app's manual UPI path (customer claim -> admin confirmation with a
  reference), COD uses the app's collection confirmation, settlements/withdrawals are recorded with demo references only.
- Every document created by the seed carries   is_demo: true   and   demo_batch_id: <batch>   (added after the run to every
  collection of the dedicated demo database), so cleanup removes exactly the demo batch and nothing else.

All data goes through the application's own workflows (applications, onboarding, approvals, products, staff invitations,
orders, payment confirmation, fulfilment, COD collection, returns, refund cases, activation, KYC, withdrawals, settlements and
the commission release job), so stock, ledgers, commissions and wallets stay internally consistent.
"""
import json
import os
import sys
from datetime import date, datetime, timezone

BATCH = os.environ.get("DEMO_BATCH_ID", "demo-" + datetime.now(timezone.utc).strftime("%Y%m%d"))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))


def _guard():
    url, name = os.environ.get("MONGO_URL", ""), os.environ.get("DB_NAME", "")
    if "127.0.0.1:27018" not in url and "localhost:27018" not in url:
        raise SystemExit("refusing: the demo environment runs only on the isolated local test MongoDB (127.0.0.1:27018)")
    if not name.endswith("_demo_test"):
        raise SystemExit("refusing: DB_NAME must be a dedicated *_demo_test database")


_guard()
os.environ.setdefault("CRON_SECRET", "demo-cron-" + BATCH)
os.environ.setdefault("JWT_SECRET", "demo-jwt-" + "x" * 40)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import core  # noqa: E402
from core import db, hash_password, new_id, now_iso  # noqa: E402

PW = {   # demo passwords (local only)
    "super_admin": "Demo@SuperAdmin2026", "admin": "Demo@Admin2026", "support_admin": "Demo@Support2026", "accounts_admin": "Demo@Accounts2026",
    "vendor": "Vendor@Demo2026", "staff": "Staff@Demo2026", "genie": "Genie@Demo2026", "customer": "Customer@Demo2026",
}
REPORT = {"batch": BATCH, "accounts": [], "counts": {}, "notes": []}
c = None
TOK = {}


# ------------------------------------------------------------------ helpers
def ok(r, what, codes=(200,)):
    if r.status_code not in codes:
        raise SystemExit(f"FAILED: {what}: {r.status_code} {r.text[:400]}")
    return r.json() if r.content else {}


def H(key):
    return {"Authorization": f"Bearer {TOK[key]}"}


def account(panel, name, role, login, password, link):
    REPORT["accounts"].append({"panel": panel, "account": name, "role": role, "login": login, "password": password, "link": link})


def login_user(key, ident, password):
    TOK[key] = ok(c.post("/api/auth/login", json={"email": ident, "password": password}), f"login {key}")["token"]


def login_admin(key, username, password):
    TOK[key] = ok(c.post("/api/auth/admin-login", json={"username": username, "password": password}), f"admin login {key}")["token"]


def run(coro_fn):
    return c.portal.call(coro_fn)


ADDR = {"Rohit": {"full_name": "Rohit Mehra", "mobile": "9810000101", "line1": "B-14, Green Park", "city": "New Delhi", "state": "Delhi", "pincode": "110016"},
        "Kavita": {"full_name": "Kavita Joshi", "mobile": "9810000102", "line1": "C-7, Sector 21", "city": "Noida", "state": "Uttar Pradesh", "pincode": "201301"},
        "Imran": {"full_name": "Imran Khan", "mobile": "9810000103", "line1": "45, DLF Phase 2", "city": "Gurugram", "state": "Haryana", "pincode": "122002"}}


def order(cust_key, addr, items, seller=None, cod=False):
    body = {"items": items, "address": addr, "payment_method": "cod" if cod else "online"}
    if seller:
        body["seller_ref"] = seller
    return ok(c.post("/api/orders", headers=H(cust_key), json=body), f"order by {cust_key}")


def pay(cust_key, order_id, ref):
    ok(c.post("/api/payments/upi-claim", headers=H(cust_key), json={"order_id": order_id, "reference": ref}), "upi claim")
    ok(c.put(f"/api/admin/payments/upi-confirm/{order_id}", headers=H("admin"), json={"reference": ref}), "upi confirm")


def fulfil(vkey, order_id, steps):
    notes = {"rejected": "Item damaged at our warehouse during quality check", "cancelled": "Stock damaged before dispatch",
             "delivered": "Delivered to customer, recipient signed (demo)"}
    for st in steps:
        body = {"status": st, "note": notes.get(st, "")}
        if st == "dispatched":
            body.update({"carrier": "Delhivery (demo)", "tracking_number": f"DEMO{order_id[:8].upper()}"})
        ok(c.post(f"/api/vendor/orders/{order_id}/fulfilment", headers=H(vkey), json=body), f"fulfil {st}")


def release_commissions(tag):
    ok(c.post("/api/cron/release-points", headers={"Authorization": f"Bearer {os.environ['CRON_SECRET']}"}, json={"run_id": f"{BATCH}-{tag}"}), "release job")


def insert_admins():
    async def go():
        for i, (role, user, name) in enumerate((("super_admin", "demo.superadmin", "Demo Super Admin"), ("admin", "demo.admin", "Demo Admin"),
                                                ("support_admin", "demo.support", "Demo Support Admin"), ("accounts_admin", "demo.accounts", "Demo Accounts Admin"))):
            await db.users.insert_one({"id": new_id(), "distributor_id": f"DEMOADM{i + 1}", "username": user, "full_name": name, "mobile": f"981000000{i + 1}",
                                       "email": f"{user}@demo.homegenies.test", "password_hash": hash_password(PW[role]), "role": role,
                                       "status": "green", "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()})
    run(go)


# ------------------------------------------------------------------ vendor onboarding through the real flow
def onboard_and_approve(vid, sections, docs, commission_pct):
    for section, body in sections.items():
        ok(c.put(f"/api/admin/vendors/{vid}/onboarding/{section}", headers=H("admin"), json=body), f"onboarding {section}")
    for t in docs:
        d = ok(c.post(f"/api/admin/vendors/{vid}/onboarding/documents", headers=H("admin"),
                      json={"type": t, "url": f"https://cdn.demo.homegenies.test/kyc/{vid[:8]}/{t}.pdf", "note": "Demo document"}), f"doc {t}")
        ok(c.post(f"/api/admin/vendor-documents/{d['id']}/review", headers=H("support"), json={"status": "verified"}), f"verify {t}")
    ag = ok(c.post(f"/api/admin/finance/vendors/{vid}/agreements", headers=H("accounts"),
                   json={"commission_pct": commission_pct, "fixed_fee_paise": 0, "settlement_schedule": "monthly",
                         "effective_from": date.today().isoformat(), "notes": "Demo commercial agreement"}), "agreement draft")
    ok(c.post(f"/api/admin/finance/agreements/{ag['id']}/approve", headers=H("super")), "agreement approve")
    ok(c.post(f"/api/admin/vendors/{vid}/submit-for-approval", headers=H("admin")), "submit for approval")
    return ok(c.post(f"/api/admin/vendors/{vid}/final-review", headers=H("super"), json={"action": "approve", "reason": "Demo approval"}), "final approve")


def sections_for(legal_name, display, btype, roles, desc, cats, person, pan, gstin, addr, bank, extra_legal=None):
    legal = {"pan": pan, "gst_registered": True, "gstin": gstin, **(extra_legal or {})}
    return {
        "business": {"legal_name": legal_name, "display_name": display, "business_type": btype, "supplier_roles": roles, "description": desc,
                     "categories": cats, "year_established": 2011},
        "person": {**person, "relationship": "proprietor" if btype == "proprietorship" else "director", "is_authorised_signatory": True},
        "legal": legal,
        "addresses": {"registered": addr, "pickup_same_as": "registered", "return_same_as": "pickup",
                      "pickup_contact_name": person["full_name"], "pickup_contact_phone": person["mobile"]},
        "operations": {"handling_days": 2, "support_phone": person["mobile"], "support_email": person["email"], "support_hours": "Mon-Sat 10am-7pm",
                       "packaging_by": "vendor", "shipping_by": "vendor"},
        "bank": bank,
    }


def product(vkey, body, approve=True, reject_reason=None):
    p = ok(c.post("/api/vendor/products", headers=H(vkey), json=body), f"product {body['sku']}")
    if approve:
        ok(c.post(f"/api/admin/vendor-products/{p['id']}/decision", headers=H("admin"), json={"action": "approve"}), "approve product")
    elif reject_reason:
        ok(c.post(f"/api/admin/vendor-products/{p['id']}/decision", headers=H("admin"), json={"action": "reject", "reason": reject_reason}), "reject product")
    return p


def register_genie(key, name, mobile, email, sponsor, password):
    ok(c.post("/api/auth/register-request", json={"full_name": name, "mobile": mobile, "email": email, "password": password,
                                                   "confirm_password": password, "sponsor_id": sponsor or "", "city": "New Delhi",
                                                   "state": "Delhi", "pincode": "110001", "address": "Demo address"}), f"register {key}")
    login_user(key, mobile, password)
    return run(lambda: db.users.find_one({"mobile": mobile}, {"_id": 0}))


# ------------------------------------------------------------------ the seed
def seed():
    async def fresh():
        await server.client.drop_database(os.environ["DB_NAME"])
        await server._init_db()
        await db_indexes.apply()
    run(fresh)
    for k in list(core.RATE_LIMITS):                       # many logins/registrations in one run; limits are tested elsewhere
        core.RATE_LIMITS[k] = (100000, 3600)

    # ---------------- admins (no API creates admins; seeded like the env admin)
    insert_admins()
    for key, role, user in (("super", "super_admin", "demo.superadmin"), ("admin", "admin", "demo.admin"), ("support", "support_admin", "demo.support"),
                            ("accounts", "accounts_admin", "demo.accounts")):
        login_admin(key, user, PW[role])
        account("Admin", f"Demo {role.replace('_', ' ').title()}", role, user, PW[role], "/admin-secure-login")

    # ---------------- money settings for the demo: release window 0 first (so some earnings are genuinely released)
    ok(c.put("/api/admin/settings", headers=H("super"), json={"return_window_days": 0}), "window 0")

    # ---------------- VENDOR 1: public "Apply to sell" -> applicant signs in -> admin converts -> onboarding -> approval
    v1_mobile, v1_email = "9820000101", "owner@kanchisilk.demo.homegenies.test"
    ok(c.post("/api/vendor-applications", json={"business_name": "Kanchi Silk House", "business_type": "private_limited",
                                                 "description": "Third-generation silk weavers from Kanchipuram supplying temple-border and bridal sarees.",
                                                 "categories": ["Sarees", "Fashion Products"], "contact_name": "Lakshmi Narayanan", "mobile": v1_mobile,
                                                 "email": v1_email, "city": "Chennai", "state": "Tamil Nadu", "website": "https://kanchisilk.demo.homegenies.test",
                                                 "consent": True, "password": PW["vendor"], "confirm_password": PW["vendor"]}), "v1 apply")
    app1 = run(lambda: db.vendor_applications.find_one({"mobile": v1_mobile}, {"_id": 0}))
    ok(c.post(f"/api/admin/vendor-applications/{app1['id']}/action", headers=H("admin"), json={"action": "review"}), "v1 review")
    v1 = ok(c.post(f"/api/admin/vendor-applications/{app1['id']}/action", headers=H("admin"), json={"action": "convert"}), "v1 convert")
    v1id = v1["vendor_id"]
    onboard_and_approve(v1id, sections_for(
        "Kanchi Silk House Private Limited", "Kanchi Silk House", "private_limited", ["manufacturer", "brand_owner"],
        "Handwoven Kanchipuram silk sarees, bridal collections and festive dupattas made in our own looms.", ["Sarees", "Fashion Products"],
        {"full_name": "Lakshmi Narayanan", "designation": "Managing Director", "mobile": v1_mobile, "email": v1_email},
        "AAACK1234F", "33AAACK1234F1Z9", {"line1": "12, Gandhi Road", "city": "Kanchipuram", "state": "Tamil Nadu", "pincode": "631501"},
        {"account_holder": "Kanchi Silk House Pvt Ltd", "bank_name": "Indian Bank", "account_number": "60123456789", "account_number_confirm": "60123456789",
         "ifsc": "IDIB000K001", "account_type": "current"}, {"cin": "U17110TN2011PTC081234"}),
        ["pan", "bank_proof", "address_proof", "identity", "gst", "business_registration"], 12.0)
    login_user("v1", v1_email, PW["vendor"])
    account("Vendor", "Vendor 1 Owner — Kanchi Silk House", "vendor owner", v1_email, PW["vendor"], "/vendor/login")

    # ---------------- VENDOR 2: admin-started onboarding -> approval -> owner invitation accepted
    v2_mobile, v2_email = "9820000201", "owner@gharessentials.demo.homegenies.test"
    v2 = ok(c.post("/api/admin/vendors/create", headers=H("admin"), json={"business_name": "Ghar Essentials", "full_name": "Rakesh Agarwal",
                                                                          "mobile": v2_mobile, "email": v2_email}), "v2 create")
    v2id = v2["vendor_id"]
    appr2 = onboard_and_approve(v2id, sections_for(
        "Ghar Essentials", "Ghar Essentials", "proprietorship", ["wholesaler", "distributor"],
        "Household cleaning, kitchen essentials and herbal personal-care products for everyday family needs.",
        ["Household Essentials", "Makeup, Beauty & Skincare"],
        {"full_name": "Rakesh Agarwal", "designation": "Proprietor", "mobile": v2_mobile, "email": v2_email},
        "ABCPA1234K", "07ABCPA1234K1Z5", {"line1": "88, Chandni Chowk", "city": "New Delhi", "state": "Delhi", "pincode": "110006"},
        {"account_holder": "Rakesh Agarwal", "bank_name": "HDFC Bank", "account_number": "50100987654321", "account_number_confirm": "50100987654321",
         "ifsc": "HDFC0000123", "account_type": "current"}), ["pan", "bank_proof", "address_proof", "identity", "gst"], 10.0)
    ok(c.post("/api/vendor/invitation/owner/accept", json={"token": appr2["invitation"]["token"], "password": PW["vendor"]}), "v2 accept invitation")
    login_user("v2", v2_email, PW["vendor"])
    account("Vendor", "Vendor 2 Owner — Ghar Essentials", "vendor owner", v2_email, PW["vendor"], "/vendor/login")

    # ---------------- VENDOR 3: approved, then SUSPENDED by admin (with a product)
    v3_mobile, v3_email = "9820000301", "owner@rangoli.demo.homegenies.test"
    ok(c.post("/api/vendor-applications", json={"business_name": "Rangoli Fashion Studio", "business_type": "proprietorship",
                                                 "description": "Block-printed kurtis and festive fashion from Jaipur.", "categories": ["Fashion Products"],
                                                 "contact_name": "Pooja Rathore", "mobile": v3_mobile, "email": v3_email, "city": "Jaipur",
                                                 "state": "Rajasthan", "website": "", "consent": True, "password": PW["vendor"],
                                                 "confirm_password": PW["vendor"]}), "v3 apply")
    app3 = run(lambda: db.vendor_applications.find_one({"mobile": v3_mobile}, {"_id": 0}))
    v3id = ok(c.post(f"/api/admin/vendor-applications/{app3['id']}/action", headers=H("admin"), json={"action": "convert"}), "v3 convert")["vendor_id"]
    onboard_and_approve(v3id, sections_for(
        "Rangoli Fashion Studio", "Rangoli Fashion Studio", "proprietorship", ["manufacturer"], "Block-printed kurtis and festive fashion from Jaipur.",
        ["Fashion Products"], {"full_name": "Pooja Rathore", "designation": "Proprietor", "mobile": v3_mobile, "email": v3_email},
        "BCDPR4321L", "08BCDPR4321L1Z2", {"line1": "21, Bapu Bazaar", "city": "Jaipur", "state": "Rajasthan", "pincode": "302003"},
        {"account_holder": "Pooja Rathore", "bank_name": "State Bank of India", "account_number": "30987654321", "account_number_confirm": "30987654321",
         "ifsc": "SBIN0000654", "account_type": "current"}), ["pan", "bank_proof", "address_proof", "identity", "gst"], 10.0)
    login_user("v3", v3_email, PW["vendor"])
    product("v3", {"sku": "RFS-KURTI-01", "name": "Block Print Cotton Kurti", "mrp": 1299, "selling_price": 999, "stock": 15, "category": "Fashion Products",
                   "description": "Hand block-printed cotton kurti.", "images": ["/brand/pillar-fashion.jpg"]})
    ok(c.post(f"/api/admin/vendors/{v3id}/decision", headers=H("admin"),
              json={"action": "suspend", "reason": "Demo: KYC document expired, awaiting renewal"}), "v3 suspend")
    account("Vendor", "Vendor 3 Owner — Rangoli (SUSPENDED)", "vendor owner", v3_email, PW["vendor"], "/vendor/login")

    # ---------------- VENDOR 4: applicant only (onboarding state; can sign in, cannot sell)
    v4_mobile, v4_email = "9820000401", "owner@banarasweaves.demo.homegenies.test"
    ok(c.post("/api/vendor-applications", json={"business_name": "Banaras Weaves Collective", "business_type": "partnership",
                                                 "description": "Cooperative of Varanasi weavers supplying Banarasi silk sarees.", "categories": ["Sarees"],
                                                 "contact_name": "Shabana Ansari", "mobile": v4_mobile, "email": v4_email, "city": "Varanasi",
                                                 "state": "Uttar Pradesh", "website": "", "consent": True, "password": PW["vendor"],
                                                 "confirm_password": PW["vendor"]}), "v4 apply")
    account("Vendor", "Vendor 4 — Banaras Weaves (APPLICATION / ONBOARDING)", "vendor applicant", v4_email, PW["vendor"], "/vendor/login")

    # ---------------- products
    P = {}
    P["kss"] = product("v1", {"sku": "KSH-KANJ-001", "name": "Kanjivaram Silk Saree — Temple Border", "mrp": 8999, "selling_price": 7499, "stock": 25,
                              "category": "Sarees", "description": "Pure mulberry silk with zari temple border. 6.3 m with blouse piece.",
                              "images": ["/brand/pillar-sarees.jpg"], "attributes": {"fabric": "Pure silk", "weave_style": "Kanjivaram", "length_m": 6.3}})
    P["ban"] = product("v1", {"sku": "KSH-BANG-002", "name": "Banarasi Georgette Saree", "mrp": 3999, "selling_price": 3299, "stock": 0,
                              "category": "Sarees", "description": "Lightweight georgette with Banarasi zari motifs.", "images": ["/brand/pillar-sarees.jpg"],
                              "variants": [{"sku": "KSH-BANG-002-MAR", "attributes": {"colour": "Maroon"}, "stock": 12},
                                           {"sku": "KSH-BANG-002-NAV", "attributes": {"colour": "Navy"}, "stock": 6}]})
    P["cot"] = product("v1", {"sku": "KSH-COTN-003", "name": "Cotton Handloom Saree — Daily Wear", "mrp": 1499, "selling_price": 1199, "stock": 40,
                              "category": "Sarees", "description": "Breathable handloom cotton for everyday wear.", "images": ["/brand/pillar-sarees.jpg"]})
    P["dup"] = product("v1", {"sku": "KSH-DUPT-004", "name": "Chanderi Silk Dupatta", "mrp": 999, "selling_price": 799, "stock": 4,
                              "category": "Fashion Products", "description": "Chanderi silk dupatta with gota border.", "images": ["/brand/pillar-fashion.jpg"]})
    P["kur"] = product("v1", {"sku": "KSH-KURT-005", "name": "Embroidered Kurti Set", "mrp": 2299, "selling_price": 1899, "stock": 0,
                              "category": "Fashion Products", "description": "Kurti with palazzo and dupatta.", "images": ["/brand/pillar-fashion.jpg"],
                              "variants": [{"sku": "KSH-KURT-005-S", "attributes": {"size": "S"}, "stock": 5},
                                           {"sku": "KSH-KURT-005-M", "attributes": {"size": "M"}, "stock": 0},
                                           {"sku": "KSH-KURT-005-L", "attributes": {"size": "L"}, "stock": 4}]})
    P["org"] = product("v1", {"sku": "KSH-ORGZ-006", "name": "Organza Party Wear Saree", "mrp": 4599, "selling_price": 3899, "stock": 0,
                              "category": "Sarees", "description": "Sheer organza with sequin work (currently out of stock).", "images": ["/brand/pillar-sarees.jpg"]})
    product("v1", {"sku": "KSH-PAIT-007", "name": "Paithani Silk Saree (awaiting review)", "mrp": 12999, "selling_price": 10999, "stock": 6,
                   "category": "Sarees", "description": "Peacock-motif Paithani — submitted, waiting for admin review.", "images": ["/brand/pillar-sarees.jpg"]}, approve=False)
    product("v1", {"sku": "KSH-MISC-008", "name": "Silk Saree Cover Bag", "mrp": 499, "selling_price": 399, "stock": 20,
                   "category": "Fashion Products", "description": "Rejected demo product.", "images": []}, approve=False,
            reject_reason="Please add clear product photos and dimensions")
    P["flr"] = product("v2", {"sku": "GE-FLOOR-101", "name": "Herbal Floor Cleaner 1L", "mrp": 249, "selling_price": 199, "stock": 120,
                              "category": "Household Essentials", "description": "Neem and pine oil floor cleaner.", "images": ["/brand/pillar-household.jpg"]})
    P["kit"] = product("v2", {"sku": "GE-KITCH-102", "name": "Kitchen Essentials Combo", "mrp": 1299, "selling_price": 999, "stock": 30,
                              "category": "Household Essentials", "description": "Steel scrubbers, dish bar, microfibre cloths and jar set.",
                              "images": ["/brand/pillar-household.jpg"]})
    P["ubt"] = product("v2", {"sku": "GE-UBTAN-103", "name": "Ubtan Face Pack 100g", "mrp": 399, "selling_price": 329, "stock": 60,
                              "category": "Makeup, Beauty & Skincare", "description": "Turmeric and sandalwood face pack.", "images": ["/brand/pillar-beauty.jpg"]})
    P["lip"] = product("v2", {"sku": "GE-LIPS-104", "name": "Matte Lipstick", "mrp": 499, "selling_price": 399, "stock": 0,
                              "category": "Makeup, Beauty & Skincare", "description": "Long-wear matte lipstick.", "images": ["/brand/pillar-beauty.jpg"],
                              "variants": [{"sku": "GE-LIPS-104-ROSE", "attributes": {"shade": "Rose"}, "stock": 20},
                                           {"sku": "GE-LIPS-104-RED", "attributes": {"shade": "Classic Red"}, "stock": 18},
                                           {"sku": "GE-LIPS-104-NUDE", "attributes": {"shade": "Nude"}, "stock": 3}]})
    P["cop"] = product("v2", {"sku": "GE-COPPR-105", "name": "Copper Water Bottle 1L", "mrp": 899, "selling_price": 749, "stock": 3,
                              "category": "Household Essentials", "description": "Pure copper bottle (low stock).", "images": ["/brand/pillar-household.jpg"]})

    # ---------------- staff for vendor 1 (owner invites; each accepts with their own password)
    for i, (role, name) in enumerate((("store_manager", "Arjun Store Manager"), ("product_manager", "Divya Product Manager"),
                                      ("order_manager", "Karan Order Manager"), ("inventory_staff", "Meena Inventory Staff"),
                                      ("finance_viewer", "Suresh Finance Viewer"))):
        mobile = f"98300001{i:02d}"
        inv = ok(c.post("/api/vendor/staff/invitations", headers=H("v1"), json={"mobile": mobile, "full_name": name, "role": role}), f"invite {role}")
        ok(c.post("/api/vendor/staff/accept", json={"token": inv["token"], "mobile": mobile, "full_name": name, "password": PW["staff"]}), f"accept {role}")
        account("Vendor", f"Vendor 1 Staff — {name}", role, mobile, PW["staff"], "/vendor/login")

    # ---------------- HomeGenies (register -> own qualifying purchase -> admin activation), sponsor chain Meera > Anita > Priya > Neha
    g = {}
    g["meera"] = register_genie("meera", "Meera Iyer", "9840000101", "meera@demo.homegenies.test", "", PW["genie"])
    addr_g = {"full_name": "Meera Iyer", "mobile": "9840000101", "line1": "Flat 3B, Lodhi Colony", "city": "New Delhi", "state": "Delhi", "pincode": "110003"}

    def activate(key, addr, items):
        o = order(key, addr, items)
        pay(key, o["id"], f"DEMOUPI{o['order_number']}")
        ok(c.post(f"/api/admin/activations/{g[key]['id']}/approve", headers=H("admin"), json={"order_id": o["id"], "note": "Demo activation purchase"}),
           f"activate {key}")
        return o

    act = {"meera": activate("meera", addr_g, [{"product_id": P["kss"]["id"], "quantity": 1}])}
    g["anita"] = register_genie("anita", "Anita Verma", "9840000102", "anita@demo.homegenies.test", g["meera"]["distributor_id"], PW["genie"])
    act["anita"] = activate("anita", {**addr_g, "full_name": "Anita Verma", "mobile": "9840000102"}, [{"product_id": P["kit"]["id"], "quantity": 3}])
    g["priya"] = register_genie("priya", "Priya Sharma", "9840000103", "priya@demo.homegenies.test", g["anita"]["distributor_id"], PW["genie"])
    act["priya"] = activate("priya", {**addr_g, "full_name": "Priya Sharma", "mobile": "9840000103"},
                            [{"product_id": P["ban"]["id"], "quantity": 1, "variant_sku": "KSH-BANG-002-MAR"}])
    g["neha"] = register_genie("neha", "Neha Gupta", "9840000104", "neha@demo.homegenies.test", g["priya"]["distributor_id"], PW["genie"])
    for key, label in (("priya", "Home Genie 1 — Priya Sharma (ACTIVE, main)"), ("neha", "Home Genie 2 — Neha Gupta (NEW, not yet activated)"),
                       ("anita", "Home Genie 3 — Anita Verma (EARNINGS / WALLET demo)"), ("meera", "Home Genie 4 — Meera Iyer (team leader)")):
        account("Home Genies", label, "distributor (HomeGenie)", g[key]["mobile"], PW["genie"], "/login")
    # the activation orders are delivered by the vendors
    fulfil("v1", act["meera"]["id"], ["accepted", "packed", "dispatched", "delivered"])
    fulfil("v2", act["anita"]["id"], ["accepted", "packed", "dispatched", "delivered"])
    fulfil("v1", act["priya"]["id"], ["accepted", "packed", "dispatched", "delivered"])

    # ---------------- customers (shoppers; RED accounts that are not HomeGenies)
    for key, name, mobile in (("rohit", "Rohit Mehra", "9810000101"), ("kavita", "Kavita Joshi", "9810000102"), ("imran", "Imran Khan", "9810000103")):
        register_genie(key, name, mobile, f"{key}@demo.homegenies.test", "", PW["customer"])
        account("Customer / Shop", f"Customer — {name}", "customer (buyer)", mobile, PW["customer"], "/login")
    pr, an = g["priya"]["distributor_id"], g["anita"]["distributor_id"]

    # ---------------- PHASE A (release window 0): sales through HomeGenie links, delivered -> commissions released by the job
    a1 = order("rohit", ADDR["Rohit"], [{"product_id": P["cot"]["id"], "quantity": 2}], seller=pr)
    pay("rohit", a1["id"], f"DEMOUPI{a1['order_number']}")
    fulfil("v1", a1["id"], ["accepted", "packed", "dispatched", "delivered"])
    a2 = order("kavita", ADDR["Kavita"], [{"product_id": P["kit"]["id"], "quantity": 2}, {"product_id": P["flr"]["id"], "quantity": 3}], seller=an)
    pay("kavita", a2["id"], f"DEMOUPI{a2['order_number']}")
    fulfil("v2", a2["id"], ["accepted", "packed", "dispatched", "delivered"])
    a3 = order("imran", ADDR["Imran"], [{"product_id": P["kss"]["id"], "quantity": 1}], seller=pr)
    pay("imran", a3["id"], f"DEMOUPI{a3['order_number']}")
    fulfil("v1", a3["id"], ["accepted", "packed", "dispatched", "delivered"])
    release_commissions("phaseA")
    ok(c.put("/api/admin/settings", headers=H("super"), json={"return_window_days": 7}), "window back to 7")

    # ---------------- PHASE B (normal 7-day window): pending earnings and every operational state
    b1 = order("rohit", ADDR["Rohit"], [{"product_id": P["ban"]["id"], "quantity": 1, "variant_sku": "KSH-BANG-002-NAV"},
                                          {"product_id": P["ubt"]["id"], "quantity": 2}, {"product_id": P["lip"]["id"], "quantity": 1, "variant_sku": "GE-LIPS-104-ROSE"}],
               seller=pr)                                                                    # MULTI-VENDOR order
    pay("rohit", b1["id"], f"DEMOUPI{b1['order_number']}")
    fulfil("v1", b1["id"], ["accepted", "packed", "dispatched"])                              # V1 part in transit
    fulfil("v2", b1["id"], ["accepted"])                                                      # V2 part accepted
    b2 = order("imran", ADDR["Imran"], [{"product_id": P["dup"]["id"], "quantity": 1}], seller=pr)
    pay("imran", b2["id"], f"DEMOUPI{b2['order_number']}")                                     # V1: NEW, awaiting acceptance
    b3 = order("kavita", ADDR["Kavita"], [{"product_id": P["kur"]["id"], "quantity": 1, "variant_sku": "KSH-KURT-005-L"}], seller=pr)
    pay("kavita", b3["id"], f"DEMOUPI{b3['order_number']}")
    fulfil("v1", b3["id"], ["accepted", "packed"])                                            # V1: packed
    b4 = order("rohit", ADDR["Rohit"], [{"product_id": P["kss"]["id"], "quantity": 1}], seller=pr)
    pay("rohit", b4["id"], f"DEMOUPI{b4['order_number']}")
    fulfil("v1", b4["id"], ["accepted", "packed", "dispatched", "delivered"])                # V1: delivered -> return requested
    ret = ok(c.post(f"/api/orders/{b4['id']}/returns", headers=H("rohit"),
                    json={"kind": "return", "items": [{"product_id": P["kss"]["id"], "quantity": 1}], "reason": "Colour differs from the photo (demo)"}),
             "return request")
    ret = ret["cases"][0]                                     # one return case per vendor in the order
    ok(c.post(f"/api/vendor/returns/{ret['id']}/action", headers=H("v1"), json={"action": "approve", "note": "Return approved, please ship it back"}),
       "vendor approves return")
    b5 = order("imran", ADDR["Imran"], [{"product_id": P["cot"]["id"], "quantity": 1}])
    pay("imran", b5["id"], f"DEMOUPI{b5['order_number']}")
    fulfil("v1", b5["id"], ["rejected"])                                                      # vendor rejection -> refund case for finance
    b6 = order("kavita", ADDR["Kavita"], [{"product_id": P["flr"]["id"], "quantity": 2}, {"product_id": P["ubt"]["id"], "quantity": 1}], seller=pr, cod=True)
    fulfil("v2", b6["id"], ["accepted", "packed", "dispatched", "delivered"])                # COD delivered...
    cod_total = run(lambda: db.orders.find_one({"id": b6["id"]}, {"_id": 0, "total": 1}))["total"]
    ok(c.post(f"/api/orders/{b6['id']}/cod-collected", headers=H("admin"),
              json={"amount_collected": cod_total, "evidence_type": "courier_confirmation", "evidence_reference": f"DEMO-COD-{b6['order_number']}",
                    "note": "Courier remittance confirmed (demo)"}), "cod collected")
    b7 = order("kavita", ADDR["Kavita"], [{"product_id": P["cop"]["id"], "quantity": 1}], seller=an, cod=True)
    fulfil("v2", b7["id"], ["accepted"])                                                      # COD accepted, not yet delivered
    b8 = order("neha", {**ADDR["Rohit"], "full_name": "Neha Gupta", "mobile": "9840000104"}, [{"product_id": P["ubt"]["id"], "quantity": 1}])
    pay("neha", b8["id"], f"DEMOUPI{b8['order_number']}")                                      # new HomeGenie's own small purchase
    order("imran", ADDR["Imran"], [{"product_id": P["kss"]["id"], "quantity": 1}], seller=pr)  # awaiting payment (online, unpaid)

    # ---------------- wallets: KYC, withdrawals (approver != payer)
    for key, pan_, acct in (("meera", "AAAPI1111A", "11112222333301"), ("anita", "AAAPV2222B", "11112222333302"), ("priya", "AAAPS3333C", "11112222333303")):
        ok(c.post("/api/kyc", headers=H(key), json={"pan": pan_, "aadhaar": "123412341234", "account_holder_name": g[key]["full_name"],
                                                      "bank_account": acct, "ifsc": "SBIN0000001", "bank_name": "State Bank of India"}), f"kyc {key}")
        ok(c.put(f"/api/admin/kyc/{g[key]['id']}", headers=H("admin"), json={"action": "verify"}), f"verify kyc {key}")
    wal = {k: ok(c.get("/api/wallet", headers=H(k)), f"wallet {k}") for k in ("meera", "anita", "priya")}
    if wal["anita"].get("available_balance", 0) >= 50:
        w = ok(c.post("/api/withdrawals", headers=H("anita"), json={"amount": 50}), "anita withdrawal")
        ok(c.put(f"/api/admin/withdrawals/{w['id']}", headers=H("accounts"), json={"action": "approve", "note": "Demo approval"}), "approve withdrawal")
        ok(c.put(f"/api/admin/withdrawals/{w['id']}", headers=H("super"), json={"action": "mark_paid", "note": "Demo payout",
                                                                                "payout_reference": f"DEMOUTR{w['id'][:8].upper()}"}), "pay withdrawal")
    if wal["priya"].get("available_balance", 0) >= 100:
        ok(c.post("/api/withdrawals", headers=H("priya"), json={"amount": 100}), "priya withdrawal (left requested)")
    else:
        REPORT["notes"].append(f"Priya's available balance {wal['priya'].get('available_balance')} < 100: no withdrawal request created")

    # ---------------- vendor finance: settlement policy, one PAID settlement (V2) and one REQUESTED settlement (V1)
    ok(c.put("/api/admin/finance/policy", headers=H("accounts"), json={"active": True, "require_dual_approval": True, "min_settlement": 0,
                                                                       "cod_overdue_days": 7, "notes": "Demo settlement policy"}), "settlement policy")
    s2 = ok(c.post("/api/admin/finance/settlements", headers=H("accounts"), json={"vendor_id": v2id, "amount": 500, "note": "Demo settlement"}), "v2 settlement")
    ok(c.post(f"/api/admin/finance/settlements/{s2['id']}/action", headers=H("super"), json={"action": "approve", "note": "Demo approval"}), "approve settlement")
    ok(c.post(f"/api/admin/finance/settlements/{s2['id']}/action", headers=H("accounts"), json={"action": "mark_paid", "reference": f"DEMONEFT{s2['number']}"}),
       "pay settlement")
    ok(c.post("/api/admin/finance/settlements", headers=H("accounts"), json={"vendor_id": v1id, "amount": 1000, "note": "Demo settlement awaiting approval"}),
       "v1 settlement")

    # ---------------- support ticket (vendor 1) with an admin reply
    t = ok(c.post("/api/vendor/support/tickets", headers=H("v1"), json={"category": "settlement", "subject": "When will my first settlement be paid?",
                                                                         "body": "Hello team, please confirm the settlement schedule for this month."}), "ticket")
    ok(c.post(f"/api/admin/support/tickets/{t['id']}/reply", headers=H("support"), json={"body": "Settlements are processed monthly after approval (demo reply)."}),
       "ticket reply")

    # ---------------- tag everything as this demo batch
    async def tag():
        n = {}
        for coll in await db.list_collection_names():
            if coll.startswith("system."):
                continue
            r = await db[coll].update_many({}, {"$set": {"is_demo": True, "demo_batch_id": BATCH}})
            n[coll] = r.modified_count
        await db.demo_batches.update_one({"id": BATCH}, {"$set": {"id": BATCH, "created_at": now_iso(), "collections": n, "is_demo": True,
                                                                  "demo_batch_id": BATCH}}, upsert=True)
        return n
    tagged = run(tag)
    REPORT["tagged_collections"] = tagged
    REPORT["vendors"] = {"v1": v1id, "v2": v2id, "v3": v3id}
    REPORT["genies"] = {k: v["distributor_id"] for k, v in g.items()}


def cleanup(apply_):
    async def go():
        out = {}
        for coll in await db.list_collection_names():
            if coll.startswith("system."):
                continue
            q = {"demo_batch_id": BATCH, "is_demo": True}
            out[coll] = await db[coll].count_documents(q)
            if apply_ and out[coll]:
                await db[coll].delete_many(q)
        return out
    res = run(go)
    print(json.dumps({"batch": BATCH, "apply": apply_, "documents": {k: v for k, v in res.items() if v}}, indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    with TestClient(server.app) as client:
        c = client
        if cmd == "seed":
            seed()
            out = os.environ["DEMO_REPORT"]                       # outside the repository: it contains the demo passwords
            with open(out, "w") as f:
                json.dump(REPORT, f, indent=1)
            os.chmod(out, 0o600)
            print(f"demo batch {BATCH} seeded; report: {out}")
        elif cmd == "cleanup":
            cleanup("--apply" in sys.argv)
        else:
            raise SystemExit(__doc__)
