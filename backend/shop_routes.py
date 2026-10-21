"""Products, cart -> orders, and payment capture with server-side verification."""
import os
from decimal import Decimal, ROUND_HALF_UP
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
    variant: Optional[str] = None      # e.g. "Size: Free Size / Shade: Maroon"


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
    seller_ref: Optional[str] = None   # HomeGenie code from a share link (?ref=)
    payment_method: str = "online"     # "online" | "cod"


@router.post("/orders")
async def create_order(body: CreateOrder, request: Request, user: dict = Depends(get_current_user)):
    if not body.items:
        raise HTTPException(status_code=400, detail="Your cart is empty.")
    settings = await get_settings()
    gst_percent = settings.get("gst_percent", 5.0)

    line_items = []
    subtotal = 0.0
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
        line_items.append({
            "product_id": p["id"], "sku": p["sku"], "name": p["name"], "name_hi": p.get("name_hi", ""),
            "image": (p.get("images") or [None])[0], "price": price, "quantity": it.quantity,
            "variant": (it.variant or "").strip(),
            "total": round(total, 2),
        })

    cod = (body.payment_method or "online").lower() == "cod"
    if cod and not settings.get("cod_enabled", True):
        raise HTTPException(status_code=400, detail="Cash on delivery is not available right now.")
    cod_fee = float(settings.get("cod_fee", 0.0)) if cod else 0.0

    # Attribute the sale to the HomeGenie whose share link was used (if any).
    seller_user_id, seller_did = None, None
    ref = (body.seller_ref or "").strip().upper()
    if ref:
        seller = await db.users.find_one({"distributor_id": ref, "status": "green"}, {"_id": 0})
        if seller and seller["id"] != user["id"]:
            seller_user_id, seller_did = seller["id"], seller.get("distributor_id")

    gst_amount = round(subtotal * gst_percent / 100.0, 2)
    grand_total = round(subtotal + gst_amount + cod_fee, 2)
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
        "seller_user_id": seller_user_id,
        "seller_distributor_id": seller_did,
        "payment_method": "cod" if cod else "online",
        "cod_fee": cod_fee,
        # pending, payment_pending, confirmed, paid, processing, packed, shipped, delivered, cancelled, refunded
        "status": "confirmed" if cod else "payment_pending",
        "payment_status": "cod_pending" if cod else "pending",
        "invoice_number": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.orders.insert_one(dict(order))
    await log_audit(user, "order_created", "order", oid, new_value={"total": grand_total}, request=request)
    order.pop("_id", None)
    return order


@router.post("/orders/{order_id}/cod-collected")
async def cod_collected(order_id: str, request: Request, user: dict = Depends(get_current_user)):
    """Confirm that cash was collected for a COD order.

    Allowed for the attributed HomeGenie (own sale) and for admins. Commission is credited
    only at this point, never when the COD order is placed.
    """
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.get("payment_method") != "cod":
        raise HTTPException(status_code=400, detail="This is not a cash-on-delivery order.")
    is_admin = user.get("role") in ("admin", "super_admin")
    if not is_admin and order.get("seller_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Only the HomeGenie for this sale or an admin can confirm collection.")
    if order.get("payment_status") == "paid":
        return {"ok": True, "already": True}

    claim = await db.orders.update_one(
        {"id": order_id, "payment_status": "cod_pending"},
        {"$set": {"payment_status": "paid", "status": "delivered",
                  "cod_collected_by": user["id"],
                  "cod_collected_by_id": user.get("distributor_id"),
                  "cod_collected_role": "admin" if is_admin else "homegenie",
                  "cod_collected_at": now_iso(), "paid_at": now_iso(), "updated_at": now_iso()}})
    if claim.modified_count != 1:
        return {"ok": True, "already": True}

    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    buyer = await db.users.find_one({"id": order["user_id"]}, {"_id": 0})
    if not order.get("invoice_number"):
        inv = await next_sequence("invoice", "INV", 6)
        await db.orders.update_one({"id": order_id}, {"$set": {"invoice_number": inv}})
        order["invoice_number"] = inv
    from commission import distribute_sale_commissions
    result = await distribute_sale_commissions(order, buyer or {}, request)
    await log_audit(user, "cod_collected", "order", order_id,
                    new_value={"amount": order.get("total"), "commissions": result}, request=request)
    await create_notification(order["user_id"], "order", "Order delivered",
                              f"Cash received for order {order['order_number']}. Thank you!",
                              "ऑर्डर डिलीवर हुआ",
                              f"ऑर्डर {order['order_number']} के लिए नकद प्राप्त हुआ। धन्यवाद!")
    return {"ok": True, "commissions": result}


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


