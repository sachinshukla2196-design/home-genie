"""Products, cart -> orders, and payment capture with server-side verification."""
import os
import re
from datetime import datetime, timedelta, timezone
import logging
from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Body, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator
from typing import Any, List, Optional

try:  # Emergent's private package (preinstalled only in Emergent's image) — unchanged behaviour there
    from emergentintegrations.payments.stripe.checkout import StripeCheckout, CheckoutSessionRequest
    _STRIPE_VIA_EMERGENT = True
except ImportError:  # other hosts (e.g. Vercel): same interface on the official `stripe` SDK
    from stripe_checkout import StripeCheckout, CheckoutSessionRequest, configured as _stripe_key_configured
    _STRIPE_VIA_EMERGENT = False

from money import to_paise, paise_to_float, mul_ratio, paise_of
from cod_rules import refundable_total_paise, require_confirmer_role, refuse_own_sale, parse_collection_evidence, hold_reason
from pymongo.errors import DuplicateKeyError
from core import (db, now_iso, new_id, get_current_user, get_settings, next_sequence, wallet_apply,
                  add_wallet_transaction, create_notification, log_audit, require_admin, P_PUBLIC)
from stock import (expire_one, expire_pending_online_orders, handle_late_payment, EXPIRY_REASON, reserve_for_order,
                   mark_reserve_bound, abandon_reservation)

logger = logging.getLogger("homegenies")
router = APIRouter(prefix="/api", tags=["shop"])

import razorpay
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")


def _razorpay_client():
    if not (RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET):
        raise HTTPException(status_code=503, detail="Online payment is not configured yet. Please use UPI or contact admin.")
    return razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

STRIPE_API_KEY = os.environ.get("STRIPE_API_KEY", "sk_test_emergent")


# ---------------- GST-inclusive pricing (Decision 1) ----------------
def _line_gst_rate(product: dict, platform_rate) -> float:
    """The product's own GST rate when it has a valid one (0-28 %), otherwise the platform GST setting. No rate is invented."""
    r = product.get("gst_percent")
    if isinstance(r, (int, float)) and not isinstance(r, bool) and 0 <= r <= 28:
        return float(r)
    return float(platform_rate or 0)


