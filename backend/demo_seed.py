"""Idempotent demo data: a GREEN sponsor with a small referral network,
orders, wallet ledger, commissions, KYC, and a pending withdrawal — so the
dashboards, reports and admin panel are populated for testing."""
from datetime import datetime, timezone, timedelta
from core import (db, now_iso, new_id, hash_password, next_distributor_id, next_sequence,
                  get_or_create_wallet, add_wallet_transaction, create_notification, logger)

DEMO_SPONSOR_EMAIL = "demo.distributor@anjaliherballife.in"
DEMO_PASSWORD = "Demo@1234"


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


async def _make_user(name, email, status, sponsor=None, created=None):
    did = await next_distributor_id()
    uid = new_id()
    doc = {
        "id": uid, "distributor_id": did, "full_name": name, "email": email,
        "mobile": "90000" + did[-5:], "password_hash": hash_password(DEMO_PASSWORD),
        "role": "distributor", "status": status, "mobile_verified": True, "email_verified": True,
        "sponsor_id": sponsor["distributor_id"] if sponsor else None,
        "sponsor_user_id": sponsor["id"] if sponsor else None,
        "address": "12 Wellness Road", "state": "Maharashtra", "city": "Pune", "pincode": "411001",
        "kyc_status": "not_started", "activation_date": None, "activation_order_id": None, "activation_amount": None,
        "created_at": created or now_iso(), "updated_at": created or now_iso(),
    }
    await db.users.insert_one(dict(doc))
    await get_or_create_wallet(uid)
    return doc


async def _activation_order(user, created):
    onum = await next_sequence("order", "ORD", 6)
    inv = await next_sequence("invoice", "INV", 6)
    oid = new_id()
    order = {
        "id": oid, "order_number": onum, "user_id": user["id"], "distributor_id": user["distributor_id"],
        "items": [{"product_id": "demo", "sku": "ANJ-STARTER", "name": "Distributor Starter Kit",
                   "name_hi": "डिस्ट्रीब्यूटर स्टार्टर किट", "image": None, "price": 1500.0, "quantity": 1, "total": 1500.0}],
        "subtotal": 1500.0, "gst_percent": 5.0, "gst_amount": 75.0, "total": 1575.0, "currency": "INR",
        "address": {"full_name": user["full_name"], "mobile": user["mobile"], "line1": "12 Wellness Road",
                    "city": "Pune", "state": "Maharashtra", "pincode": "411001"},
        "is_activation_order": True, "status": "delivered", "payment_status": "paid",
        "invoice_number": inv, "paid_at": created, "created_at": created, "updated_at": created,
    }
    await db.orders.insert_one(dict(order))
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "status": "green", "activation_date": created, "activation_order_id": oid, "activation_amount": 1575.0}})
    await db.activation_records.insert_one({
        "id": new_id(), "user_id": user["id"], "distributor_id": user["distributor_id"],
        "order_id": oid, "amount": 1575.0, "status": "activated", "activation_date": created, "created_at": created})
    return oid


async def _commission(sponsor, referred, created):
    comm = {
        "id": new_id(), "sponsor_id": sponsor["id"], "sponsor_distributor_id": sponsor["distributor_id"],
        "referred_user_id": referred["id"], "referred_distributor_id": referred["distributor_id"],
        "type": "REFERRAL_COMMISSION", "amount": 100.0, "reference_order_id": "demo",
        "status": "CREDITED", "description": f"Referral commission for activation of {referred['distributor_id']}",
        "created_at": created}
    await db.commissions.insert_one(dict(comm))
    await add_wallet_transaction(sponsor["id"], "REFERRAL_COMMISSION", 100.0, "CREDITED",
                                 reference="demo", description=f"Referral commission: {referred['distributor_id']} activated")