HG_COMMISSION_TYPES = ["COMMISSION_DIRECT", "COMMISSION_REFERRAL", "COMMISSION_TEAM"]


async def reverse_order_financials(order_id: str, actor: dict = None, request: Request = None,
                                   refund_amount: float = None, reference: str = "", reason: str = ""):
    """Auditable refund/clawback. Full refund (refund_amount None) or PARTIAL refund (amount of the
    order total actually returned). Each income credit tied to the order is clawed back in the same
    proportion (refund_amount / order total), never beyond what was credited. Originals are kept and
    marked REVERSED/PARTIALLY_REVERSED; linked CLAWBACK ledger entries are written. Idempotent: a
    refund event is keyed by (order, reference) and total refunds can never exceed the order total."""
    order = await db.orders.find_one({"id": order_id})
    if not order or order.get("payment_status") not in ("paid", "refunded", "partially_refunded"):
        return {"reversed": 0, "refund_amount": 0.0}
    total = float(order.get("total") or 0)
    already = float(order.get("refunded_amount") or 0)
    remaining = round(total - already, 2)
    amt = remaining if refund_amount is None else round(float(refund_amount), 2)
    if amt <= 0 or remaining <= 0:
        return {"reversed": 0, "refund_amount": 0.0}
    amt = min(amt, remaining)
    event_id = f"{order_id}:refund:{reference or 'full'}"
    try:
        await db.order_refunds.insert_one({"_id": event_id, "id": event_id, "order_id": order_id, "amount": amt, "reference": reference,
                                           "reason": reason, "status": "processing", "created_at": now_iso(),
                                           "actor_id": (actor or {}).get("id")})
    except Exception:
        return {"reversed": 0, "refund_amount": 0.0, "duplicate": True}
    claim = await db.orders.update_one(
        {"id": order_id, "refunded_amount": {"$in": [None, already]}},
        {"$set": {"refunded_amount": round(already + amt, 2), "updated_at": now_iso(),
                  "payment_status": "refunded" if round(already + amt, 2) >= total else "partially_refunded",
                  "financials_reversed": round(already + amt, 2) >= total}})
    if claim.modified_count != 1:
        await db.order_refunds.delete_one({"id": event_id})
        return {"reversed": 0, "refund_amount": 0.0, "conflict": True}
    fraction = amt / total if total else 1.0
    n = 0
    # Clawback HOME GENIES commissions tied to this order, in the refunded proportion.
    comms = await db.commissions.find(
        {"order_id": order_id, "status": {"$in": ["PENDING", "RELEASED", "PARTIALLY_REVERSED"]},
         "type": {"$in": HG_COMMISSION_TYPES}}).to_list(1000)
    for c in comms:
        credited = float(c["amount"]); done = float(c.get("reversed_amount") or 0)
        claw = round(credited * fraction, 2) if fraction < 1 else round(credited - done, 2)
        claw = min(claw, round(credited - done, 2))
        if claw <= 0:
            continue
        new_done = round(done + claw, 2)
        was_pending = c.get("status") == "PENDING"
        await db.commissions.update_one({"id": c["id"]}, {"$set": {
            "reversed_amount": new_done, "reversed_at": now_iso(),
            "status": "REVERSED" if new_done >= credited - 0.005 else "PARTIALLY_REVERSED"}})
        if was_pending:
            # never released: simply remove it from the pending pool
            await db.wallets.update_one({"user_id": c["user_id"]},
                                        {"$inc": {"pending_balance": -claw},
                                         "$set": {"updated_at": now_iso()}})
            await add_wallet_transaction(
                c["user_id"], "COMMISSION_CLAWBACK", claw, "INFO",
                reference=event_id, direction="debit",
                description=f"Pending commission cancelled - refund of order {order.get('order_number')}")
        else:
            await add_wallet_transaction(
                c["user_id"], "COMMISSION_CLAWBACK", claw, "CLAWBACK",
                reference=event_id, direction="debit",
                description=f"Clawback of {c.get('type')} on refund of order {order.get('order_number')}")
        n += 1
    await db.order_refunds.update_one({"id": event_id}, {"$set": {"status": "completed", "clawbacks": n}})
    await log_audit(actor, "order_financials_reversed", "order", order_id,
                    new_value={"reversed_entries": n, "refund_amount": amt, "reference": reference, "reason": reason}, request=request)
    return {"reversed": n, "refund_amount": amt, "refund_event": event_id}