def _taxable_part(inclusive_paise: int, rate: float) -> int:
    """Taxable value inside a GST-inclusive amount: inclusive x 100 / (100 + rate), rounded half-up to the paisa."""
    if not rate:
        return inclusive_paise
    return int((Decimal(inclusive_paise) * 100 / (Decimal(100) + Decimal(str(rate)))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---------------- Products ----------------
# The public shop shows only products that can actually be bought: approved, listed, not archived (CAT-04, SEC-23).
# Admins list every product through GET /api/admin/products instead.
SHOP_VISIBLE = {"approval_status": {"$in": [None, "approved"]}, "is_active": True, "archived": {"$ne": True}}


# What shoppers may see of a product (Batch 12): never a vendor's unapproved pending changes, its price history, the compliance
# documents it gave for review, or who prepared / reviewed it.
P_SHOP = {**P_PUBLIC, "pending_revision": 0, "price_history": 0, "compliance_documents": 0, "created_by": 0,
          "created_on_behalf_by": 0, "reviewed_by": 0, "rejection_reason": 0, "status_set_by_admin": 0}


@router.get("/products")
async def list_products(category: Optional[str] = None):
    q = dict(SHOP_VISIBLE)
    if category:
        q["category"] = category
    items = await db.products.find(q, P_SHOP).sort("created_at", 1).to_list(200)
    return items


@router.get("/products/{product_id}")
async def get_product(product_id: str):
    p = await db.products.find_one({"id": product_id, **SHOP_VISIBLE}, P_SHOP)
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
    """A typed delivery address (Batch 13: validated on the server; a saved address is sent as `address_id` instead)."""
    full_name: str = Field(min_length=2, max_length=80)
    mobile: str
    line1: str = Field(min_length=3, max_length=160)
    line2: str = Field(default="", max_length=120)
    landmark: str = Field(default="", max_length=120)
    city: str = Field(min_length=2, max_length=60)
    state: str = Field(min_length=2, max_length=60)
    pincode: str

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v):
        v = re.sub(r"[\s-]", "", v or "")
        v = v[3:] if v.startswith("+91") else v
        if not re.fullmatch(r"[6-9]\d{9}", v):
            raise ValueError("Enter a valid 10-digit mobile number.")
        return v

    @field_validator("pincode")
    @classmethod
    def _pin(cls, v):
        v = (v or "").strip()
        if not re.fullmatch(r"[1-9]\d{5}", v):
            raise ValueError("Enter a valid 6-digit PIN code.")
        return v

    @field_validator("full_name", "line1", "line2", "landmark", "city", "state")
    @classmethod
    def _plain(cls, v):
        v = (v or "").strip()
        if any(ch in v for ch in "<>"):
            raise ValueError("Address fields cannot contain < or >.")
        return v


class CreateOrder(BaseModel):
    items: List[OrderItemIn]
    address: Optional[AddressIn] = None
    address_id: Optional[str] = None    # Batch 13: a saved address (copied into the order as a snapshot)
    seller_ref: Optional[str] = None   # HomeGenie code from a share link (?ref=)
    payment_method: str = "online"     # "online" | "cod"


@router.post("/orders")
async def create_order(body: CreateOrder, request: Request, user: dict = Depends(get_current_user)):
    if not body.items:
        raise HTTPException(status_code=400, detail="Your cart is empty.")
    from money_guard import ensure as _money_guard          # Programme 01 (B-004): fail closed without the unique indexes
    await _money_guard("orders", "stock")
    # Programme 01 (B-006): protection BEFORE anything is reserved - one order per identical submission, then the per-account
    # and per-IP rate limits and the open-order cap (order_protection). A refused or failed attempt releases its claim.
    from order_protection import fingerprint, claim_submission, bind_submission, release_submission, check_limits
    fp = fingerprint(user["id"], body)
    claimed, existing = await claim_submission(fp)
    if not claimed:
        return {**existing, "duplicate_submission": True}
    try:
        await check_limits(user, request)
        order = await _create_order(body, request, user)
    except Exception:
        await release_submission(fp)
        raise
    await bind_submission(fp, order["id"])
    return order


async def _create_order(body: CreateOrder, request: Request, user: dict):
    # the delivery address is settled BEFORE anything is reserved: a saved one is copied (snapshot), a typed one was validated
    if body.address_id:
        from customer_routes import address_snapshot
        address = await address_snapshot(user["id"], body.address_id)
    elif body.address:
        address = body.address.model_dump()
    else:
        raise HTTPException(status_code=400, detail="Choose a delivery address.")
    settings = await get_settings()
    gst_percent = settings.get("gst_percent", 5.0)

    line_items = []
    subtotal_p = 0   # exact integer paise; the rupee floats stored on the order are derived from these
    gst_sum_p = 0    # GST contained in the inclusive line totals
    inclusive_p = 0  # what the customer pays for the goods (before any COD fee)
    product_ids = [it.product_id for it in body.items]
    products = {p["id"]: p for p in await db.products.find(
        {"id": {"$in": product_ids}}, {"_id": 0}).to_list(len(product_ids) or 1)}
    for it in body.items:
        p = products.get(it.product_id)
        if not p or not p.get("is_active") or p.get("archived") or p.get("approval_status", "approved") != "approved":
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
        total_p = price_p * it.quantity           # Decision 1: the shelf price INCLUDES GST
        rate = _line_gst_rate(p, gst_percent)
        taxable_p = _taxable_part(total_p, rate)
        line_gst_p = total_p - taxable_p
        subtotal_p += taxable_p                   # the pre-GST (taxable) value: the base for commission and activation
        gst_sum_p += line_gst_p
        inclusive_p += total_p
        line_items.append({
            "product_id": p["id"], "sku": p["sku"], "name": p["name"], "name_hi": p.get("name_hi", ""),
            "image": (p.get("images") or [None])[0], "price": paise_to_float(price_p), "price_paise": price_p,
            "quantity": it.quantity, "variant": label, "variant_sku": vsku,
            "handling_days": int((p.get("package") or {}).get("handling_days", settings.get("dispatch_deadline_days", 3))),
            "total": paise_to_float(total_p), "total_paise": total_p,
            # order-time snapshot of who fulfils this line (None = platform-fulfilled)
            "vendor_id": p.get("vendor_id"), "vendor_name": p.get("vendor_name"),
            # CAT-02 (data only): the product's own tax classification at order time. The order TOTAL still uses the
            # platform GST setting until the owner decides whether shelf prices include GST (decision gate 1).
            "product_gst_percent": p.get("gst_percent"), "hsn_code": p.get("hsn_code") or "",
            # Decision 1 (GST-inclusive): the invoice breakdown of this line; total_paise = taxable_paise + gst_paise
            "gst_rate": rate, "taxable_paise": taxable_p, "taxable": paise_to_float(taxable_p),
            "gst_paise": line_gst_p, "gst_amount": paise_to_float(line_gst_p),
        })

    cod = (body.payment_method or "online").lower() == "cod"
    if cod and not settings.get("cod_enabled", True):
        raise HTTPException(status_code=400, detail="Cash on delivery is not available right now.")
    cod_fee_p = to_paise(settings.get("cod_fee", 0.0)) if cod else 0

    # Attribute the sale to the HomeGenie whose share link was used (if any).
    seller_user_id, seller_did = None, None
    ref = (body.seller_ref or "").strip().upper()
    if ref:
        # only an active HomeGenie (distributor, green) can be a commission-earning seller; other share codes attribute nothing
        seller = await db.users.find_one({"distributor_id": ref, "role": "distributor", "status": "green"}, {"_id": 0})
        if seller and seller["id"] != user["id"]:
            seller_user_id, seller_did = seller["id"], seller.get("distributor_id")

    gst_p = gst_sum_p
    total_paise = inclusive_p + cod_fee_p        # GST is already inside the prices; it is shown, never added on top
    rates = sorted({li["gst_rate"] for li in line_items})
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
        "gst_percent": rates[0] if len(rates) == 1 else None,      # None when lines carry different rates
        "gst_amount": gst_amount, "gst_paise": gst_p,
        "total": grand_total, "total_paise": total_paise, "subtotal_paise": subtotal_p, "money_version": 3,
        "prices_include_gst": True, "items_total_paise": inclusive_p, "items_total": paise_to_float(inclusive_p),
        "currency": settings.get("currency", "INR"),
        "address": address,
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
    await expire_pending_online_orders(limit=50, max_seconds=2)     # B-006: bounded inline; the cron finishes the rest

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


def _cod_delivery_fields(order: dict) -> dict:
    """Batch 12 (audit C-5d): confirming COD cash records the payment, not the delivery. Vendor goods are delivered by the
    vendor's fulfilment (which rolls the order to delivered); only an order without vendor fulfilments, or whose fulfilments are
    already finished, shows as delivered here. No payout clock starts from this step (eligibility reads the fulfilments)."""
    from eligibility import delivered_at as _delivered
    if not order.get("fulfilments"):
        return {"status": "delivered", "delivered_at": now_iso()}
    return {"status": "delivered"} if _delivered(order) else {}


@router.post("/orders/{order_id}/cod-collected")
async def cod_collected(order_id: str, request: Request, user: dict = Depends(get_current_user), body: Any = Body(default=None)):
    """Confirm that cash was collected for a COD order. The rules live in `cod_rules` (see its docstring).

    Order of checks, so a refused request changes nothing and reveals nothing:
      1. role gate (admin or super_admin only; accounts_admin and everyone else are refused),
      2. the order exists and is a COD order, and the actor is not the HomeGenie attributed to it,
      3. already-processed orders return unchanged,
      4. only now is the body read and validated (amount, evidence type, reference),
      5. a manual exception, or any amount other than the order total, is HELD for independent review and never paid here,
      6. otherwise the order is claimed once with a conditional update and commission is distributed once.
    """
    require_confirmer_role(user)
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.get("payment_method") != "cod":
        raise HTTPException(status_code=400, detail="This is not a cash-on-delivery order.")
    refuse_own_sale(user, order)
    if order.get("payment_status") == "paid":
        if order.get("completion_due"):     # Programme 01 (B-003): a repeated confirmation finishes an interrupted completion
            from order_completion import complete_paid_order
            await complete_paid_order(order_id, request, source="cod_collection_retry", notify=False)
        return {"ok": True, "already": True}
    if order.get("payment_status") == "cod_discrepancy":
        return {"ok": True, "discrepancy": True, "already": True}
    if order.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="This order is cancelled, so cash cannot be confirmed for it.")
    entry = parse_collection_evidence(body)
    from cod_rules import expected_cod_paise, unsupplied_goods_paise
    expected_p = expected_cod_paise(order)          # audit C-8: goods a vendor did not supply are not collected
    collected_p = to_paise(entry.amount_collected)
    evidence = {"type": entry.evidence_type, "reference": entry.evidence_reference, "note": entry.note,
                "recorded_by": user["id"], "recorded_at": now_iso(),
                "verified_by_system": False}      # no courier or provider integration exists; the reference is recorded, not verified
    reason = hold_reason(entry.evidence_type, collected_p, expected_p)
    if reason:
        held = await db.orders.update_one(
            {"id": order_id, "payment_status": "cod_pending"},
            {"$set": {"payment_status": "cod_discrepancy", "updated_at": now_iso(),
                      "cod_discrepancy": {"expected_paise": expected_p, "collected_paise": collected_p, "status": "open",
                                          "reason": reason, "evidence": evidence,
                                          "reported_by": user["id"], "reported_at": now_iso()}}})
        if held.modified_count == 1:
            await log_audit(user, "cod_discrepancy_reported", "order", order_id,
                            new_value={"expected_paise": expected_p, "collected_paise": collected_p, "reason": reason,
                                       "evidence_type": entry.evidence_type}, request=request)
            for a in await db.users.find({"role": {"$in": ["super_admin", "accounts_admin"]}}, {"_id": 0, "id": 1}).to_list(20):
                await create_notification(a["id"], "order", "COD discrepancy",
                                          f"Order {order['order_number']}: expected {paise_to_float(expected_p)}, reported {paise_to_float(collected_p)}.",
                                          meta={"order_id": order_id})
        return {"ok": True, "discrepancy": True, "expected": paise_to_float(expected_p), "collected": paise_to_float(collected_p),
                "reason": reason}

    claim = await db.orders.update_one(
        {"id": order_id, "payment_status": "cod_pending"},
        {"$set": {"payment_status": "paid", **_cod_delivery_fields(order),
                  "cod_expected_paise": expected_p, "cod_collected_paise": collected_p,
                  **({"commission_base_paise": paise_of(order, "subtotal_paise", "subtotal") - unsupplied_goods_paise(order)[1]}
                     if unsupplied_goods_paise(order)[1] else {}),
                  "cod_collected_by": user["id"],
                  "cod_collected_by_id": user.get("distributor_id"),
                  "cod_collected_role": "admin",
                  "cod_collection": {**evidence, "expected_paise": expected_p, "collected_paise": collected_p},
                  "cod_collected_at": now_iso(), "paid_at": now_iso(), "updated_at": now_iso(),
                  "completion_due": True}})          # Programme 01 (B-003): durable marker, written with the claim
    from order_completion import complete_paid_order
    if claim.modified_count != 1:
        # A repeated confirmation of a collection that was already claimed finishes an interrupted completion (idempotent).
        if (await db.orders.find_one({"id": order_id}, {"_id": 0, "completion_due": 1}) or {}).get("completion_due"):
            await complete_paid_order(order_id, request, source="cod_collection_retry", notify=False)
        return {"ok": True, "already": True}

    # invoice, vendor sales and the commission plan (refused unless the collection is proven) through the shared step
    done = await complete_paid_order(order_id, request, source="cod_collection", notify=False)
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    result = done.get("commissions")
    await log_audit(user, "cod_collected", "order", order_id,
                    new_value={"amount": order.get("total"), "commissions": result}, request=request)
    await create_notification(order["user_id"], "order", "Order delivered",
                              f"Cash received for order {order['order_number']}. Thank you!",
                              "ऑर्डर डिलीवर हुआ",
                              f"ऑर्डर {order['order_number']} के लिए नकद प्राप्त हुआ। धन्यवाद!")
    return {"ok": True, "commissions": result}


