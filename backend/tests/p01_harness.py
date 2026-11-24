"""Shared helpers for the Programme 01 integration suites (money integrity). Not a test module.

Each suite sets its own THROWAWAY DB_NAME before importing `server`, then calls `seed_world(S)` inside its fixture.
Real orders go through POST /api/orders; payments through the real completion paths; vendor steps through the vendor API.
"""
from datetime import datetime, timedelta, timezone

from core import db, hash_password, create_token, now_iso, new_id

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
OLD = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
ADMIN_ROLES = {"adm": "admin", "fin": "accounts_admin", "fin2": "accounts_admin", "sup": "super_admin", "support": "support_admin"}


def hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


async def seed_world(S: dict, prefix: str):
    async def user(key, role, did):
        u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": "92" + new_id()[:8].replace("-", "2"), "email": None,
             "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
             "created_at": now_iso(), "updated_at": now_iso()}
        await db.users.insert_one(dict(u))
        S[key] = u
    await user("cust", "distributor", prefix + "CUST")
    await user("cust2", "customer", prefix + "CUS2")
    await user("seller", "distributor", prefix + "SELL")
    for k, r in ADMIN_ROLES.items():
        await user(k, r, prefix + k.upper())
    for k in ("va", "vb"):
        await user("u" + k, "vendor", prefix + k.upper())
        S[k] = {"id": new_id(), "user_id": S["u" + k]["id"], "vendor_code": prefix + k.upper(), "business_name": "Vendor " + k,
                "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
        await db.vendors.insert_one(dict(S[k]))


class World:
    """Helpers bound to one TestClient + seeded dict."""

    def __init__(self, c, S, seller_ref):
        self.c, self.S, self.seller_ref = c, S, seller_ref

    def run(self, fn):
        return self.c.portal.call(fn)

    def product(self, vendor="va", price=1000, stock=50):
        p = {"id": new_id(), "sku": "P1-" + new_id()[:6], "name": "Saree " + vendor, "images": [], "mrp": price + 200, "selling_price": price,
             "gst_percent": 5, "stock": stock, "category": "Sarees", "options": [], "vendor_id": self.S[vendor]["id"],
             "vendor_name": self.S[vendor]["business_name"], "is_active": True, "approval_status": "approved", "created_at": now_iso()}
        self.run(lambda: db.products.insert_one(dict(p)))
        return p["id"]

    def order(self, lines, method="online", who="cust", seller=True):
        body = {"items": [{"product_id": p, "quantity": q} for p, q in lines], "address": ADDR, "payment_method": method}
        if seller:
            body["seller_ref"] = self.seller_ref
        r = self.c.post("/api/orders", json=body, headers=hdr(self.S[who]["id"]))
        assert r.status_code == 200, r.text
        return r.json()

    def tx(self, o, sid=None):
        sid = sid or "cs_" + o["id"][:12]
        self.run(lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                             "amount": o["total"], "status": "initiated", "payment_status": "pending",
                                                             "created_at": now_iso()}))
        return sid

    def paid_order(self, lines):
        import shop_routes
        o = self.order(lines)
        sid = self.tx(o)
        self.run(lambda: shop_routes._process_paid_order(sid))
        return self.get(o["id"])

    def get(self, oid):
        return self.run(lambda: db.orders.find_one({"id": oid}, {"_id": 0}))

    def cases(self, oid):
        return self.run(lambda: db.refund_cases.find({"order_id": oid}, {"_id": 0}).to_list(20))

    def case(self, cid):
        return self.run(lambda: db.refund_cases.find_one({"id": cid}, {"_id": 0}))

    def comms(self, oid):
        return self.run(lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10))

    def plan(self, oid):
        return self.run(lambda: db.commission_plans.find_one({"_id": oid}))

    def ledger(self, oid, typ=None, vendor=None):
        q = {"order_id": oid}
        if typ:
            q["type"] = typ
        if vendor:
            q["vendor_id"] = self.S[vendor]["id"]
        return self.run(lambda: db.vendor_ledger.find(q, {"_id": 0}).to_list(50))

    def net(self, oid, vendor):
        return sum(r["amount_paise"] for r in self.ledger(oid, vendor=vendor))

    def events(self, oid, status=None):
        q = {"order_id": oid}
        if status:
            q["status"] = status
        return self.run(lambda: db.order_refunds.find(q, {"_id": 0}).to_list(20))

    def audits(self, action, entity_id=None):
        q = {"action": action}
        if entity_id:
            q["entity_id"] = entity_id
        return self.run(lambda: db.audit_logs.find(q, {"_id": 0}).to_list(50))

    def stock(self, pid):
        return self.run(lambda: db.products.find_one({"id": pid}, {"_id": 0, "stock": 1}))["stock"]

    def wallet_ok(self):
        from wallet_reconcile import expected_aggregates
        rows = self.run(lambda: db.wallet_transactions.find({"user_id": self.S["seller"]["id"]}, {"_id": 0}).to_list(5000))
        w = self.run(lambda: db.wallets.find_one({"user_id": self.S["seller"]["id"]}, {"_id": 0})) or {}
        exp = expected_aggregates(rows)
        return all(exp[f] == w.get(f + "_paise", 0) for f in exp)

    def act(self, who, cid, action, **kw):
        return self.c.post(f"/api/admin/refund-cases/{cid}/action", headers=hdr(self.S[who]["id"]), json={"action": action, **kw})

    def confirm(self, who, cid, ref):
        return self.act(who, cid, "confirm", reference=ref, confirmation_type="manual_reconciliation", note="Verified against the bank statement")

    def step(self, vendor, oid, status, note="Courier could not reach the customer"):
        body = {"status": status, "note": note}
        if status == "dispatched":
            body.update({"carrier": "Delhivery", "tracking_number": "TRK" + oid[:6]})
        return self.c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=hdr(self.S["u" + vendor]["id"]), json=body)

    def deliver(self, vendor, oid):
        for st in ("accepted", "packed", "dispatched"):
            assert self.step(vendor, oid, st).status_code == 200, st
        assert self.step(vendor, oid, "delivered", note="Recipient: Cust, OTP 4411").status_code == 200

    def rto(self, vendor, oid):
        for st in ("accepted", "packed", "dispatched", "delivery_failed"):
            assert self.step(vendor, oid, st).status_code == 200, st
        return self.step(vendor, oid, "returned_to_origin", note="Shipment returned to the warehouse")

    def age(self, oid):
        """Every delivered vendor group and the commission creation move 40 days into the past."""
        async def go():
            o = await db.orders.find_one({"id": oid}, {"_id": 0})
            fl = [{**f, "delivered_at": OLD, "events": [{**e, "at": OLD} if e.get("status") == "delivered" else e for e in f.get("events", [])]}
                  if f.get("status") == "delivered" else f for f in o.get("fulfilments", [])]
            await db.orders.update_one({"id": oid}, {"$set": {"fulfilments": fl}})
            await db.commissions.update_many({"order_id": oid}, {"$set": {"created_at": OLD}})
        self.run(go)