async def _process_paid_order(session_id: str, request: Request = None):
    """Idempotent: mark order paid, generate the invoice and credit pending sale commissions."""
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
    claim = await db.orders.update_one(
        {"id": order["id"], "payment_status": {"$ne": "paid"}},
        {"$set": {"payment_status": "paid", "status": "processing",
                  "invoice_number": invoice_number, "paid_at": now_iso(), "updated_at": now_iso()}},
    )
    if claim.modified_count != 1:
        return  # concurrent webhook/verify already claimed this order
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

    # ---- HOME GENIES commission engine (30% direct / 10% referral / 5% team) ----
    # Credited as PENDING points; released after the return window by the points cron.
    from commission import distribute_sale_commissions
    await distribute_sale_commissions(order, user, request)


# Positional TEAM SALES commission matrix (FINAL, locked). Position 1 = buyer's IMMEDIATE sponsor.
# S = product subtotal EXCLUDING GST. Company direct share = 30% of S. Commission POOL = 70% of S.
# Position rates apply to the POOL (45% of pool paid out; the other 55% of pool stays with company).
# GD 0 | BD 15 | AD 5 | CD 5 | PD 5 | MD 5 | RD 4 | DD 3 | MDD 3  =>  45% of pool
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


# ---------------- Manual UPI — admin-confirmed ----------------
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
    return {"message": "Payment submitted. Our team will verify it shortly.", "order_id": order["id"]}


class ManualPayBody(BaseModel):
    distributor_id: str
    reference: str
    note: str = ""


@router.post("/admin/payments/manual")
async def manual_payment_by_distributor(body: ManualPayBody, request: Request, admin: dict = Depends(require_admin)):
    """ADMIN/MANUAL payment recorded against an existing HomeGenie ID. Never creates a user; no duplicates."""
    did = (body.distributor_id or "").strip().upper()
    ref = (body.reference or "").strip()
    if not did:
        raise HTTPException(status_code=400, detail="HomeGenie ID is required.")
    if not ref:
        raise HTTPException(status_code=400, detail="Payment reference / reason is required.")
    user = await db.users.find_one({"distributor_id": did})
    if not user:
        raise HTTPException(status_code=404, detail=f"No HomeGenie found with ID {did}.")
    order = await db.orders.find_one({"user_id": user["id"], "payment_status": {"$ne": "paid"}},
                                     sort=[("created_at", -1)])
    if not order:
        raise HTTPException(status_code=404, detail="This member has no pending order to mark as paid.")
    if order.get("payment_status") == "paid":
        return {"message": "This member's latest order is already paid.", "order_id": order["id"]}
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
    await _process_paid_order(sid, request)  # idempotent: invoice + pending commissions
    await log_audit(admin, "upi_payment_confirmed", "order", order_id, new_value={"reference": ref}, request=request)
    return {"message": "Payment confirmed and account activated.", "reference": ref}