@router.get("/orders")
async def my_orders(user: dict = Depends(get_current_user)):
    await expire_pending_online_orders(limit=50, max_seconds=2)     # B-006: bounded inline; the cron finishes the rest
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

    amount_p = paise_of(order, "total_paise", "total")   # server-side amount, never from client; DEF-05: the exact paise total
    amount = amount_p / 100
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
        "amount": amount, "amount_paise": amount_p, "provider": "stripe",
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
    await db.payment_transactions.update_one({"session_id": body.razorpay_order_id},
        {"$set": {"razorpay_payment_id": body.razorpay_payment_id, "updated_at": now_iso()}})
    if pay.get("status") == "authorized":
        # Batch 14: an authorisation is not money received yet. The order is confirmed by the payment.captured webhook
        # (or the next verify / status check) once the gateway captures it.
        return {"message": "Payment received; we are confirming it with the bank.", "status": "pending_capture",
                "order_id": tx.get("order_id")}
    if pay.get("status") != "captured":
        raise HTTPException(status_code=400, detail="Payment is not captured yet.")
    await _process_paid_order(body.razorpay_order_id, request)
    tx = await db.payment_transactions.find_one({"session_id": body.razorpay_order_id}, {"_id": 0})
    return {"message": "Payment successful", "order_id": tx.get("order_id") if tx else None}


