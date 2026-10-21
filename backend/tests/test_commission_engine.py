"""End-to-end check of the HOME GENIES commission engine (preview DB, no external providers).

Run:  cd /app/backend && python3 tests/test_commission_engine.py

Verifies: 30/10/5 on the pre-GST base, pending -> available release after the return
window, idempotency of a repeated payment event, and refund clawback. Cleans up after itself.
"""
import asyncio, os, uuid, sys
from motor.motor_asyncio import AsyncIOMotorClient  # noqa: F401
from dotenv import load_dotenv

load_dotenv('/app/backend/.env')
sys.path.insert(0, '/app/backend')


async def main():
    from core import db, new_id, now_iso, hash_password, get_or_create_wallet
    from commission import distribute_sale_commissions, release_due_points
    assert os.environ['DB_NAME'] == 'homegenies', 'refusing to run against another database'

    tag = uuid.uuid4().hex[:6]

    async def mk(did, sponsor_user_id=None):
        uid = new_id()
        await db.users.insert_one({
            "id": uid, "distributor_id": did, "full_name": f"T {did}",
            "email": f"{did.lower()}@t{tag}.com", "mobile": f"9{uuid.uuid4().int % 10**9:09d}",
            "password_hash": hash_password("x"), "role": "distributor", "status": "green",
            "sponsor_user_id": sponsor_user_id, "created_at": now_iso(), "updated_at": now_iso()})
        await get_or_create_wallet(uid)
        return uid

    team = await mk(f"TEAM{tag}")
    ref = await mk(f"REFR{tag}", team)
    seller = await mk(f"SELL{tag}", ref)
    buyer = await mk(f"BUYR{tag}")

    order = {"id": new_id(), "order_number": f"T{tag}", "user_id": buyer, "subtotal": 1000.0,
             "gst_amount": 50.0, "total": 1050.0, "seller_user_id": seller,
             "payment_status": "paid", "status": "processing", "items": [],
             "created_at": now_iso(), "updated_at": now_iso()}
    await db.orders.insert_one(dict(order))
    buyer_doc = await db.users.find_one({"id": buyer})

    assert (await distribute_sale_commissions(order, buyer_doc))["credited"] == 3
    assert (await distribute_sale_commissions(order, buyer_doc))["credited"] == 0, "not idempotent"

    async def w(uid):
        return await db.wallets.find_one({"user_id": uid}, {"_id": 0})

    s, r, t = await w(seller), await w(ref), await w(team)
    assert (s['pending_balance'], r['pending_balance'], t['pending_balance']) == (300, 100, 50), "wrong rates"
    assert s['available_balance'] == 0, "points must not be available before the return window"

    await db.commissions.update_many({"order_id": order["id"]},
                                     {"$set": {"created_at": "2020-01-01T00:00:00+00:00"}})
    assert (await release_due_points())["released"] == 3
    s = await w(seller)
    assert (s['available_balance'], s['pending_balance']) == (300, 0), "release failed"

    from shop_routes import reverse_order_financials
    assert (await reverse_order_financials(order["id"], reference=f"t{tag}", reason="test"))["reversed"] == 3
    s, r = await w(seller), await w(ref)
    assert s['available_balance'] == 0 and r['available_balance'] == 0, "clawback failed"

    print("PASS: 30/10/5 pre-GST base, pending->available release, idempotency, refund clawback")

    ids = [team, ref, seller, buyer]
    await db.users.delete_many({"id": {"$in": ids}})
    await db.wallets.delete_many({"user_id": {"$in": ids}})
    await db.wallet_transactions.delete_many({"user_id": {"$in": ids}})
    await db.notifications.delete_many({"user_id": {"$in": ids}})
    await db.commissions.delete_many({"order_id": order["id"]})
    await db.orders.delete_many({"id": order["id"]})
    await db.order_refunds.delete_many({"order_id": order["id"]})
    print("fixtures cleaned up")


asyncio.run(main())
