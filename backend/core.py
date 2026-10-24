"""Shared core: db, auth, helpers for the HOME GENIES platform."""
import os
import uuid
import jwt
import bcrypt
import httpx
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional
from dotenv import load_dotenv
from fastapi import Depends, Request, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from money import to_paise, paise_to_float

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger("homegenies")

# Missing configuration must not crash the import (Vercel would then only report an opaque
# FUNCTION_INVOCATION_FAILED). It is recorded here and server.py answers every request with a 503 that names
# the missing variables (names only, never values) until it is fixed.
CONFIG_PROBLEMS = [n for n in ("MONGO_URL", "DB_NAME") if not os.environ.get(n)]
mongo_url = os.environ.get("MONGO_URL") or "mongodb://localhost:27017"
def _make_client(url):
    return AsyncIOMotorClient(url, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000, retryWrites=True)


try:
    client = _make_client(mongo_url)
except Exception as _e:  # mongodb+srv:// resolves DNS eagerly: a wrong cluster host raises here, at import
    logger.error("MONGO_URL is not usable (%s); serving 503 until it is corrected", type(_e).__name__)
    CONFIG_PROBLEMS.append("MONGO_URL_INVALID (e.g. the cluster host does not resolve; copy the exact connection string from Atlas > Connect > Drivers)")
    client = _make_client("mongodb://localhost:27017")  # placeholder; never used while CONFIG_PROBLEMS is non-empty
db = client[os.environ.get("DB_NAME") or "homegenies_unconfigured"]

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET or JWT_SECRET == "change-me":
    CONFIG_PROBLEMS.append("JWT_SECRET")
    JWT_SECRET = uuid.uuid4().hex  # throwaway; every request is refused while JWT_SECRET is unset
JWT_ALGO = "HS256"

ADMIN_ROLES = {"super_admin", "admin", "accounts_admin", "support_admin"}
# Projection for product documents returned to clients: hides the internal stock idempotency markers (stock.py).
P_PUBLIC = {"_id": 0, "stock_ops": 0}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def mask_aadhaar(a: str) -> str:
    a = str(a or "").strip()
    if len(a) < 4:
        return ""
    return "XXXX-XXXX-" + a[-4:]


# ---------- passwords ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ---------- jwt ----------
def create_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,  # lets a password change revoke sessions issued before it
        "exp": now + timedelta(days=7),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def _decode(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])


def clean_user(user: dict) -> dict:
    if not user:
        return user
    user = dict(user)
    user.pop("_id", None)
    user.pop("password_hash", None)
    if user.get("aadhaar_number"):
        user["aadhaar_masked"] = mask_aadhaar(user["aadhaar_number"])
        user.pop("aadhaar_number", None)
    return user