# Razorpay webhooks: payment_events.py (Batch 14 reconciliation: signature, normalised record, match, validate, apply once).
WEBHOOK_STALE_SECONDS = 120


HG_COMMISSION_TYPES = ["COMMISSION_DIRECT", "COMMISSION_REFERRAL", "COMMISSION_TEAM"]


async def _reserve_refund(order_id: str, event: dict):
    """Reserve the refund amount on the order exactly once (keyed by the event id). Returns None on success, or
    "exceeds" / "conflict". Nothing is clawed back until the reservation exists, so a refused reservation moves no money."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if event["id"] in order.get("refund_event_ids", []):
        return None
    total_p = refundable_total_paise(order, paise_of(order, "total_paise", "total"))
    already_p = paise_of(order, "refunded_paise", "refunded_amount")
    new_total_p = already_p + int(event["amount_paise"])
    if new_total_p > total_p or (new_total_p >= total_p) != bool(event["closes_order"]):
        return "exceeds"
    if "refunded_paise" in order:
        refunded_filter = {"refunded_paise": already_p}
    else:   # legacy order: guard on the stored float counter exactly as it was read
        refunded_filter = {"refunded_paise": {"$exists": False}, "refunded_amount": order.get("refunded_amount")}
    claim = await db.orders.update_one(
        {"id": order_id, "refund_event_ids": {"$ne": event["id"]}, **refunded_filter},
        {"$set": {"refunded_paise": new_total_p, "refunded_amount": paise_to_float(new_total_p), "updated_at": now_iso(),
                  "payment_status": "refunded" if event["closes_order"] else "partially_refunded",
                  "financials_reversed": bool(event["closes_order"])},
         "$push": {"refund_event_ids": event["id"]}})
    if claim.modified_count == 1:
        return None
    current = await db.orders.find_one({"id": order_id}, {"_id": 0, "refund_event_ids": 1})
    return None if event["id"] in (current or {}).get("refund_event_ids", []) else "conflict"


async def _reverse_commission(c: dict, event: dict, order: dict) -> int:
    """Claw back one commission's share of one refund event, exactly once. The reversal INTENT is recorded with a
    conditional update on the record as read; a changed record is re-read and recomputed. Then the intent is finished
    (financial_ops). A retry finds the recorded intent and only finishes it. Returns 1 when this commission carries a
    clawback for the event."""
    from commission import snapshot_filter
    from financial_ops import finish_release, finish_reversal
    event_id = event["id"]
    for _ in range(5):
        rec = next((r for r in c.get("reversal_records", []) if r["event_id"] == event_id), None)
        if rec:
            await finish_reversal(c, rec)
            return 1 if rec["claw_paise"] > 0 else 0
        if (c.get("release") or {}).get("applied") is False:
            await finish_release(c)            # complete an interrupted release before reversing it
        credited_p = paise_of(c, "amount_paise", "amount")
        done_p = paise_of(c, "reversed_paise", "reversed_amount")
        room_p = credited_p - done_p
        from cod_rules import refund_basis_paise
        total_p = refund_basis_paise(order, paise_of(order, "total_paise", "total"))   # goods value, without the COD fee (C-11)
        claw_p = min(room_p if event["closes_order"] else mul_ratio(credited_p, int(event["amount_paise"]), total_p), room_p)
        if claw_p <= 0:
            return 0
        new_done_p = done_p + claw_p
        rec = {"op_key": f"clawback:{event_id}:{c['id']}", "event_id": event_id, "claw_paise": claw_p,
               "was_pending": not c.get("released_at"), "applied": False, "order_number": order.get("order_number")}
        claim = await db.commissions.update_one({"id": c["id"], **snapshot_filter(c)}, {"$set": {
            "reversed_paise": new_done_p, "reversed_amount": paise_to_float(new_done_p), "reversed_at": now_iso(),
            "status": "REVERSED" if new_done_p >= credited_p else "PARTIALLY_REVERSED"},
            "$push": {"reversal_records": rec}})
        if claim.modified_count == 1:
            await finish_reversal(c, rec)
            return 1
        c = await db.commissions.find_one({"id": c["id"]}, {"_id": 0})
        if not c or c.get("status") not in ("PENDING", "RELEASED", "PARTIALLY_REVERSED", "REVERSED", "HELD"):
            return 0
    logger.error("commission %s kept changing during refund %s; not completed", c.get("id"), event_id)
    raise RuntimeError("commission changed repeatedly during the refund; retry the refund")


async def reverse_order_financials(order_id: str, actor: dict = None, request: Request = None,
                                   refund_amount: float = None, reference: str = "", reason: str = "",
                                   case_id: str = None, vendor_id: str = None, exact: bool = False):
    """Refund and clawback in EXACT integer paise, crash-safe and idempotent per refund event.

    Steps, in order: (1) the refund EVENT is recorded (keyed by order and reference); (2) the amount is RESERVED on the
    order exactly once; (3) every commission share is clawed back through a recorded intent; (4) vendor shares and open
    refund cases are settled; (5) only then is the event marked completed. A crash at any step is resumed by calling this
    function again with the same reference: completed steps are skipped, and the stored event amount is used, so a retry
    never recomputes the refund.

    Programme 01 (B-002) `exact=True` (refund-case confirmation): the amount is booked exactly or not at all. More than is still
    refundable is REJECTED instead of silently lowered, and a reference whose earlier booking was rejected (nothing was booked)
    may be booked again once - the rejected event is re-claimed atomically, so concurrent retries still book at most once.
    """
    order = await db.orders.find_one({"id": order_id})
    if not order or order.get("payment_status") not in ("paid", "refunded", "partially_refunded"):
        return {"reversed": 0, "refund_amount": 0.0, "rejected": exact, "why": "order_not_refundable"}
    from money_guard import ensure as _money_guard          # Programme 01 (B-004): fail closed without the unique indexes
    await _money_guard("ledger", "wallet")
    event_id = f"{order_id}:refund:{reference or 'full'}"
    event = await db.order_refunds.find_one({"id": event_id}, {"_id": 0})
    if exact and event is not None and event["status"] == "rejected":
        total_p = refundable_total_paise(order, paise_of(order, "total_paise", "total"))
        already_p = paise_of(order, "refunded_paise", "refunded_amount")
        amt_p = to_paise(refund_amount) if refund_amount is not None else total_p - already_p
        if amt_p <= 0 or amt_p > total_p - already_p:
            return {"reversed": 0, "refund_amount": 0.0, "rejected": True, "why": "exceeds_refundable"}
        retried = await db.order_refunds.find_one_and_update(
            {"id": event_id, "status": "rejected"},
            {"$set": {"status": "processing", "amount": paise_to_float(amt_p), "amount_paise": amt_p,
                      "closes_order": already_p + amt_p >= total_p, "case_id": case_id, "vendor_id": vendor_id, "reason": reason,
                      "retried_at": now_iso(), "actor_id": (actor or {}).get("id")}, "$inc": {"attempts": 1}},
            projection={"_id": 0}, return_document=True)
        event = retried or await db.order_refunds.find_one({"id": event_id}, {"_id": 0})
    if event is None:
        total_p = refundable_total_paise(order, paise_of(order, "total_paise", "total"))
        already_p = paise_of(order, "refunded_paise", "refunded_amount")
        remaining_p = total_p - already_p
        amt_p = remaining_p if refund_amount is None else to_paise(refund_amount)
        if amt_p <= 0 or remaining_p <= 0:
            return {"reversed": 0, "refund_amount": 0.0, "rejected": exact, "why": "nothing_refundable"}
        if exact and amt_p > remaining_p:
            return {"reversed": 0, "refund_amount": 0.0, "rejected": True, "why": "exceeds_refundable"}
        amt_p = min(amt_p, remaining_p)
        event = {"_id": event_id, "id": event_id, "order_id": order_id, "amount": paise_to_float(amt_p), "amount_paise": amt_p,
                 "closes_order": already_p + amt_p >= total_p, "reference": reference, "case_id": case_id,
                 "vendor_id": vendor_id, "reason": reason, "status": "processing", "created_at": now_iso(),
                 "actor_id": (actor or {}).get("id")}
        try:
            await db.order_refunds.insert_one(dict(event))
        except DuplicateKeyError:
            event = await db.order_refunds.find_one({"id": event_id}, {"_id": 0})
    if event["status"] == "completed":
        return {"reversed": event.get("clawbacks", 0), "refund_amount": event["amount"], "duplicate": True}
    if event["status"] == "rejected":
        return {"reversed": 0, "refund_amount": 0.0, "rejected": True}
    outcome = await _reserve_refund(order_id, event)
    if outcome == "exceeds":
        await db.order_refunds.update_one({"id": event_id, "status": "processing"}, {"$set": {"status": "rejected"}})
        return {"reversed": 0, "refund_amount": 0.0, "rejected": True}
    if outcome == "conflict":
        return {"reversed": 0, "refund_amount": 0.0, "conflict": True}
    from commission import resume_distribution
    if await db.commission_plans.find_one({"_id": order_id, "completed_at": None}, {"_id": 1}):
        await resume_distribution(order_id)             # no clawback may act on a half-created commission
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    n = 0
    comms = await db.commissions.find({"order_id": order_id, "$or": [
        {"status": {"$in": ["PENDING", "RELEASED", "PARTIALLY_REVERSED", "HELD"]}},     # HELD: legacy manual holds changed the status
        {"reversal_records.event_id": event_id}]}, {"_id": 0}).to_list(1000)
    for c in comms:
        n += await _reverse_commission(c, event, order)
    from ledger import post_refund_shares
    await post_refund_shares(order, event)                 # idempotent per (refund event, vendor)
    if not event.get("case_id"):                           # the one-step Refund action also settles any open refund case
        from returns_routes import confirm_open_cases_for_order
        await confirm_open_cases_for_order(order_id, event, (actor or {}).get("id", "system"))
    done = await db.order_refunds.update_one({"id": event_id, "status": "processing"},
                                             {"$set": {"status": "completed", "clawbacks": n, "completed_at": now_iso()}})
    if done.modified_count == 1:
        await log_audit(actor, "order_financials_reversed", "order", order_id,
                        new_value={"reversed_entries": n, "refund_amount": event["amount"], "reference": reference, "reason": reason}, request=request)
    return {"reversed": n, "refund_amount": event["amount"], "refund_event": event_id}


# The only payment states an online / UPI / admin-recorded payment may turn into "paid". A refunded or partially refunded
# order must never be re-marked paid by a late or repeated payment call, and a COD order is paid only through the COD
# collection route (Phase 3A evidence rules), never by a UPI or manual payment.
PAYABLE_PAYMENT_STATES = ("pending", "claimed")


def is_payable_online(order: dict) -> bool:
    return order.get("payment_method") != "cod" and order.get("payment_status") in PAYABLE_PAYMENT_STATES


MANUAL_SESSION_PREFIXES = ("manual_", "admin_")


async def _flag_unapplied_capture(order: dict, tx: dict, reason: str) -> None:
    """A gateway reported money captured for an order that is already paid by ANOTHER payment (two tabs, card + Razorpay, ...)
    or that can no longer take a payment (refunded, COD). The money is NOT applied to the order; it is recorded once as
    refund-due so finance can return it (FIN-06). Idempotent per payment session."""
    sid = tx["session_id"]
    if sid.startswith(MANUAL_SESSION_PREFIXES):
        return                                      # manual confirmations never capture money by themselves
    entry = {"session_id": sid, "provider": tx.get("provider") or "stripe", "amount": tx.get("amount"),
             "reason": reason, "status": "refund_due", "detected_at": now_iso()}
    r = await db.orders.update_one({"id": order["id"], "duplicate_payments.session_id": {"$ne": sid}},
                                   {"$push": {"duplicate_payments": entry}, "$set": {"has_duplicate_payment": True}})
    await db.payment_transactions.update_one({"session_id": sid}, {"$set": {
        "status": "completed", "payment_status": "paid", "applied_to_order": False, "duplicate_capture": True,
        "refund_status": "refund_due", "updated_at": now_iso()}})
    if r.modified_count:
        logger.warning("payment %s for order %s not applied (%s); flagged refund_due", sid, order["id"], reason)
        await log_audit(None, "payment_duplicate_capture", "order", order["id"],
                        new_value={"session_id": sid, "reason": reason, "amount": tx.get("amount")})


async def _process_paid_order(session_id: str, request: Request = None):
    """Idempotent: mark order paid, generate the invoice and credit pending sale commissions."""
    tx = await db.payment_transactions.find_one({"session_id": session_id})
    if not tx:
        return
    settings = await get_settings()
    # The claim is conditional on BOTH the payment state and the cancellation state this call decided on. A cancellation
    # or expiry landing between the read and the claim makes the claim miss; the order is then read again and handled as
    # a late payment, instead of being overwritten to "processing" after its stock was already returned.
    for _attempt in range(3):
        order = await db.orders.find_one({"id": tx["order_id"]})
        if not order:
            return
        paid_by = order.get("paid_session_id")
        if order.get("payment_status") == "paid":
            if paid_by and paid_by != session_id:
                await _flag_unapplied_capture(order, tx, "order_already_paid")
            elif paid_by == session_id:
                # Programme 01 (B-003): this payment's claim landed earlier. If the process died before finishing, the same
                # payment reported again finishes it (transaction record + completion), idempotently, instead of returning early.
                if tx.get("payment_status") != "paid":
                    await db.payment_transactions.update_one({"session_id": session_id},
                                                             {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}})
                if order.get("completion_due"):
                    from order_completion import complete_paid_order
                    await complete_paid_order(order["id"], request, source=f"retry:{tx.get('provider') or 'gateway'}")
            return  # already processed (the same payment reported again is a no-op)
        if not is_payable_online(order):
            logger.warning("payment for order %s ignored: payment_status=%s method=%s is not payable", order["id"],
                           order.get("payment_status"), order.get("payment_method"))
            if paid_by != session_id:
                await _flag_unapplied_capture(order, tx, f"order_not_payable:{order.get('payment_status')}")
            return  # refunded / partially refunded / COD: a payment call can never re-open or bypass it
        # A payment for an already-cancelled order must never silently re-open it (its stock may have been returned).
        cancelled = order.get("status") == "cancelled"
        revivable = cancelled and order.get("cancel_reason") == EXPIRY_REASON   # expired by the 15-minute rule
        paid_set = {"payment_status": "paid", "paid_at": now_iso(), "updated_at": now_iso(), "paid_session_id": session_id,
                    "completion_due": True}     # B-003: durable "finish me" marker, written atomically with the claim
        if not cancelled:      # the invoice is written atomically with the claim (a lost claim only leaves a numbering gap)
            paid_set.update({"status": "processing", "invoice_number": await next_sequence("invoice", "INV", 6)})
        claim = await db.orders.update_one({"id": order["id"], "payment_status": {"$in": list(PAYABLE_PAYMENT_STATES)},
                                            "payment_method": {"$ne": "cod"},
                                            "status": "cancelled" if cancelled else {"$ne": "cancelled"}}, {"$set": paid_set})
        if claim.modified_count == 1:
            break
    else:
        return  # the order kept changing; a later webhook / verify / status poll finishes it
    await db.payment_transactions.update_one(
        {"session_id": session_id},
        {"$set": {"status": "completed", "payment_status": "paid", "updated_at": now_iso()}},
    )
    from order_completion import complete_paid_order
    source = f"payment:{tx.get('provider') or 'gateway'}"
    if cancelled:
        # Expired order: take the stock back if still available. Admin-cancelled order: flag for refund. Otherwise refund.
        if not await handle_late_payment(order, allow_revive=revivable):
            await complete_paid_order(order["id"], request, source=source)   # clears the marker: a refund is owed, nothing earns
            return  # no commission / no invoice for an order that cannot be fulfilled
        # the revived order gets its invoice inside the shared completion (only when missing)

    # Programme 01 (B-003): vendor sales, the invoice, the HomeGenie commission plan (30% direct / 10% referral / 5% team,
    # credited as PENDING and released after the return window by the points cron) and the one-time notifications are all
    # done by ONE idempotent step shared by every payment path; a crash here is finished by a retry or the repair sweep.
    await complete_paid_order(order["id"], request, source=source)


# Positional TEAM SALES commission matrix (FINAL, locked). Position 1 = buyer's IMMEDIATE sponsor.
# S = product subtotal EXCLUDING GST. Company direct share = 30% of S. Commission POOL = 70% of S.
# Position rates apply to the POOL (45% of pool paid out; the other 55% of pool stays with company).
# GD 0 | BD 15 | AD 5 | CD 5 | PD 5 | MD 5 | RD 4 | DD 3 | MDD 3  =>  45% of pool
@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str, request: Request):
    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found.")
    # Programme 03 / DEF-05: only a Stripe attempt is checked here, and only Stripe's own record of the session (amount, currency,
    # order) can complete the order - `payment_status: "paid"` alone, or the redirect, never does (payment_events.stripe_checkout_paid).
    if tx.get("payment_status") != "paid" and (tx.get("provider") or "stripe") == "stripe" \
            and not tx["session_id"].startswith(MANUAL_SESSION_PREFIXES):
        try:
            from payment_events import stripe_checkout_paid
            sc = _stripe(request)
            await stripe_checkout_paid(session_id, sc.get_checkout_status, request)
            tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
        except HTTPException:
            pass                                        # card checkout not configured / money protection not ready: stays pending
        except Exception as e:
            logger.error("payment status check for %s failed (%s); it stays pending and is retried", session_id, type(e).__name__)
    return {"session_id": tx["session_id"], "status": tx["status"],
            "payment_status": tx["payment_status"], "order_id": tx.get("order_id")}


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Programme 03 / DEF-05: verified (signature, by the Stripe SDK), recorded once in `webhook_events`, then validated against
    Stripe's own record of the session before anything changes (payment_events.apply_stripe)."""
    from payment_events import apply_stripe, claim, stripe_event, _finish
    body = await request.body()
    sig = request.headers.get("Stripe-Signature", "")
    try:
        sc = _stripe(request)
        resp = await sc.handle_webhook(body, sig)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("stripe webhook refused (%s)", type(e).__name__)
        raise HTTPException(status_code=400, detail="Invalid webhook")
    if not getattr(resp, "event_id", None) or not getattr(resp, "event_type", None):
        raise HTTPException(status_code=400, detail="Invalid payload")
    ev = stripe_event(resp.event_id, resp.event_type, getattr(resp, "session_id", None))
    if not await claim(ev, provider="stripe"):
        return {"status": "duplicate"}
    try:
        out = await apply_stripe(ev, sc.get_checkout_status, request)
    except Exception as e:                                       # recorded; Stripe (or finance) retries it
        await _finish(ev["event_id"], "failed", f"{type(e).__name__}: {str(e)[:200]}")
        raise HTTPException(status_code=500, detail="Event could not be processed; it will be retried.")
    return {"status": out["status"]}


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
    if not is_payable_online(order):
        raise HTTPException(status_code=409, detail="This order cannot take a UPI payment (cash on delivery, or already refunded).")
    claimed = await db.orders.update_one({"id": order["id"], "payment_status": {"$in": list(PAYABLE_PAYMENT_STATES)},
                                          "payment_method": {"$ne": "cod"}}, {"$set": {
        "payment_method": "upi_manual", "payment_status": "claimed", "claimed_at": now_iso(),
        "upi_reference": body.reference, "updated_at": now_iso()}})
    if claimed.modified_count != 1:
        raise HTTPException(status_code=409, detail="This order changed just now. Please refresh.")
    await log_audit(user, "upi_payment_claimed", "order", order["id"],
                    new_value={"reference": body.reference}, request=request)
    return {"message": "Payment submitted. Our team will verify it shortly.", "order_id": order["id"]}