async def seed_demo():
    if await db.users.find_one({"email": DEMO_SPONSOR_EMAIL}):
        return
    logger.info("Seeding demo data...")

    sponsor = await _make_user("Anjali Demo Distributor", DEMO_SPONSOR_EMAIL, "red", created=days_ago(20))
    await _activation_order(sponsor, days_ago(20))
    sponsor = await db.users.find_one({"id": sponsor["id"]}, {"_id": 0})

    # KYC verified for sponsor
    await db.kyc_records.insert_one({
        "id": new_id(), "user_id": sponsor["id"], "distributor_id": sponsor["distributor_id"],
        "pan": "ABCDE1234F", "aadhaar": "123412341234", "aadhaar_verified": True,
        "account_holder_name": "Anjali Demo Distributor", "bank_account": "1234567890",
        "ifsc": "HDFC0000123", "bank_name": "HDFC Bank", "status": "verified", "rejection_reason": None,
        "submitted_at": days_ago(18), "updated_at": days_ago(17), "created_at": days_ago(18)})
    await db.users.update_one({"id": sponsor["id"]}, {"$set": {"kyc_status": "verified"}})

    # referral network: 2 GREEN (commission), 1 RED (no commission)
    refs = [
        ("Ravi Kumar", "ravi.demo@anjaliherballife.in", "green", days_ago(12)),
        ("Priya Sharma", "priya.demo@anjaliherballife.in", "green", days_ago(1)),
        ("Amit Patel", "amit.demo@anjaliherballife.in", "red", days_ago(3)),
    ]
    for name, email, status, created in refs:
        ru = await _make_user(name, email, "red", sponsor=sponsor, created=created)
        await db.referral_relationships.insert_one({
            "id": new_id(), "sponsor_id": sponsor["id"], "sponsor_distributor_id": sponsor["distributor_id"],
            "referred_user_id": ru["id"], "referred_distributor_id": ru["distributor_id"],
            "commission_paid": status == "green", "created_at": created})
        if status == "green":
            await _activation_order(ru, created)
            await _commission(sponsor, ru, created)

    # bonus adjustment so withdrawal demo is possible, plus a pending withdrawal
    await add_wallet_transaction(sponsor["id"], "ADJUSTMENT", 800.0, "CREDITED",
                                 description="Festive bonus (demo)")
    # available now 200 (2 comm) + 800 = 1000
    await add_wallet_transaction(sponsor["id"], "WITHDRAWAL", 500.0, "DEBITED",
                                 description="Withdrawal request (held)", direction="debit")
    await add_wallet_transaction(sponsor["id"], "WITHDRAWAL", 500.0, "PENDING",
                                 description="Withdrawal pending admin review")
    await db.withdrawal_requests.insert_one({
        "id": new_id(), "request_number": "WDDEMO001", "user_id": sponsor["id"],
        "distributor_id": sponsor["distributor_id"], "amount": 500.0, "status": "pending",
        "admin_note": None, "created_at": days_ago(1), "updated_at": days_ago(1)})

    # a product (non-activation) order for the sponsor
    onum = await next_sequence("order", "ORD", 6)
    inv = await next_sequence("invoice", "INV", 6)
    await db.orders.insert_one({
        "id": new_id(), "order_number": onum, "user_id": sponsor["id"], "distributor_id": sponsor["distributor_id"],
        "items": [{"product_id": "demo2", "sku": "ANJ-CHY-01", "name": "Chyawanprash Immunity Booster",
                   "name_hi": "च्यवनप्राश इम्युनिटी बूस्टर", "image": None, "price": 449.0, "quantity": 2, "total": 898.0}],
        "subtotal": 898.0, "gst_percent": 5.0, "gst_amount": 44.9, "total": 942.9, "currency": "INR",
        "address": {"full_name": sponsor["full_name"], "mobile": sponsor["mobile"], "line1": "12 Wellness Road",
                    "city": "Pune", "state": "Maharashtra", "pincode": "411001"},
        "is_activation_order": False, "status": "shipped", "payment_status": "paid",
        "invoice_number": inv, "paid_at": days_ago(5), "created_at": days_ago(5), "updated_at": days_ago(5)})

    await create_notification(sponsor["id"], "welcome", "Welcome to your demo account",
                              "This account is pre-loaded with sample income, orders and a team so you can explore.",
                              "आपके डेमो खाते में स्वागत है",
                              "यह खाता नमूना आय, ऑर्डर और टीम के साथ पहले से लोड है ताकि आप एक्सप्लोर कर सकें।")
    logger.info("Demo data seeded.")
