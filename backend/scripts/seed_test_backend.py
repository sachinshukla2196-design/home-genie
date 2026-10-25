"""Seed the ISOLATED test backend with the accounts and products the live-backend suites expect.

Refuses to run unless DB_NAME is a dedicated test database (it must end in `_test` and must not be the production name).
Idempotent: it replaces only the records it owns (test accounts, the test activation product) and clears login-attempt and rate-limit
records so earlier failed logins cannot lock out a fresh run. Nothing else is touched.

Environment (names only; values come from the operator, never from this file):
    MONGO_URL, DB_NAME (dedicated *_test database)
    TEST_ADMIN_EMAIL, TEST_ADMIN_USERNAME, TEST_ADMIN_PASSWORD      test-only admin
    TEST_DEMO_PASSWORD                                              demo distributor password (default Demo@1234)
    TEST_SPONSOR_ID                                                 referral ID of a green test sponsor (default MST000001)

Usage:  python scripts/seed_test_backend.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core import db, hash_password, new_id, now_iso, add_wallet_transaction  # noqa: E402

DEMO_EMAIL = "demo.distributor@homegenies.example.com"


def _require_test_database() -> str:
    name = os.environ.get("DB_NAME", "")
    if not name.endswith("_test") or name == "homegenies":
        raise SystemExit("refusing to seed: DB_NAME must be a dedicated *_test database, never the production name")
    return name


def _person(email, mobile, role, did, password, status="green", **extra):
    return {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": email,
            "password_hash": hash_password(password), "role": role, "status": status, "account_status": "active",
            "created_at": now_iso(), "updated_at": now_iso(), **extra}


async def main() -> None:
    name = _require_test_database()
    admin_email = os.environ["TEST_ADMIN_EMAIL"]
    admin_password = os.environ["TEST_ADMIN_PASSWORD"]
    demo_password = os.environ.get("TEST_DEMO_PASSWORD", "Demo@1234")
    sponsor_id = os.environ.get("TEST_SPONSOR_ID", "MST000001")

    await db.users.delete_many({"email": {"$in": [admin_email, DEMO_EMAIL]}})
    await db.users.delete_many({"distributor_id": {"$in": [sponsor_id, "DEMO0001"]}})
    await db.users.insert_many([
        {**_person(admin_email, "9999999999", "super_admin", "TESTADM", admin_password),
         "username": os.environ.get("TEST_ADMIN_USERNAME", admin_email)},
        _person(DEMO_EMAIL, "9000000018", "distributor", "DEMO0001", demo_password),
        _person(None, "9199000997", "distributor", sponsor_id, demo_password),
    ])
    # test-only wallet history, written through the ledger path (never a direct balance write)
    demo = await db.users.find_one({"email": DEMO_EMAIL}, {"id": 1})
    for kind, amount, txn_type, status, direction in (
            ("earned", 1000, "MANUAL_ADMIN_CREDIT", "CREDITED", "credit"),
            ("withdrawn", 500, "WITHDRAWAL", "DEBITED", "debit"),
            ("pending", 500, "COMMISSION", "PENDING", "credit")):
        await add_wallet_transaction(demo["id"], txn_type, amount, status, direction=direction,
                                     reference=f"test-seed:demo-wallet:{kind}:{demo['id']}", description="Test-only seed entry")
    await db.products.delete_many({"sku": "ANJ-STARTER"})
    await db.products.insert_one({"id": new_id(), "sku": "ANJ-STARTER", "name": "Test Activation Kit", "name_hi": "", "description": "Test-only kit",
                                  "description_hi": "", "images": [], "mrp": 1000, "selling_price": 800, "gst_percent": 5, "hsn_code": "",
                                  "stock": 100, "low_stock_threshold": 5, "category": "Household Essentials", "is_active": True,
                                  "approval_status": "approved", "is_activation_product": True, "archived": False,
                                  "created_at": now_iso(), "updated_at": now_iso()})
    cleared_attempts = (await db.login_attempts.delete_many({})).deleted_count
    cleared_limits = (await db.rate_limits.delete_many({})).deleted_count
    print(f"seeded test database {name}: admin, demo distributor, sponsor, activation product; "
          f"cleared {cleared_attempts} login attempts and {cleared_limits} rate-limit records")


if __name__ == "__main__":
    asyncio.run(main())
