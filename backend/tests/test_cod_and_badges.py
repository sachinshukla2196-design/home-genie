"""COD + badge checks on the HOME GENIES preview DB (no external providers).

Run: cd /app/backend && python3 tests/test_cod_and_badges.py

Verifies: a COD order credits NO commission when placed; commission is credited only when
cash collection is confirmed; the HomeGenie herself and an admin may both confirm; a second
confirmation is a no-op; and the monthly badge reflects the confirmed sale value.
"""
import asyncio, os, sys, uuid
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')


async def main():
    from core import db, new_id, now_iso, hash_password, get_or_create_wallet, get_settings
    from shop_routes import cod_collected
    from badges import monthly_badge
    assert os.environ['DB_NAME'] == 'homegenies', 'refusing to run against another database'

    tag = uuid.uuid4().hex[:6]

    async def mk(did, role="distributor", sponsor=None):
        uid = new_id()
        await db.users.insert_one({
            "id": uid, "distributor_id": did, "full_name": f"T {did}",
            "email": f"{did.lower()}@t{tag}.com", "mobile": f"9{uuid.uuid4().int % 10**9:09d}",
            "password_hash": hash_password("x"), "role": role, "status": "green",
            "sponsor_user_id": sponsor, "created_at": now_iso(), "updated_at": now_iso()})
        await get_or_create_wallet(uid)
        return await db.users.find_one({"id": uid}, {"_id": 0})

    team = await mk(f"TEM{tag}")
    referrer = await mk(f"REF{tag}", sponsor=team["id"])
    seller = await mk(f"SEL{tag}", sponsor=referrer["id"])
    buyer = await mk(f"BUY{tag}")
    admin = await mk(f"ADM{tag}", role="admin")

    s = await get_settings()
    fee = float(s.get("cod_fee", 0))

    async def place(n):
        oid = new_id()
        await db.orders.insert_one({
            "id": oid, "order_number": f"C{tag}{n}", "user_id": buyer["id"],
            "items": [], "subtotal": 10000.0, "gst_percent": 5.0, "gst_amount": 500.0,
            "cod_fee": fee, "total": 10500.0 + fee, "payment_method": "cod",
            "seller_user_id": seller["id"], "seller_distributor_id": seller["distributor_id"],
            "status": "confirmed", "payment_status": "cod_pending",
            "created_at": now_iso(), "updated_at": now_iso()})
        return oid

    o1, o2 = await place(1), await place(2)

    # nothing is credited while the cash is uncollected
    w = await db.wallets.find_one({"user_id": seller["id"]}, {"_id": 0})
    assert w["pending_balance"] == 0 and w["available_balance"] == 0, "COD must not pay on placement"
    b = await monthly_badge(seller["id"])
    assert b["sales_value"] == 0, "unpaid COD must not count toward a badge"
    print("PASS: COD order pays nothing and counts nothing until collected")

    # the HomeGenie confirms her own delivery
    r1 = await cod_collected(o1, request=None, user=seller)
    assert r1["commissions"]["credited"] == 3, r1
    assert (await cod_collected(o1, request=None, user=seller)).get("already") is True, "not idempotent"

    # an admin confirms the second one
    r2 = await cod_collected(o2, request=None, user=admin)
    assert r2["commissions"]["credited"] == 3, r2

    w = await db.wallets.find_one({"user_id": seller["id"]}, {"_id": 0})
    assert w["pending_balance"] == 6000, f"expected 2 x 30% of 10000, got {w['pending_balance']}"
    wr = await db.wallets.find_one({"user_id": referrer["id"]}, {"_id": 0})
    assert wr["pending_balance"] == 2000, f"expected 2 x 10%, got {wr['pending_balance']}"
    wt = await db.wallets.find_one({"user_id": team["id"]}, {"_id": 0})
    assert wt["pending_balance"] == 1000, f"expected 2 x 5%, got {wt['pending_balance']}"
    print("PASS: commission credited only on collection, by both HomeGenie and admin, idempotently")

    o1d = await db.orders.find_one({"id": o1}, {"_id": 0})
    assert o1d["cod_collected_role"] == "homegenie" and o1d["payment_status"] == "paid"
    o2d = await db.orders.find_one({"id": o2}, {"_id": 0})
    assert o2d["cod_collected_role"] == "admin"
    print("PASS: who confirmed the cash is recorded on each order")

    b = await monthly_badge(seller["id"])
    assert b["sales_value"] == 20000 and b["badge"] == "Bronze" and b["next_badge"] == "Silver", b
    assert b["remaining"] == 5000, b
    print(f"PASS: badge = {b['badge']} on {b['sales_value']} monthly sales, {b['remaining']} to {b['next_badge']}")

    ids = [seller["id"], referrer["id"], team["id"], buyer["id"], admin["id"]]
    await db.users.delete_many({"id": {"$in": ids}})
    await db.wallets.delete_many({"user_id": {"$in": ids}})
    await db.wallet_transactions.delete_many({"user_id": {"$in": ids}})
    await db.notifications.delete_many({"user_id": {"$in": ids}})
    await db.commissions.delete_many({"order_id": {"$in": [o1, o2]}})
    await db.orders.delete_many({"id": {"$in": [o1, o2]}})
    print("fixtures cleaned up")


asyncio.run(main())
