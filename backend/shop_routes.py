"""Products, cart -> orders, and payment capture with server-side verification."""
import os
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from typing import List, Optional

try:  # Emergent's private package (preinstalled only in Emergent's image) — unchanged behaviour there
    from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest
    _STRIPE_VIA_EMERGENT = True
except ImportError:  # other hosts (e.g. Vercel): same interface on the official `stripe` SDK
    from stripe_checkout import StripeCheckout, CheckoutSessionRequest, configured as _stripe_key_configured
    _STRIPE_VIA_EMERGENT = False

from money import to_paise, paise_to_float, mul_pct, mul_ratio, paise_of
from core import (db, now_iso, new_id, get_current_user, get_settings, next_sequence, wallet_apply,
                  add_wallet_transaction, create_notification, log_audit, require_admin, P_PUBLIC)
from stock import (expire_one, expire_pending_online_orders, handle_late_payment, EXPIRY_REASON, reserve_for_order,
                   mark_reserve_bound, abandon_reservation)

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
    q = {"approval_status": {"$in": [None, "approved"]}}
    if active:
        q["is_active"] = True
    if category:
        q["category"] = category
    items = await db.products.find(q, P_PUBLIC).sort("created_at", 1).to_list(200)
    return items


@router.get("/products/{product_id}")
async def get_product(product_id: str):
    p = await db.products.find_one({"id": product_id, "approval_status": {"$in": [None, "approved"]}}, P_PUBLIC)
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
    variant: Optional[str] = None      # e.g. "Size: Free Size / Shade: Maroon" (free-text label, legacy)
    variant_sku: Optional[str] = None  # required when the product has variants


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
    subtotal_p = 0   # exact integer paise; the rupee floats stored on the order are derived from these
    product_ids = [it.product_id for it in body.items]
    products = {p["id"]: p for p in await db.products.find(
        {"id": {"$in": product_ids}}, {"_id": 0}).to_list(len(product_ids) or 1)}
    for it in body.items:
        p = products.get(it.product_id)
        if not p or not p.get("is_active") or p.get("approval_status", "approved") != "approved":
            raise HTTPException(status_code=400, detail="A product in your cart is unavailable.")
        vsku, label = None, (it.variant or "").strip()
        sell = p["selling_price"]
        if p.get("variants"):
            vsku = (it.variant_sku or "").strip().upper()
            var = next((x for x in p["variants"] if x["sku"] == vsku), None)
            if not var:
                raise HTTPException(status_code=400, detail=f"Please choose an option for {p['name']}.")
            sell = var.get("price") or p["selling_price"]
            label = label or ", ".join(f"{k}: {v}" for k, v in var["attributes"].items())
        elif it.variant_sku:
            raise HTTPException(status_code=400, detail=f"{p['name']} has no variants.")
        price_p = to_paise(sell)
        total_p = price_p * it.quantity
        subtotal_p += total_p
        line_items.append({
            "product_id": p["id"], "sku": p["sku"], "name": p["name"], "name_hi": p.get("name_hi", ""),
            "image": (p.get("images") or [None])[0], "price": paise_to_float(price_p), "price_paise": price_p,
            "quantity": it.quantity, "variant": label, "variant_sku": vsku,
            "handling_days": int((p.get("package") or {}).get("handling_days", settings.get("dispatch_deadline_days", 3))),
            "total": paise_to_float(total_p), "total_paise": total_p,
            # order-time snapshot of who fulfils this line (None = platform-fulfilled)
            "vendor_id": p.get("vendor_id"), "vendor_name": p.get("vendor_name"),
        })

    cod = (body.payment_method or "online").lower() == "cod"
    if cod and not settings.get("cod_enabled", True):
        raise HTTPException(status_code=400, detail="Cash on delivery is not available right now.")
    cod_fee_p = to_paise(settings.get("cod_fee", 0.0)) if cod else 0

    # Attribute the sale to the HomeGenie whose share link was used (if any).
    seller_user_id, seller_did = None, None
    ref = (body.seller_ref or "").strip().upper()
    if ref:
        seller = await db.users.find_one({"distributor_id": ref, "status": "green"}, {"_id": 0})
        if seller and seller["id"] != user["id"]:
            seller_user_id, seller_did = seller["id"], seller.get("distributor_id")

    gst_p = mul_pct(subtotal_p, gst_percent)
    total_paise = subtotal_p + gst_p + cod_fee_p
    gst_amount, grand_total, subtotal, cod_fee = paise_to_float(gst_p), paise_to_float(total_paise), paise_to_float(subtotal_p), paise_to_float(cod_fee_p)
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
        "gst_amount": gst_amount, "gst_paise": gst_p,
        "total": grand_total, "total_paise": total_paise, "subtotal_paise": subtotal_p, "money_version": 2,
        "currency": settings.get("currency", "INR"),
        "address": body.address.model_dump(),
        "seller_user_id": seller_user_id,
        "seller_distributor_id": seller_did,
        "payment_method": "cod" if cod else "online",
        "cod_fee": cod_fee, "cod_fee_paise": cod_fee_p,
        # pending, payment_pending, confirmed, paid, processing, packed, shipped, delivered, cancelled, refunded
        "status": "confirmed" if cod else "payment_pending",
        "payment_status": "cod_pending" if cod else "pending",
        "invoice_number": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    # One fulfilment group per vendor in the cart; platform-owned lines stay with admin.
    vendor_ids = []
    for li in line_items:
        if li.get("vendor_id") and li["vendor_id"] not in vendor_ids:
            vendor_ids.append(li["vendor_id"])
    order["fulfilments"] = [{
        "vendor_id": v, "vendor_name": next(li.get("vendor_name") for li in line_items if li.get("vendor_id") == v),
        "status": "new", "carrier": "", "tracking_number": "", "tracking_url": "", "note": "",
        "events": [{"status": "new", "at": now_iso(), "by": "system", "note": ""}],
    } for v in vendor_ids]

    # Free stock held by overdue unpaid online orders before reserving (15-minute payment window).
    await expire_pending_online_orders(limit=50)

    # Reserve stock for every line, all-or-nothing, as a journaled transaction (survives crashes; see stock.py).
    short = await reserve_for_order(oid, line_items, user["id"])
    if short:
        raise HTTPException(status_code=409, detail=f"Not enough stock for {short['name']}. Please reduce the quantity.")
    order["stock_reserved"] = True
    try:
        await db.orders.insert_one(dict(order))
    except Exception:
        await abandon_reservation(oid)      # never leave stock reserved for an order that was not saved
        raise
    await mark_reserve_bound(oid)
    if cod:    # COD orders are actionable at once; online orders notify the vendor when payment is confirmed
        from core import notify_order_vendors
        await notify_order_vendors(order, "New order", f"New order {order_number}: please accept and pack it.")
    await log_audit(user, "order_created", "order", oid, new_value={"total": grand_total}, request=request)
    order.pop("_id", None)
    return order


