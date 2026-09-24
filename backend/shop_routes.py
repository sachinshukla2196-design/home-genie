"""Products, cart -> orders, and Stripe payments with server-side verification."""
import os
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import List, Optional

from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest

from core import (db, now_iso, new_id, get_current_user, get_settings, next_sequence,
                  add_wallet_transaction, create_notification, log_audit, require_admin)

router = APIRouter(prefix="/api", tags=["shop"])

import razorpay
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")


def _razorpay_client():
    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET):
        raise HTTPException(status_code=503, detail="Online payment is not configured yet. Please use UPI or contact admin.")
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "sk_test_emergent")


# ---------------- Products ----------------
@router.get("/products")
async def list_products(category: Optional[str] = None, active: bool = True):
    q = {}
    if active:
        q["is_active"] = True
    if category:
        q["category"] = category
    items = await db.products.find(q, {"_id": 0}).sort("created_at", 1).to_list(200)
    return items


@router.get("/products/{product_id}")
async def get_product(product_id: str):
    p = await db.products.find_one({"id": product_id}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    return p


@router.get("/categories")
async def categories():
    return await db.product_categories.find({}, {"_id": 0}).to_list(100)


# ---------------- Orders ----------------
class OrderItemIn(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=50)


class AddressIn(BaseModel):
    full_name: str
    mobile: str
    line1: str
    city: str
    state: str
    pincode: str


class CreateOrder(BaseModel):
    items: List[OrderItemIn]
    address: AddressIn


@router.post("/orders")
async def create_order(body: CreateOrder, request: Request, user: dict = Depends(get_current_user)):
    if not body.items:
        raise HTTPException(status_code=400, detail="Your cart is empty.")
    settings = await get_settings()
    gst_percent = settings.get("gst_percent", 5.0)

    line_items = []
    subtotal = 0.0
    is_activation_order = False
    product_ids = [it.product_id for it in body.items]
    products = {p["id"]: p for p in await db.products.find(
        {"id": {"$in": product_ids}}, {"_id": 0}).to_list(len(product_ids) or 1)}
    for it in body.items:
        p = products.get(it.product_id)
        if not p or not p.get("is_active"):
            raise HTTPException(status_code=400, detail="A product in your cart is unavailable.")
        price = float(p["selling_price"])
        total = price * it.quantity
        subtotal += total
        if p.get("is_activation_product"):
            is_activation_order = True
        line_items.append({
            "product_id": p["id"], "sku": p["sku"], "name": p["name"], "name_hi": p.get("name_hi", ""),
            "image": (p.get("images") or [None])[0], "price": price, "quantity": it.quantity,
            "total": round(total, 2),
        })

    gst_amount = round(subtotal * gst_percent / 100.0, 2)
    grand_total = round(subtotal + gst_amount, 2)
    order_number = await next_sequence("order", "ORD", 6)
    oid = new_id()
    order = {
        "id": oid,
        "order_number": order_number,
        "user_id": user["id"],
        "distributor_id": user.get("distributor_id"),
        "items": line_items,
        "subtotal": round(subtotal, 2),
        "gst_percent": gst_percent,
        "gst_amount": gst_amount,
        "total": grand_total,
        "currency": settings.get("currency", "INR"),
        "address": body.address.model_dump(),
        "is_activation_order": is_activation_order,
        "status": "payment_pending",  # pending, payment_pending, paid, processing, packed, shipped, delivered, cancelled, refunded
        "payment_status": "pending",
        "invoice_number": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.orders.insert_one(dict(order))
    await log_audit(user, "order_created", "order", oid, new_value={"total": grand_total}, request=request)
    order.pop("_id", None)
    return order


@router.get("/orders")
async def my_orders(user: dict = Depends(get_current_user)):
    return await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.get("/orders/{order_id}")
async def get_order(order_id: str, user: dict = Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin", "accounts_admin", "support_admin"):
        raise HTTPException(status_code=403, detail="Access denied.")
    return o


# ---------------- Payments ----------------
class CheckoutBody(BaseModel):
    order_id: str
    origin_url: str


def _stripe(request: Request) -> StripeCheckout:
    host = str(request.base_url)
    webhook_url = f"{host}api/webhook/stripe"
    return StripeCheckout(api_key=STRIPE_API_KEY, webhook_url=webhook_url)


@router.post("/payments/checkout")
async def create_checkout(body: CheckoutBody, request: Request, user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": body.order_id}, {"_id": 0})
    if not order or order["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order["payment_status"] == "paid":
        raise HTTPException(status_code=400, detail="This order is already paid.")

    amount = float(order["total"])  # server-side amount, never from client
    success_url = f"{body.origin_url}/payment/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{body.origin_url}/payment/cancel"
    sc = _stripe(request)
    req = CheckoutSessionRequest(
        amount=amount, currency=(order.get("currency") or "INR").lower(),
        success_url=success_url, cancel_url=cancel_url,
        metadata={"order_id": order["id"], "user_id": user["id"]},
    )
    session = await sc.create_checkout_session(req)

    await db.payment_transactions.insert_one({
        "id": new_id(),
        "session_id": session.session_id,
        "order_id": order["id"],
        "user_id": user["id"],
        "amount": amount,
        "currency": order.get("currency", "INR"),
        "status": "initiated",
        "payment_status": "pending",
        "created_at": now_iso(), "updated_at": now_iso(),
    })
    await db.orders.update_one({"id": order["id"]},
                               {"$set": {"stripe_session_id": session.session_id, "updated_at": now_iso()}})
    return {"checkout_url": session.url, "session_id": session.session_id}


class RzpOrderBody(BaseModel):
    order_id: str


@router.post("/payments/razorpay/order")
async def razorpay_create_order(body: RzpOrderBody, user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": body.order_id}, {"_id": 0})
    if not order or order["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order["payment_status"] == "paid":
        raise HTTPException(status_code=400, detail="This order is already paid.")
    client = _razorpay_client()
    amount_paise = int(round(float(order["total"]) * 100))
    rzp_order = client.order.create({"amount": amount_paise, "currency": "INR",
                                     "receipt": order["order_number"][:40], "payment_capture": 1})
    await db.payment_transactions.insert_one({
        "id": new_id(), "session_id": rzp_order["id"], "order_id": order["id"], "user_id": user["id"],
        "amount": float(order["total"]), "currency": "INR", "provider": "razorpay",
        "status": "initiated", "payment_status": "pending", "created_at": now_iso(), "updated_at": now_iso()})
    await db.orders.update_one({"id": order["id"]}, {"$set": {"razorpay_order_id": rzp_order["id"], "updated_at": now_iso()}})
    return {"key_id": RAZORPAY_KEY_ID, "razorpay_order_id": rzp_order["id"],
            "amount": amount_paise, "currency": "INR", "order_number": order["order_number"],
            "name": user.get("full_name"), "email": user.get("email"), "contact": user.get("mobile")}


class RzpVerifyBody(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/payments/razorpay/verify")
async def razorpay_verify(body: RzpVerifyBody, request: Request, user: dict = Depends(get_current_user)):
    client = _razorpay_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": body.razorpay_order_id,
            "razorpay_payment_id": body.razorpay_payment_id,
            "razorpay_signature": body.razorpay_signature})
    except Exception:
        raise HTTPException(status_code=400, detail="Payment verification failed.")
    # Trusted-source verification: fetch the payment from Razorpay and confirm it is
    # captured/authorized for the exact amount we created the order for.
    tx = await db.payment_transactions.find_one({"session_id": body.razorpay_order_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Payment record not found.")
    try:
        pay = client.payment.fetch(body.razorpay_payment_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not verify payment with the gateway.")
    expected_paise = int(round(float(tx["amount"]) * 100))
    if pay.get("order_id") != body.razorpay_order_id:
        raise HTTPException(status_code=400, detail="Payment does not match this order.")
    if int(pay.get("amount", 0)) != expected_paise:
        raise HTTPException(status_code=400, detail="Payment amount mismatch.")
    if pay.get("status") not in ("captured", "authorized"):
        raise HTTPException(status_code=400, detail="Payment is not captured yet.")
    await db.payment_transactions.update_one({"session_id": body.razorpay_order_id},
        {"$set": {"razorpay_payment_id": body.razorpay_payment_id, "updated_at": now_iso()}})
    await _process_paid_order(body.razorpay_order_id, request)
    tx = await db.payment_transactions.find_one({"session_id": body.razorpay_order_id}, {"_id": 0})
    return {"message": "Payment successful", "order_id": tx.get("order_id") if tx else None}


@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    """Server-authoritative Razorpay webhook. Validates HMAC, is idempotent per event,
    and converges on the same _process_paid_order state machine as the client verify."""
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")
    raw = await request.body()
    sig = request.headers.get("X-Razorpay-Signature", "")
    import hmac as _hmac, hashlib as _hashlib, json as _json
    expected = _hmac.new(secret.encode(), raw, _hashlib.sha256).hexdigest()
    if not _hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        event = _json.loads(raw.decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid payload")
    event_id = request.headers.get("X-Razorpay-Event-Id") or event.get("id") or ""
    if event_id:
        seen = await db.webhook_events.find_one({"event_id": event_id})
        if seen:
            return {"status": "duplicate"}
        await db.webhook_events.insert_one({"event_id": event_id, "provider": "razorpay",
                                            "type": event.get("event"), "created_at": now_iso()})
    etype = event.get("event", "")
    if etype in ("payment.captured", "order.paid"):
        entity = (event.get("payload", {}).get("payment", {}) or {}).get("entity", {}) or {}
        rzp_order_id = entity.get("order_id")
        if not rzp_order_id:
            order_ent = (event.get("payload", {}).get("order", {}) or {}).get("entity", {}) or {}
            rzp_order_id = order_ent.get("id")
        if rzp_order_id:
            tx = await db.payment_transactions.find_one({"session_id": rzp_order_id})
            if tx:
                await _process_paid_order(rzp_order_id, request)
    return {"status": "ok"}


async def reverse_order_financials(order_id: str, actor: dict = None, request: Request = None):
    """Auditable refund/clawback: reverse product commissions + ₹100 referral reward
    tied to a refunded order. Never deletes history — marks originals REVERSED and
    writes clawback ledger entries. Idempotent via an atomic claim on the order."""
    claim = await db.orders.update_one(
        {"id": order_id, "payment_status": "paid", "financials_reversed": {"$ne": True}},
        {"$set": {"financials_reversed": True, "updated_at": now_iso()}})
    if claim.modified_count != 1:
        return {"reversed": 0}
    order = await db.orders.find_one({"id": order_id})
    n = 0
    comms = await db.commissions.find(
        {"reference_order_id": order_id, "status": "CREDITED",
         "type": {"$in": ["PURCHASE_LEVEL_COMMISSION", "REFERRAL_COMMISSION"]}}).to_list(1000)
    for c in comms:
        await db.commissions.update_one({"id": c["id"]},
            {"$set": {"status": "REVERSED", "reversed_at": now_iso()}})
        await add_wallet_transaction(
            c["sponsor_id"], "COMMISSION_CLAWBACK", float(c["amount"]), "CLAWBACK",
            reference=order_id, direction="debit",
            description=f"Clawback of {c.get('type')} on refunded order {order.get('order_number')}")
        n += 1
    # If the refunded order was the activation order, revert the account to RED.
    if order and order.get("is_activation_order"):
        buyer = await db.users.find_one({"id": order["user_id"]})
        if buyer and buyer.get("activation_order_id") == order_id:
            await db.users.update_one({"id": buyer["id"]},
                {"$set": {"status": "red", "activation_status": "inactive",
                          "activation_order_id": None, "updated_at": now_iso()}})
            await db.activation_records.update_many({"order_id": order_id},
                {"$set": {"status": "reversed", "updated_at": now_iso()}})
    await log_audit(actor, "order_financials_reversed", "order", order_id,
                    new_value={"reversed_entries": n}, request=request)
    return {"reversed": n}


async def _process_paid_order(session_id: str, request: Request = None):
    """Idempotent: mark order paid, generate invoice, run GREEN activation + referral commission."""
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx:
        return
    order = await db.orders.find_one({"id": tx["order_id"]})
    if not order:
        return
    if order.get("payment_status") == "paid":
        return  # already processed

    settings = await get_settings()
    invoice_number = await next_sequence("invoice", "INV", 6)
    await db.orders.update_one(
        {"id": order["id"], "payment_status": {"$ne": "paid"}},
        {"$set": {"payment_status": "paid", "status": "processing",
                  "invoice_number": invoice_number, "paid_at": now_iso(), "updated_at": now_iso()}},
    )
    await db.payment_transactions.update_one(
        {"session_id": session_id},
        {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}},
    )

    user = await db.users.find_one({"id": order["user_id"]})
    if not user:
        return
    await create_notification(user["id"], "payment_success", "Payment successful",
                              f"Payment received for order {order['order_number']}. Invoice {invoice_number} generated.",
                              "भुगतान सफल",
                              f"ऑर्डर {order['order_number']} का भुगतान प्राप्त हुआ। इनवॉइस {invoice_number} बन गया।")

    # ---- GREEN activation ----
    activation_amount = float(settings.get("activation_amount", 1500.0))
    qualifies = order.get("is_activation_order") and float(order["total"]) >= activation_amount
    if qualifies and user.get("status") == "red":
        await db.users.update_one(
            {"id": user["id"], "status": "red"},
            {"$set": {"status": "green", "activation_status": "active", "activation_date": now_iso(),
                      "activation_order_id": order["id"], "activation_amount": order["total"],
                      "updated_at": now_iso()}},
        )
        await db.activation_records.insert_one({
            "id": new_id(), "user_id": user["id"], "distributor_id": user.get("distributor_id"),
            "order_id": order["id"], "amount": order["total"], "status": "activated",
            "activation_date": now_iso(), "created_at": now_iso(),
        })
        await db.wallets.update_one({"user_id": user["id"]}, {"$set": {"active": True, "updated_at": now_iso()}})
        await create_notification(user["id"], "activation", "Your account is now GREEN",
                                  "Congratulations! Your distributor account is activated. Income & referrals unlocked.",
                                  "आपका खाता अब ग्रीन है",
                                  "बधाई हो! आपका डिस्ट्रीब्यूटर खाता सक्रिय हो गया है। आय और रेफ़रल अनलॉक।")
        await log_audit(None, "green_activation", "user", user["id"],
                        old_value={"status": "red"}, new_value={"status": "green"}, request=request)

        # ---- Referral commission (idempotent) ----
        rel = await db.referral_relationships.find_one({"referred_user_id": user["id"]})
        if rel and not rel.get("commission_paid"):
            sponsor = await db.users.find_one({"id": rel["sponsor_id"]})
            commission_amount = float(settings.get("referral_commission", 100.0))
            if sponsor and sponsor.get("status") == "green":
                # guard: no existing commission for this referred user
                existing = await db.commissions.find_one({"referred_user_id": user["id"],
                                                          "type": "REFERRAL_COMMISSION"})
                if not existing:
                    marked = await db.referral_relationships.update_one(
                        {"id": rel["id"], "commission_paid": {"$ne": True}},
                        {"$set": {"commission_paid": True, "commission_paid_at": now_iso()}},
                    )
                    if marked.modified_count == 1:
                        comm = {
                            "id": new_id(), "sponsor_id": sponsor["id"],
                            "sponsor_distributor_id": sponsor.get("distributor_id"),
                            "referred_user_id": user["id"],
                            "referred_distributor_id": user.get("distributor_id"),
                            "type": "REFERRAL_COMMISSION", "amount": commission_amount,
                            "reference_order_id": order["id"], "status": "CREDITED",
                            "description": f"Referral commission for activation of {user.get('distributor_id')}",
                            "created_at": now_iso(),
                        }
                        await db.commissions.insert_one(dict(comm))
                        await add_wallet_transaction(
                            sponsor["id"], "REFERRAL_COMMISSION", commission_amount, "CREDITED",
                            reference=order["id"],
                            description=f"Referral commission: {user.get('distributor_id')} activated",
                            direction="credit",
                        )
                        await create_notification(
                            sponsor["id"], "commission",
                            f"You earned {settings.get('currency_symbol','₹')}{int(commission_amount)}",
                            f"Referral commission credited for activation of {user.get('distributor_id')}.",
                            f"आपने {settings.get('currency_symbol','₹')}{int(commission_amount)} कमाए",
                            f"{user.get('distributor_id')} के सक्रिय होने पर रेफ़रल कमीशन क्रेडिट हुआ।")
                        await log_audit(None, "commission_credited", "commission", comm["id"],
                                        new_value={"amount": commission_amount, "sponsor": sponsor.get("distributor_id")},
                                        request=request)

    # ---- Product purchase level commission (separate from the ₹100 direct referral) ----
    await _distribute_purchase_commission(order, user, settings, request)


# Depth-based TEAM SALES commission. Depth 1 = the buyer's IMMEDIATE sponsor.
# Base = product value EXCLUDING GST. Total pool = 70%.
# SEPARATE from the ₹100 direct referral reward — the two never mix.
LEVEL_COMMISSION_PCT = {1: 20.0, 2: 12.0, 3: 10.0, 4: 8.0, 5: 6.0, 6: 5.0, 7: 4.0, 8: 3.0, 9: 2.0}
# User-facing rank/designation names by depth (backend keeps numeric levels internally).
RANK_NAME = {1: "Executive", 2: "Sr. Executive", 3: "Asst. Organizer", 4: "Organizer",
             5: "Sr. Organizer", 6: "Manager", 7: "Sr. Manager", 8: "Area Manager", 9: "Sr. Area Manager"}


async def _distribute_purchase_commission(order, buyer, settings, request=None):
    """Pay level-wise purchase commission on a PAID order, up the real sponsor chain.
    - Base = order subtotal (product value EXCLUDING GST).
    - Level is positional depth from the buyer (L1 = immediate sponsor).
    - Only GREEN/active uplines are paid; skipped uplines are NOT redistributed.
    - Idempotent: an order is claimed atomically so retries/refresh never duplicate.
    """
    # Activation orders pay ONLY the ₹100 direct referral reward (handled elsewhere).
    # Depth-based TEAM SALES commission applies to genuine PRODUCT purchases only.
    if order.get("is_activation_order"):
        return
    claim = await db.orders.update_one(
        {"id": order["id"], "purchase_commission_paid": {"$ne": True}},
        {"$set": {"purchase_commission_paid": True, "updated_at": now_iso()}},
    )
    if claim.modified_count != 1:
        return  # already processed
    base = float(order.get("subtotal", 0) or 0)  # product value excluding GST
    if base <= 0:
        return
    sym = settings.get("currency_symbol", "₹")
    current_id = buyer["id"]
    for level in range(1, 10):
        rel = await db.referral_relationships.find_one({"referred_user_id": current_id})
        if not rel or not rel.get("sponsor_id"):
            break
        sponsor_id = rel["sponsor_id"]
        pct = LEVEL_COMMISSION_PCT.get(level, 0.0)
        if pct > 0:
            sponsor = await db.users.find_one({"id": sponsor_id})
            if sponsor and sponsor.get("status") == "green":
                amount = round(base * pct / 100.0, 2)
                if amount > 0:
                    comm = {
                        "id": new_id(), "sponsor_id": sponsor_id,
                        "sponsor_distributor_id": sponsor.get("distributor_id"),
                        "referred_user_id": buyer["id"],
                        "referred_distributor_id": buyer.get("distributor_id"),
                        "type": "PURCHASE_LEVEL_COMMISSION", "level": level, "percent": pct,
                        "rank": RANK_NAME.get(level, f"Level {level}"),
                        "amount": amount, "base_amount": base,
                        "reference_order_id": order["id"], "status": "CREDITED",
                        "description": f"{RANK_NAME.get(level, f'Level {level}')} purchase commission ({pct:g}%) "
                                       f"on order {order.get('order_number')} by {buyer.get('distributor_id')}",
                        "created_at": now_iso(),
                    }
                    await db.commissions.insert_one(dict(comm))
                    await add_wallet_transaction(
                        sponsor_id, "PURCHASE_LEVEL_COMMISSION", amount, "CREDITED",
                        reference=order["id"],
                        description=f"Purchase commission • {RANK_NAME.get(level, f'Level {level}')} ({pct:g}%) • "
                                    f"base ₹{base:g} • order {order.get('order_number')} ({buyer.get('distributor_id')})",
                        direction="credit",
                    )
                    await create_notification(
                        sponsor_id, "commission",
                        f"You earned {sym}{amount:g}",
                        f"{RANK_NAME.get(level, f'Level {level}')} purchase commission ({pct:g}%) credited on order {order.get('order_number')}.",
                        f"आपने {sym}{amount:g} कमाए",
                        f"ऑर्डर {order.get('order_number')} पर {RANK_NAME.get(level, f'Level {level}')} खरीद कमीशन क्रेडिट हुआ।")
                    await log_audit(None, "purchase_commission_credited", "commission", comm["id"],
                                    new_value={"amount": amount, "level": level,
                                               "sponsor": sponsor.get("distributor_id")}, request=request)
        current_id = sponsor_id


@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request):
    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    if tx.get("payment_status") != "paid":
        try:
            sc = _stripe(request)
            status = await sc.get_checkout_status(session_id)
            if status.payment_status == "paid" or status.status == "complete":
                await _process_paid_order(session_id, request)
                tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        except Exception as e:
            print(f"[payment_status] error: {e}")
    return {"session_id": tx["session_id"], "status": tx["status"],
            "payment_status": tx["payment_status"], "order_id": tx.get("order_id")}


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        sc = _stripe(request)
        resp = await sc.handle_webhook(body, sig)
    except Exception as e:
        print(f"[webhook] error: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook")
    if resp.payment_status == "paid" and resp.session_id:
        await _process_paid_order(resp.session_id, request)
    return {"status": "ok"}


# ---------------- Manual UPI (PhonePe QR) — admin-confirmed ----------------
class UpiClaim(BaseModel):
    order_id: str
    reference: str = ""


@router.post("/payments/upi-claim")
async def upi_claim(body: UpiClaim, request: Request, user: dict = Depends(get_current_user)):
    order = await db.orders.find_one({"id": body.order_id}, {"_id": 0})
    if not order or order["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order["payment_status"] == "paid":
        raise HTTPException(status_code=400, detail="This order is already paid.")
    await db.orders.update_one({"id": order["id"]}, {"$set": {
        "payment_method": "upi_manual", "payment_status": "claimed",
        "upi_reference": body.reference, "updated_at": now_iso()}})
    await log_audit(user, "upi_payment_claimed", "order", order["id"],
                    new_value={"reference": body.reference}, request=request)
    return {"message": "Payment submitted. Admin will verify and activate shortly.", "order_id": order["id"]}


async def _create_activation_order(user: dict) -> dict:
    settings = await get_settings()
    amt = float(settings.get("activation_amount", 1500.0))
    prod = await db.products.find_one({"is_activation_product": True}, {"_id": 0})
    items = []
    if prod:
        items = [{"product_id": prod["id"], "sku": prod.get("sku"), "name": prod.get("name"),
                  "name_hi": prod.get("name_hi", ""), "image": (prod.get("images") or [None])[0],
                  "price": amt, "quantity": 1, "total": amt}]
    order = {
        "id": new_id(), "order_number": await next_sequence("order", "ORD", 6),
        "user_id": user["id"], "distributor_id": user.get("distributor_id"),
        "items": items, "subtotal": amt, "gst_amount": 0.0, "total": amt, "currency": "INR",
        "payment_status": "pending", "status": "payment_pending", "is_activation_order": True,
        "payment_method": "admin_manual",
        "address": {"full_name": user.get("full_name"), "mobile": user.get("mobile", ""),
                    "line1": user.get("address", ""), "city": user.get("city", ""),
                    "state": user.get("state", ""), "pincode": user.get("pincode", "")},
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.orders.insert_one(dict(order))
    return order


class ManualPayBody(BaseModel):
    distributor_id: str
    reference: str
    note: str = ""


@router.post("/admin/payments/manual")
async def manual_payment_by_distributor(body: ManualPayBody, request: Request, admin: dict = Depends(require_admin)):
    """ADMIN/MANUAL payment recorded against an existing Distributor ID. Never creates a user; no duplicates."""
    did = (body.distributor_id or "").strip().upper()
    ref = (body.reference or "").strip()
    if not did:
        raise HTTPException(status_code=400, detail="Distributor ID is required.")
    if not ref:
        raise HTTPException(status_code=400, detail="Payment reference / reason is required.")
    user = await db.users.find_one({"distributor_id": did})
    if not user:
        raise HTTPException(status_code=404, detail=f"No distributor found with ID {did}.")
    order = await db.orders.find_one({"user_id": user["id"], "payment_status": {"$ne": "paid"}},
                                     sort=[("created_at", -1)])
    if not order:
        order = await _create_activation_order(user)
    if order.get("payment_status") == "paid":
        return {"message": "This distributor's latest order is already paid.", "order_id": order["id"]}
    prev = order.get("payment_status")
    sid = f"admin_{order['id']}"
    if not await db.payment_transactions.find_one({"session_id": sid}):
        await db.payment_transactions.insert_one({
            "id": new_id(), "session_id": sid, "order_id": order["id"], "user_id": user["id"],
            "amount": float(order["total"]), "currency": order.get("currency", "INR"),
            "provider": "admin_manual", "reference": ref, "note": (body.note or "").strip(),
            "recorded_by": admin["id"], "status": "manual", "payment_status": "paid",
            "created_at": now_iso(), "updated_at": now_iso()})
    await db.orders.update_one({"id": order["id"]},
        {"$set": {"payment_reference": ref, "payment_method": "admin_manual", "updated_at": now_iso()}})
    await _process_paid_order(sid, request)
    await log_audit(admin, "admin_manual_payment", "order", order["id"],
                    old_value={"payment_status": prev},
                    new_value={"payment_status": "paid", "reference": ref, "distributor_id": did}, request=request)
    o = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
    return {"message": f"Manual payment recorded for {did}.", "order": o,
            "distributor_id": did, "full_name": user.get("full_name")}


class UpiConfirm(BaseModel):
    reference: str = ""


@router.put("/admin/payments/upi-confirm/{order_id}")
async def upi_confirm(order_id: str, body: UpiConfirm, request: Request, admin: dict = Depends(require_admin)):
    ref = (body.reference or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Payment reference ID (UTR / txn id) is required.")
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.get("payment_status") == "paid":
        return {"message": "Order already paid."}
    await db.orders.update_one({"id": order_id}, {"$set": {
        "payment_reference": ref, "upi_reference": ref, "updated_at": now_iso()}})
    sid = f"manual_{order_id}"
    if not await db.payment_transactions.find_one({"session_id": sid}):
        await db.payment_transactions.insert_one({
            "id": new_id(), "session_id": sid, "order_id": order_id, "user_id": order["user_id"],
            "amount": order["total"], "currency": order.get("currency", "INR"), "reference": ref,
            "status": "manual", "payment_status": "paid", "created_at": now_iso(), "updated_at": now_iso()})
    await _process_paid_order(sid, request)  # reuses verified activation + commission (idempotent)
    await log_audit(admin, "upi_payment_confirmed", "order", order_id, new_value={"reference": ref}, request=request)
    return {"message": "Payment confirmed and account activated.", "reference": ref}