async def get_current_user(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = _decode(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid session. Please log in again.")
    user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    if _issued_before_password_change(payload, user):
        raise HTTPException(status_code=401, detail="Your password was changed. Please log in again.")
    user.pop("password_hash", None)
    return user


def _issued_before_password_change(payload: dict, user: dict) -> bool:
    """True for tokens issued before the user's last password change (or legacy tokens without iat)."""
    changed = user.get("password_changed_at")
    if not changed:
        return False
    try:
        changed_ts = int(datetime.fromisoformat(changed).timestamp())
    except ValueError:
        return False
    return int(payload.get("iat") or 0) < changed_ts


def password_update(new_password: str) -> dict:
    """$set fields for a password change: bcrypt hash + timestamp that revokes older sessions."""
    return {"password_hash": hash_password(new_password), "password_changed_at": now_iso()}


def require_roles(*roles):
    async def dep(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(status_code=403, detail="You do not have access to this resource.")
        return user
    return dep


async def require_admin(user: dict = Depends(get_current_user)):
    if user.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


# ---------- sequences ----------
async def next_distributor_id() -> str:
    doc = await db.counters.find_one_and_update(
        {"id": "distributor"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    seq = doc["seq"]
    return f"HG{seq:06d}"


async def next_sequence(name: str, prefix: str, width: int = 6) -> str:
    doc = await db.counters.find_one_and_update(
        {"id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return f"{prefix}{doc['seq']:0{width}d}"


# ---------- business settings ----------
DEFAULT_SETTINGS = {
    "id": "business_settings",
    # HOME GENIES commission plan (percent of product price, before GST)
    "commission_direct_pct": 30.0,
    "commission_referral_pct": 10.0,
    "commission_team_pct": 5.0,
    # HomeGenie Points
    "return_window_days": 7,
    "point_value": 1.0,
    "points_withdrawal_enabled": True,
    # Cash on delivery
    "cod_enabled": True,
    "cod_fee": 49.0,
    # Monthly HomeGenie badges (sales value, before GST, in the current month)
    "badge_t1_name": "Bronze", "badge_t1_sales": 10000.0,
    "badge_t2_name": "Silver", "badge_t2_sales": 25000.0,
    "badge_t3_name": "Gold", "badge_t3_sales": 50000.0,
    "badge_t4_name": "Diamond", "badge_t4_sales": 100000.0,
    "require_kyc_for_withdrawal": True,
    "gst_percent": 5.0,
    "currency": "INR",
    "currency_symbol": "₹",
    "company_name": "HOME GENIES",
    "company_email": "",
    "company_phone": "",
    "company_address": "",
}


async def get_settings() -> dict:
    s = await db.business_settings.find_one({"id": "business_settings"}, {"_id": 0})
    if not s:
        await db.business_settings.insert_one(dict(DEFAULT_SETTINGS))
        return dict(DEFAULT_SETTINGS)
    return s


# ---------- wallet ledger (exact money) ----------
# Balances are kept in INTEGER PAISE (`<field>_paise`); the legacy rupee float fields are still maintained for old readers
# but every value returned by get_or_create_wallet is derived from paise, never from the float counters.
WALLET_FIELDS = ("available_balance", "pending_balance", "total_earned", "total_withdrawn")


def _wallet_view(w: dict) -> dict:
    w = dict(w)
    for f in WALLET_FIELDS:
        if isinstance(w.get(f + "_paise"), int):
            w[f] = paise_to_float(w[f + "_paise"])
    return w


async def get_or_create_wallet(user_id: str) -> dict:
    w = await db.wallets.find_one({"user_id": user_id}, {"_id": 0})
    if not w:
        w = {"id": new_id(), "user_id": user_id, "active": True, "created_at": now_iso(), "updated_at": now_iso()}
        for f in WALLET_FIELDS:
            w[f] = 0.0
            w[f + "_paise"] = 0
        try:
            await db.wallets.insert_one(dict(w))
        except Exception:   # concurrent creation
            w = await db.wallets.find_one({"user_id": user_id}, {"_id": 0})
    elif any(not isinstance(w.get(f + "_paise"), int) for f in WALLET_FIELDS):
        # Lazy, non-destructive upgrade of a pre-paise wallet: ADD the exact fields from the stored rupee values once.
        # The original float fields are left exactly as they were (history is never rewritten).
        for f in WALLET_FIELDS:
            if not isinstance(w.get(f + "_paise"), int):
                await db.wallets.update_one({"user_id": user_id, f + "_paise": {"$exists": False}},
                                            {"$set": {f + "_paise": to_paise(w.get(f) or 0)}})
        w = await db.wallets.find_one({"user_id": user_id}, {"_id": 0})
    return _wallet_view(w)


async def wallet_apply(user_id: str, deltas: dict, require_available: int = None) -> bool:
    """THE only place wallet balances change. `deltas` maps a balance field to a signed amount in PAISE. One atomic update
    moves the exact paise counter and the legacy float counter together. With `require_available` the update only
    happens if available_balance >= that many paise (atomic conditional debit). Returns whether it was applied."""
    await get_or_create_wallet(user_id)
    inc = {}
    for f, d in deltas.items():
        assert f in WALLET_FIELDS, f
        inc[f + "_paise"] = int(d)
        inc[f] = paise_to_float(int(d))
    flt = {"user_id": user_id}
    if require_available is not None:
        flt["available_balance_paise"] = {"$gte": int(require_available)}
    res = await db.wallets.update_one(flt, {"$inc": inc, "$set": {"updated_at": now_iso()}})
    return res.modified_count == 1


async def add_wallet_transaction(user_id: str, txn_type: str, amount: float, status: str,
                                 reference: str = "", description: str = "", direction: str = "credit"):
    """Immutable ledger entry + exact aggregate update (amount is rupees; stored and applied as integer paise)."""
    await get_or_create_wallet(user_id)
    paise = to_paise(amount)
    txn = {
        "id": new_id(),
        "user_id": user_id,
        "type": txn_type,
        "direction": direction,  # credit / debit
        "amount": paise_to_float(paise),
        "amount_paise": paise,
        "status": status,  # CREDITED / DEBITED / PENDING / REVERSED
        "reference": reference,
        "description": description,
        "created_at": now_iso(),
    }
    await db.wallet_transactions.insert_one(dict(txn))

    deltas = {}
    if status == "CREDITED" and direction == "credit":
        deltas = {"available_balance": paise, "total_earned": paise}
    elif status == "PENDING":
        deltas = {"pending_balance": paise}
    elif status == "DEBITED" and direction == "debit":
        deltas = {"available_balance": -paise, "total_withdrawn": paise}
    elif status == "CLAWBACK" and direction == "debit":
        # refund/reversal of a previously credited commission
        deltas = {"available_balance": -paise, "total_earned": -paise}
    if deltas:
        await wallet_apply(user_id, deltas)
    txn.pop("_id", None)
    return txn


def money2(v) -> float:
    """Round to 2 decimals for money/points (exact half-up via Decimal; legacy helper, prefer money.to_paise)."""
    return paise_to_float(to_paise(v))


# ---------- notifications ----------
async def create_notification(user_id: str, ntype: str, title: str, message: str,
                              title_hi: str = "", message_hi: str = "", meta: dict = None):
    n = {
        "id": new_id(),
        "user_id": user_id,
        "type": ntype,
        "title": title,
        "title_hi": title_hi or title,
        "message": message,
        "message_hi": message_hi or message,
        "meta": meta or {},
        "read": False,
        "created_at": now_iso(),
    }
    await db.notifications.insert_one(dict(n))
    return n


# ---------- audit ----------
async def log_audit(user: Optional[dict], action: str, entity: str, entity_id: str = "",
                    old_value=None, new_value=None, request: Request = None):
    ip = ""
    if request:
        ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "")
    rec = {
        "id": new_id(),
        "user_id": user.get("id") if user else None,
        "user_email": user.get("email") if user else None,
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "old_value": old_value,
        "new_value": new_value,
        "ip": ip,
        "created_at": now_iso(),
    }
    await db.audit_logs.insert_one(dict(rec))


# ---------- email (Emergent managed Resend) ----------
EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "HOME GENIES")


async def send_email(to: str, subject: str, html: str) -> bool:
    if not EMAIL_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
                json={"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME},
            )
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"email send failed: {e}")
        return False


def email_shell(title: str, body_html: str) -> str:
    return f"""
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F7F9F7;padding:32px 0;font-family:Arial,Helvetica,sans-serif;">
  <tr><td align="center">
    <table width="480" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #EAF5ED;border-radius:16px;overflow:hidden;">
      <tr><td style="background:#0B4D2E;padding:22px 28px;">
        <span style="color:#FBF3DA;font-size:18px;font-weight:bold;">HOME <span style="color:#C9A227;">GENIES</span></span>
        <div style="color:rgba(255,255,255,0.6);font-size:10px;letter-spacing:2px;">AYURVEDA INDIA LLP</div>
      </td></tr>
      <tr><td style="padding:32px 28px;">
        <h2 style="color:#17201B;margin:0 0 12px;font-size:20px;">{title}</h2>
        {body_html}
      </td></tr>
      <tr><td style="padding:18px 28px;background:#EAF5ED;color:#66736B;font-size:12px;">
        © HOME GENIES
      </td></tr>
    </table>
  </td></tr>
</table>"""


# ---------- rate limiting (shared by every sensitive endpoint) ----------
import os as _os
import time as _time
from datetime import datetime as _dt, timedelta as _td, timezone as _tz

RATE_LIMIT_SCALE = float(_os.environ.get("RATE_LIMIT_SCALE", "1"))
RATE_LIMITS = {   # name -> (max requests, window seconds); keys are per client IP (or per vendor for authenticated actions)
    "vendor_register": (10, 3600), "customer_register": (20, 3600), "forgot_password": (10, 3600),
    "login_ip": (60, 600), "admin_login_ip": (20, 600), "support_ticket": (20, 86400), "upload_sign": (60, 3600),
    "change_password": (10, 3600), "csv_import": (30, 3600),
}


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")) or "unknown"


async def rate_limit(name: str, key: str):
    """Fixed-window limiter backed by MongoDB (works across serverless instances). Raises 429 with Retry-After."""
    limit, window = RATE_LIMITS[name]
    limit = max(int(limit * RATE_LIMIT_SCALE), 1)
    start = int(_time.time() // window) * window
    flt = {"key": f"{name}:{key}", "w": start}
    upd = {"$inc": {"n": 1}, "$setOnInsert": {"expires_at": _dt.fromtimestamp(start + window + 60, _tz.utc)}}
    for attempt in (1, 2):
        try:
            doc = await db.rate_limits.find_one_and_update(flt, upd, upsert=True, return_document=True)
            break
        except Exception:                      # concurrent first insert on the unique index: retry once
            if attempt == 2:
                raise
    if doc["n"] > limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.",
                            headers={"Retry-After": str(max(start + window - int(_time.time()), 1))})


async def notify_order_vendors(order: dict, title: str, message: str):
    """Tell every vendor on an order (once per order+title) that something needs their attention."""
    for f in order.get("fulfilments", []):
        v = await db.vendors.find_one({"id": f["vendor_id"]}, {"_id": 0, "user_id": 1})
        if not v:
            continue
        key = f"{order['id']}:{title}"
        if await db.notifications.find_one({"user_id": v["user_id"], "meta.dedupe": key}, {"_id": 1}):
            continue
        await create_notification(v["user_id"], "order", title, message, meta={"order_id": order["id"], "dedupe": key})