FINANCE_CONFIRM_ROLES = ("super_admin", "accounts_admin")


async def require_finance_admin(admin: dict = Depends(require_admin)) -> dict:
    """Decision 4: confirming, recording or rejecting a manual / UPI payment is a finance action."""
    if admin.get("role") not in FINANCE_CONFIRM_ROLES:
        raise HTTPException(status_code=403, detail="Only a finance administrator can confirm or reject payments.")
    return admin


class ManualPayBody(BaseModel):
    distributor_id: str
    reference: str
    amount: float = Field(gt=0)        # the amount actually received; must equal the order total exactly (FIN-01)
    note: str = ""


def _norm_reference(ref: str) -> str:
    return re.sub(r"\s+", "", ref or "").upper()


def _order_total_paise(order: dict) -> int:
    return int(order["total_paise"]) if order.get("total_paise") is not None else to_paise(order.get("total") or 0)


def _check_amount(order: dict, amount) -> None:
    if to_paise(amount) != _order_total_paise(order):
        raise HTTPException(status_code=400, detail=f"The amount received must equal the order total of ₹{paise_to_float(_order_total_paise(order)):.2f}.")


async def _reserve_payment_reference(ref: str, order: dict, admin: dict, provider: str) -> str:
    """One bank/UPI reference can confirm ONE order only (FIN-01). The reference is the document _id, so uniqueness holds
    without any extra index. Re-confirming the same order with the same reference is idempotent."""
    key = _norm_reference(ref)
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9/_.-]{5,39}", key):
        raise HTTPException(status_code=400, detail="Enter the bank / UPI reference (UTR or transaction id, 6 to 40 letters or digits).")
    try:
        await db.payment_references.insert_one({"_id": key, "order_id": order["id"], "provider": provider,
                                                "recorded_by": admin["id"], "created_at": now_iso()})
    except DuplicateKeyError:
        used = await db.payment_references.find_one({"_id": key})
        if (used or {}).get("order_id") != order["id"]:
            raise HTTPException(status_code=409, detail="This payment reference was already used to confirm another order.")
    return key