class CodCollectIn(BaseModel):
    amount_collected: Optional[float] = Field(default=None, gt=0)   # rupees actually received; omitted = the full order total


@router.post("/orders/{order_id}/cod-collected")
async def cod_collected(order_id: str, request: Request, user: dict = Depends(get_current_user), body: Optional[CodCollectIn] = None):
    """Confirm that cash was collected for a COD order.

    Allowed for the attributed HomeGenie (own sale) and for admins. Commission is credited
    only at this point, never when the COD order is placed. If the reported amount differs from the order total the
    order is held as a COD DISCREPANCY: no payment confirmation, commission or vendor sale until an admin resolves it.
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
    if order.get("payment_status") == "cod_discrepancy":
        return {"ok": True, "discrepancy": True, "already": True}
    if order.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="This order is cancelled, so cash cannot be confirmed for it.")
    expected_p = paise_of(order, "total_paise", "total")
    collected_p = to_paise(body.amount_collected) if body and body.amount_collected is not None else expected_p
    if collected_p != expected_p:
        held = await db.orders.update_one(
            {"id": order_id, "payment_status": "cod_pending"},
            {"$set": {"payment_status": "cod_discrepancy", "updated_at": now_iso(),
                      "cod_discrepancy": {"expected_paise": expected_p, "collected_paise": collected_p, "status": "open",
                                          "reported_by": user["id"], "reported_at": now_iso()}}})
        if held.modified_count == 1:
            await log_audit(user, "cod_discrepancy_reported", "order", order_id,
                            new_value={"expected_paise": expected_p, "collected_paise": collected_p}, request=request)
            for a in await db.users.find({"role": {"$in": ["super_admin", "accounts_admin"]}}, {"_id": 0, "id": 1}).to_list(20):
                await create_notification(a["id"], "order", "COD discrepancy",
                                          f"Order {order['order_number']}: expected {paise_to_float(expected_p)}, reported {paise_to_float(collected_p)}.",
                                          meta={"order_id": order_id})
        return {"ok": True, "discrepancy": True, "expected": paise_to_float(expected_p), "collected": paise_to_float(collected_p)}

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
    from ledger import post_order_collected
    await post_order_collected(order)                       # vendor sale recorded now that the cash is confirmed
    await log_audit(user, "cod_collected", "order", order_id,
                    new_value={"amount": order.get("total"), "commissions": result}, request=request)
    await create_notification(order["user_id"], "order", "Order delivered",
                              f"Cash received for order {order['order_number']}. Thank you!",
                              "ऑर्डर डिलीवर हुआ",
                              f"ऑर्डर {order['order_number']} के लिए नकद प्राप्त हुआ। धन्यवाद!")
    return {"ok": True, "commissions": result}


@router.get("/orders")
async def my_orders(user: dict = Depends(get_current_user)):
    await expire_pending_online_orders(limit=50)
    return await db.orders.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.get("/orders/{order_id}")
async def get_order(order_id: str, user: dict = Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o["user_id"] != user["id"] and user.get("role") not in ("admin", "super_admin", "accounts_admin", "support_admin"):
        raise HTTPException(status_code=403, detail="Access denied.")
    if await expire_one(order_id):   # only after the access check; no-op unless an overdue unpaid online order
        o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return o


# ---------------- Payments ----------------
async def _ensure_payable(order: dict) -> dict:
    """Refuse to start a new payment on an order whose 15-minute window has passed (or that is cancelled)."""
    if order.get("payment_method") == "online" and order.get("payment_status") == "pending":
        await expire_one(order["id"])
        order = await db.orders.find_one({"id": order["id"]}, {"_id": 0}) or order
    if order.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="This order was cancelled because payment was not completed in time. Please place a new order.")
    return order


class CheckoutBody(BaseModel):
    order_id: str
    origin_url: str


def _stripe(request: Request):
    if not _STRIPE_VIA_EMERGENT and not _stripe_key_configured(STRIPE_API_KEY):
        raise HTTPException(status_code=503, detail="Card checkout is not configured yet. Please use another payment method.")
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
    order = await _ensure_payable(order)

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
    order = await _ensure_payable(order)
    client = _razorpay_client()
    amount_paise = paise_of(order, "total_paise", "total")
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
    expected_paise = to_paise(tx["amount"])
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
                                   refund_amount: float = None, reference: str = "", reason: str = "",
                                   case_id: str = None, vendor_id: str = None):
    """Auditable refund/clawback in EXACT integer paise. Full refund (refund_amount None) or PARTIAL refund (amount of the
    order total actually returned). Each income credit tied to the order is clawed back in the same proportion
    (refund / order total, rounded half-up per credit), never beyond what was credited; the FINAL refund that closes the
    order claws back exactly the remainder, so credits and clawbacks always reconcile to the paisa. Originals are kept and
    marked REVERSED/PARTIALLY_REVERSED; linked CLAWBACK ledger entries are written. Idempotent: a refund event is keyed by
    (order, reference) and total refunds can never exceed the order total."""
    order = await db.orders.find_one({"id": order_id})
    if not order or order.get("payment_status") not in ("paid", "refunded", "partially_refunded"):
        return {"reversed": 0, "refund_amount": 0.0}
    total_p = paise_of(order, "total_paise", "total")
    already_p = paise_of(order, "refunded_paise", "refunded_amount")
    remaining_p = total_p - already_p
    amt_p = remaining_p if refund_amount is None else to_paise(refund_amount)
    if amt_p <= 0 or remaining_p <= 0:
        return {"reversed": 0, "refund_amount": 0.0}
    amt_p = min(amt_p, remaining_p)
    new_total_refunded_p = already_p + amt_p
    closes_order = new_total_refunded_p >= total_p
    event_id = f"{order_id}:refund:{reference or 'full'}"
    try:
        await db.order_refunds.insert_one({"_id": event_id, "id": event_id, "order_id": order_id, "amount": paise_to_float(amt_p),
                                           "amount_paise": amt_p, "closes_order": closes_order, "reference": reference, "case_id": case_id, "vendor_id": vendor_id,
                                           "reason": reason, "status": "processing", "created_at": now_iso(),
                                           "actor_id": (actor or {}).get("id")})
    except Exception:
        return {"reversed": 0, "refund_amount": 0.0, "duplicate": True}
    # Optimistic claim on the exact refunded counter (equal to the value read above), so two refunds cannot interleave.
    if "refunded_paise" in order:
        claim_filter = {"id": order_id, "refunded_paise": already_p}
    else:   # legacy order: guard on the stored float counter exactly as it was read
        claim_filter = {"id": order_id, "refunded_paise": {"$exists": False}, "refunded_amount": order.get("refunded_amount")}
    claim = await db.orders.update_one(
        claim_filter,
        {"$set": {"refunded_paise": new_total_refunded_p, "refunded_amount": paise_to_float(new_total_refunded_p),
                  "updated_at": now_iso(),
                  "payment_status": "refunded" if closes_order else "partially_refunded",
                  "financials_reversed": closes_order}})
    if claim.modified_count != 1:
        await db.order_refunds.delete_one({"id": event_id})
        return {"reversed": 0, "refund_amount": 0.0, "conflict": True}
    n = 0
    # Clawback HOME GENIES commissions tied to this order, in the refunded proportion.
    comms = await db.commissions.find(
        {"order_id": order_id, "status": {"$in": ["PENDING", "RELEASED", "PARTIALLY_REVERSED"]},
         "type": {"$in": HG_COMMISSION_TYPES}}).to_list(1000)
    for c in comms:
        credited_p = paise_of(c, "amount_paise", "amount")
        done_p = paise_of(c, "reversed_paise", "reversed_amount")
        room_p = credited_p - done_p
        claw_p = room_p if closes_order else mul_ratio(credited_p, amt_p, total_p)
        claw_p = min(claw_p, room_p)
        if claw_p <= 0:
            continue
        new_done_p = done_p + claw_p
        was_pending = not c.get("released_at")   # not yet released: the credit still sits in the PENDING pool (also when
                                                  # it was already partially reversed by an earlier partial refund)
        await db.commissions.update_one({"id": c["id"]}, {"$set": {
            "reversed_paise": new_done_p, "reversed_amount": paise_to_float(new_done_p), "reversed_at": now_iso(),
            "status": "REVERSED" if new_done_p >= credited_p else "PARTIALLY_REVERSED"}})
        claw = paise_to_float(claw_p)
        if was_pending:
            # never released: simply remove it from the pending pool
            await wallet_apply(c["user_id"], {"pending_balance": -claw_p})
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
    from ledger import post_refund_shares
    refund_doc = await db.order_refunds.find_one({"id": event_id}, {"_id": 0})
    await post_refund_shares(await db.orders.find_one({"id": order_id}, {"_id": 0}), refund_doc)     # vendors' share of this refund
    if not case_id:                                         # the one-step Refund action also settles any open refund case
        from returns_routes import confirm_open_cases_for_order
        await confirm_open_cases_for_order(order_id, refund_doc, (actor or {}).get("id", "system"))
    await log_audit(actor, "order_financials_reversed", "order", order_id,
                    new_value={"reversed_entries": n, "refund_amount": paise_to_float(amt_p), "reference": reference, "reason": reason}, request=request)
    return {"reversed": n, "refund_amount": paise_to_float(amt_p), "refund_event": event_id}


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
    # A payment for an already-cancelled order must never silently re-open it (its stock may have been returned).
    cancelled = order.get("status") == "cancelled"
    revivable = cancelled and order.get("cancel_reason") == EXPIRY_REASON   # expired by the 15-minute rule
    invoice_number = None if cancelled else await next_sequence("invoice", "INV", 6)
    paid_set = {"payment_status": "paid", "paid_at": now_iso(), "updated_at": now_iso()}
    if not cancelled:
        paid_set.update({"status": "processing", "invoice_number": invoice_number})
    claim = await db.orders.update_one({"id": order["id"], "payment_status": {"$ne": "paid"}}, {"$set": paid_set})
    if claim.modified_count != 1:
        return  # concurrent webhook/verify already claimed this order
    await db.payment_transactions.update_one(
        {"session_id": session_id},
        {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}},
    )
    if cancelled:
        # Expired order: take the stock back if still available. Admin-cancelled order: flag for refund. Otherwise refund.
        if not await handle_late_payment(order, allow_revive=revivable):
            return  # no commission / no invoice for an order that cannot be fulfilled
        invoice_number = await next_sequence("invoice", "INV", 6)
        await db.orders.update_one({"id": order["id"]}, {"$set": {"invoice_number": invoice_number}})

    from ledger import post_order_collected
    fresh_order = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
    await post_order_collected(fresh_order)   # vendor sale: payment is confirmed
    from core import notify_order_vendors
    await notify_order_vendors(fresh_order, "New order", f"New paid order {fresh_order.get('order_number')}: please accept and pack it.")
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
