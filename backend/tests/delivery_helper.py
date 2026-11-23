"""Shared test helper (Batch 12, audit C-5): record a delivery the way the vendor dispatch flow records it.

Since Batch 12 the evidence of delivery is each VENDOR FULFILMENT (status `delivered` with a `delivered` event); the order's own
status / `delivered_at` alone no longer starts any payout clock for vendor goods. Tests that need "delivered N days ago" use this
instead of writing `orders.delivered_at` directly.
"""


async def deliver(db, order_id: str, at: str) -> None:
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    fl = []
    for f in o.get("fulfilments") or []:
        if f.get("status") in ("rejected", "cancelled", "returned_to_origin"):
            fl.append(f)
            continue
        ev = [e for e in f.get("events", []) if e.get("status") != "delivered"] + [{"status": "delivered", "at": at, "by": "test"}]
        fl.append({**f, "status": "delivered", "delivered_at": at, "events": ev})
    await db.orders.update_one({"id": order_id}, {"$set": {"status": "delivered", "delivered_at": at, "fulfilments": fl}})
