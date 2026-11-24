"""Programme 01 (B-006): server-side protection for order creation (stock reservation abuse).

Every order reserves stock the moment it is placed. Without limits, a script (or a stuck double-click) can place many orders
and hold stock that real customers cannot buy: unpaid online orders until they expire, cash-on-delivery orders until the seller
acts. Three independent checks run BEFORE anything is reserved; none relies on the browser:

1. Rate limits (core.rate_limit, MongoDB fixed windows shared by all instances):
   - per ACCOUNT  `order_create_user`  - the primary control;
   - per IP       `order_create_ip`    - deliberately generous (families, offices and mobile networks share addresses), so it
                                          only stops floods, never a household.
2. Open-order cap per account: orders still awaiting payment (online `pending`, UPI `claimed`) or still waiting for every seller
   to act (cash on delivery, any seller group still `new`) count as "open". At the cap the next order is refused with a clear
   message until one is paid, accepted or cancelled. It cancels nothing and changes no existing order.
3. Duplicate submission: the same account submitting the same cart (items, options, quantities, address, payment method) again
   within SUBMIT_WINDOW_SECONDS gets the SAME order back instead of a second reservation. One atomic claim per fingerprint
   (`order_submissions._id`), so two simultaneous clicks cannot both create an order.

Limits are environment settings with conservative defaults, listed in deploy/ENVIRONMENT.md. They are abuse controls, not
business policy: the owner may tune them (OWNER_DECISION_REGISTER, Programme 01).
"""
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from core import db, rate_limit, client_ip, RATE_LIMITS

# Production defaults (deploy/ENVIRONMENT.md). The environment may tune them; the test suite's conftest raises them for the
# older suites that place many orders for one test account, and test_programme01_order_protection restores these values.
DEFAULTS = {"ORDER_OPEN_UNPAID_MAX": 5, "ORDER_SUBMIT_WINDOW_SECONDS": 60, "ORDER_CREATE_PER_USER_10MIN": 10, "ORDER_CREATE_PER_IP_10MIN": 60}


def _env(name):
    v = os.environ.get(name)
    return int(v) if v not in (None, "") else DEFAULTS[name]


OPEN_UNPAID_MAX = _env("ORDER_OPEN_UNPAID_MAX")
SUBMIT_WINDOW_SECONDS = _env("ORDER_SUBMIT_WINDOW_SECONDS")
RATE_LIMITS["order_create_user"] = (_env("ORDER_CREATE_PER_USER_10MIN"), 600)
RATE_LIMITS["order_create_ip"] = (_env("ORDER_CREATE_PER_IP_10MIN"), 600)

OPEN_QUERY = lambda uid: {"user_id": uid, "status": {"$ne": "cancelled"}, "$or": [                # noqa: E731
    {"payment_method": {"$ne": "cod"}, "payment_status": {"$in": ["pending", "claimed"]}},
    {"payment_method": "cod", "payment_status": "cod_pending", "fulfilments.status": "new"}]}


def fingerprint(user_id: str, body) -> str:
    items = sorted((it.product_id, (it.variant_sku or "").strip().upper(), it.quantity) for it in body.items)
    addr = body.address_id or (body.address.model_dump() if body.address else None)
    raw = json.dumps({"u": user_id, "i": items, "a": addr, "m": (body.payment_method or "online").lower()}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


async def check_limits(user: dict, request) -> None:
    await rate_limit("order_create_user", user["id"])
    await rate_limit("order_create_ip", client_ip(request) if request is not None else "unknown")
    n = await db.orders.count_documents(OPEN_QUERY(user["id"]))
    if n >= OPEN_UNPAID_MAX:
        raise HTTPException(status_code=429, detail=f"You already have {n} orders waiting for payment or seller confirmation. "
                                                    "Please pay for or cancel one of them before placing another.")


async def claim_submission(fp: str):
    """Returns (claimed, existing_order). claimed=True: this request may create the order (call `bind_submission` after).
    claimed=False with an order: return that order. claimed=False without one: the same submission is being placed now."""
    now = datetime.now(timezone.utc)
    doc = {"_id": fp, "order_id": None, "created_at": now.isoformat(), "expires_at": now + timedelta(seconds=SUBMIT_WINDOW_SECONDS * 5)}
    try:
        await db.order_submissions.insert_one(doc)
        return True, None
    except Exception as e:                       # duplicate key: a submission with this fingerprint exists
        if "duplicate key" not in str(e).lower() and type(e).__name__ != "DuplicateKeyError":
            raise
    cur = await db.order_submissions.find_one({"_id": fp})
    created = datetime.fromisoformat(cur["created_at"]) if cur else now
    if cur and cur.get("order_id"):
        o = await db.orders.find_one({"id": cur["order_id"]}, {"_id": 0})
        still_open = o and o.get("status") != "cancelled" and o.get("payment_status") in ("pending", "cod_pending", "claimed")
        if still_open and (now - created).total_seconds() < SUBMIT_WINDOW_SECONDS:
            return False, o
    elif cur and (now - created).total_seconds() < SUBMIT_WINDOW_SECONDS:
        raise HTTPException(status_code=409, detail="This order is already being placed. Please wait a moment and check your orders.")
    # stale, paid or cancelled: take the fingerprint over atomically (only one concurrent request wins)
    won = await db.order_submissions.update_one({"_id": fp, "created_at": cur["created_at"] if cur else None},
                                                {"$set": {"order_id": None, "created_at": now.isoformat(),
                                                          "expires_at": now + timedelta(seconds=SUBMIT_WINDOW_SECONDS * 5)}})
    if won.modified_count == 1:
        return True, None
    raise HTTPException(status_code=409, detail="This order is already being placed. Please wait a moment and check your orders.")


async def bind_submission(fp: str, order_id: str) -> None:
    await db.order_submissions.update_one({"_id": fp, "order_id": None}, {"$set": {"order_id": order_id}})


async def release_submission(fp: str) -> None:
    """The order was not created (validation failed, out of stock): the same cart may be submitted again at once."""
    await db.order_submissions.delete_one({"_id": fp, "order_id": None})