@router.post("/admin/payments/manual")
async def manual_payment_by_distributor(body: ManualPayBody, request: Request, admin: dict = Depends(require_finance_admin)):
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
    order = await db.orders.find_one({"user_id": user["id"], "payment_status": {"$in": list(PAYABLE_PAYMENT_STATES)},
                                      "payment_method": {"$ne": "cod"}}, sort=[("created_at", -1)])
    if not order:
        raise HTTPException(status_code=404, detail="This member has no pending order to mark as paid.")
    if order.get("payment_status") == "paid":
        return {"message": "This member's latest order is already paid.", "order_id": order["id"]}
    _check_amount(order, body.amount)
    ref = await _reserve_payment_reference(ref, order, admin, "admin_manual")
    prev = order.get("payment_status")
    sid = f"admin_{order['id']}"
    if not await db.payment_transactions.find_one({"session_id": sid}):
        await db.payment_transactions.insert_one({
            "id": new_id(), "session_id": sid, "order_id": order["id"], "user_id": user["id"],
            "amount": float(order["total"]), "amount_received": float(body.amount), "currency": order.get("currency", "INR"),
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
    amount: float = Field(gt=0)        # the amount seen in the bank statement; must equal the order total exactly (FIN-01)


@router.put("/admin/payments/upi-confirm/{order_id}")
async def upi_confirm(order_id: str, body: UpiConfirm, request: Request, admin: dict = Depends(require_finance_admin)):
    ref = (body.reference or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="Payment reference ID (UTR / txn id) is required.")
    order = await db.orders.find_one({"id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.get("payment_status") == "paid":
        return {"message": "Order already paid."}
    if not is_payable_online(order):
        raise HTTPException(status_code=409, detail="This order cannot be confirmed as paid here (cash on delivery, or already refunded).")
    _check_amount(order, body.amount)
    ref = await _reserve_payment_reference(ref, order, admin, "upi_manual")
    await db.orders.update_one({"id": order_id}, {"$set": {
        "payment_reference": ref, "upi_reference": ref, "updated_at": now_iso()}})
    sid = f"manual_{order_id}"
    if not await db.payment_transactions.find_one({"session_id": sid}):
        await db.payment_transactions.insert_one({
            "id": new_id(), "session_id": sid, "order_id": order_id, "user_id": order["user_id"],
            "amount": order["total"], "amount_received": float(body.amount), "currency": order.get("currency", "INR"),
            "reference": ref, "provider": "upi_manual", "recorded_by": admin["id"],
            "status": "manual", "payment_status": "paid", "created_at": now_iso(), "updated_at": now_iso()})
    await _process_paid_order(sid, request)  # idempotent: invoice + pending commissions
    if (await db.orders.find_one({"id": order_id}, {"_id": 0, "payment_status": 1}) or {}).get("payment_status") != "paid":
        # the claim expired (or the order changed) while this confirmation ran: nothing was marked paid
        raise HTTPException(status_code=409, detail="This order could not be confirmed: its UPI claim expired or the order changed. "
                                                    "If the money was received, refund it to the customer.")
    await log_audit(admin, "upi_payment_confirmed", "order", order_id,
                    new_value={"reference": ref, "amount": float(body.amount)}, request=request)
    return {"message": "Payment confirmed.", "reference": ref}


# ---------------- Duplicate captures (FIN-06): listing and recording their refunds ----------------
@router.get("/admin/payments/duplicates")
async def list_duplicate_payments(status: str = "refund_due", admin: dict = Depends(require_finance_admin)):
    rows = await db.orders.find({"duplicate_payments.status": status}, {"_id": 0, "id": 1, "order_number": 1, "user_id": 1,
                                                                        "duplicate_payments": 1}).sort("updated_at", -1).to_list(500)
    return {"items": [{"order_id": o["id"], "order_number": o.get("order_number"), **d}
                      for o in rows for d in o.get("duplicate_payments", []) if d.get("status") == status]}


class DuplicateRefundIn(BaseModel):
    session_id: str
    reference: str = Field(min_length=6, max_length=60)
    note: str = Field(default="", max_length=300)


@router.post("/admin/payments/duplicates/{order_id}/refunded")
async def mark_duplicate_refunded(order_id: str, body: DuplicateRefundIn, request: Request, admin: dict = Depends(require_finance_admin)):
    """Records that the extra captured payment was returned to the customer through the gateway. Lifts the payout hold."""
    r = await db.orders.update_one(
        {"id": order_id, "duplicate_payments": {"$elemMatch": {"session_id": body.session_id, "status": "refund_due"}}},
        {"$set": {"duplicate_payments.$.status": "refunded", "duplicate_payments.$.refund_reference": body.reference.strip(),
                  "duplicate_payments.$.refunded_by": admin["id"], "duplicate_payments.$.refunded_at": now_iso()}})
    if not r.modified_count:
        raise HTTPException(status_code=409, detail="No refund-due duplicate payment with this session on this order.")
    await db.payment_transactions.update_one({"session_id": body.session_id}, {"$set": {"refund_status": "refunded"}})
    await log_audit(admin, "duplicate_payment_refunded", "order", order_id,
                    new_value={"session_id": body.session_id, "reference": body.reference.strip(), "note": body.note.strip()}, request=request)
    return {"ok": True}


class UpiReject(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


@router.put("/admin/payments/upi-reject/{order_id}")
async def upi_reject(order_id: str, body: UpiReject, request: Request, admin: dict = Depends(require_finance_admin)):
    """FIN-08: the admin could not find the customer's UPI payment. The claim is withdrawn and the order goes back to an
    ordinary unpaid online order, so the normal unpaid-order expiry releases its stock (or the customer pays properly).
    Nothing is deleted; the rejected claim stays on the order for the record."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.get("payment_status") != "claimed":
        raise HTTPException(status_code=409, detail="Only a submitted (unverified) UPI payment can be rejected.")
    entry = {"reference": order.get("upi_reference"), "reason": body.reason.strip(), "rejected_by": admin["id"], "rejected_at": now_iso()}
    r = await db.orders.update_one({"id": order_id, "payment_status": "claimed"},
                                   {"$set": {"payment_status": "pending", "payment_method": "online", "upi_reference": None,
                                             "updated_at": now_iso()},
                                    "$push": {"rejected_upi_claims": entry}})
    if not r.modified_count:
        raise HTTPException(status_code=409, detail="This order changed just now. Please refresh.")
    await create_notification(order["user_id"], "payment", "UPI payment not found",
                              f"We could not verify your UPI payment for order {order.get('order_number')}: {body.reason.strip()}. "
                              "Please pay again or contact support.")
    await log_audit(admin, "upi_payment_rejected", "order", order_id, new_value=entry, request=request)
    return {"ok": True, "payment_status": "pending"}
