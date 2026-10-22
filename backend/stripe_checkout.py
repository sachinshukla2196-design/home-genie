"""Stripe Checkout via the official `stripe` SDK.

Drop-in for the three calls shop_routes uses from Emergent's private `emergentintegrations` package
(only installable inside Emergent's own image). Used when that package is absent, e.g. on Vercel.

Configuration (environment):
  STRIPE_API_KEY         secret key from the Stripe dashboard (sk_live_… / sk_test_…). Required.
  STRIPE_WEBHOOK_SECRET  signing secret of the /api/webhook/stripe endpoint (whsec_…). Without it,
                         webhooks are rejected; payments are still confirmed via /api/payments/status.
"""
import asyncio
import os
from dataclasses import dataclass, field
from typing import Optional

import stripe

# Emergent's placeholder key only works through Emergent's proxy; it is not a real Stripe key.
_PLACEHOLDER_KEYS = {"", "sk_test_emergent"}


def configured(api_key: Optional[str]) -> bool:
    return (api_key or "").strip() not in _PLACEHOLDER_KEYS


@dataclass
class CheckoutSessionRequest:
    amount: float                 # major units (e.g. rupees); converted to the smallest unit for Stripe
    currency: str
    success_url: str
    cancel_url: str
    metadata: dict = field(default_factory=dict)


@dataclass
class CheckoutSessionResponse:
    url: str
    session_id: str


@dataclass
class CheckoutStatusResponse:
    status: str                   # open | complete | expired
    payment_status: str           # paid | unpaid | no_payment_required
    amount_total: int
    currency: str
    metadata: dict


@dataclass
class WebhookResponse:
    event_type: str
    event_id: str
    session_id: Optional[str]
    payment_status: Optional[str]
    metadata: dict


class StripeCheckout:
    def __init__(self, api_key: str, webhook_url: str = "", webhook_secret: Optional[str] = None):
        if not configured(api_key):
            raise RuntimeError("STRIPE_API_KEY is not configured.")
        self.api_key = api_key.strip()
        self.webhook_url = webhook_url
        self.webhook_secret = (webhook_secret if webhook_secret is not None
                               else os.environ.get("STRIPE_WEBHOOK_SECRET", "")).strip()

    async def create_checkout_session(self, req: CheckoutSessionRequest) -> CheckoutSessionResponse:
        unit_amount = int(round(float(req.amount) * 100))
        if unit_amount <= 0:
            raise ValueError("Amount must be positive.")

        def _create():
            return stripe.checkout.Session.create(
                api_key=self.api_key,
                mode="payment",
                line_items=[{
                    "quantity": 1,
                    "price_data": {"currency": req.currency.lower(), "unit_amount": unit_amount,
                                   "product_data": {"name": "HOME GENIES order"}},
                }],
                success_url=req.success_url,
                cancel_url=req.cancel_url,
                metadata={k: str(v) for k, v in (req.metadata or {}).items()},
            )

        s = await asyncio.to_thread(_create)
        return CheckoutSessionResponse(url=s["url"], session_id=s["id"])

    async def get_checkout_status(self, session_id: str) -> CheckoutStatusResponse:
        s = await asyncio.to_thread(stripe.checkout.Session.retrieve, session_id, api_key=self.api_key)
        return CheckoutStatusResponse(status=s["status"], payment_status=s["payment_status"],
                                      amount_total=s.get("amount_total") or 0, currency=s.get("currency") or "",
                                      metadata=dict(s.get("metadata") or {}))

    async def handle_webhook(self, body: bytes, signature: str) -> WebhookResponse:
        if not self.webhook_secret:
            raise RuntimeError("STRIPE_WEBHOOK_SECRET is not configured; refusing unverified webhook.")
        # Raises stripe.SignatureVerificationError on a bad/missing signature or a stale timestamp.
        event = stripe.Webhook.construct_event(body, signature, self.webhook_secret)
        obj = event["data"]["object"]
        is_session = event["type"].startswith("checkout.session.")
        return WebhookResponse(event_type=event["type"], event_id=event["id"],
                               session_id=obj.get("id") if is_session else None,
                               payment_status=obj.get("payment_status") if is_session else None,
                               metadata=dict(obj.get("metadata") or {}))
