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

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logger = logging.getLogger("homegenies")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(
    mongo_url,
    serverSelectionTimeoutMS=8000,
    connectTimeoutMS=8000,
    retryWrites=True,
)
db = client[os.environ["DB_NAME"]]

JWT_SECRET = os.environ.get("JWT_SECRET")
if not JWT_SECRET or JWT_SECRET == "change-me":
    raise RuntimeError("JWT_SECRET is not configured. Set a strong JWT_SECRET in the environment.")
JWT_ALGO = "HS256"

ADMIN_ROLES = {"super_admin", "admin", "accounts_admin", "support_admin"}


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
    payload = {
        "sub": user_id,
        "type": "access",
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
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
    user.pop("password_hash", None)
    return user


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


# ---------- wallet ledger ----------
async def get_or_create_wallet(user_id: str) -> dict:
    w = await db.wallets.find_one({"user_id": user_id}, {"_id": 0})
    if not w:
        w = {
            "id": new_id(),
            "user_id": user_id,
            "available_balance": 0.0,
            "pending_balance": 0.0,
            "total_earned": 0.0,
            "total_withdrawn": 0.0,
            "active": True,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.wallets.insert_one(dict(w))
    return w


async def add_wallet_transaction(user_id: str, txn_type: str, amount: float, status: str,
                                 reference: str = "", description: str = "", direction: str = "credit"):
    """Immutable ledger entry + safe aggregate update."""
    await get_or_create_wallet(user_id)
    txn = {
        "id": new_id(),
        "user_id": user_id,
        "type": txn_type,
        "direction": direction,  # credit / debit
        "amount": float(amount),
        "status": status,  # CREDITED / DEBITED / PENDING / REVERSED
        "reference": reference,
        "description": description,
        "created_at": now_iso(),
    }
    await db.wallet_transactions.insert_one(dict(txn))

    inc = {}
    if status == "CREDITED" and direction == "credit":
        inc = {"available_balance": amount, "total_earned": amount}
    elif status == "PENDING":
        inc = {"pending_balance": amount}
    elif status == "DEBITED" and direction == "debit":
        inc = {"available_balance": -amount, "total_withdrawn": amount}
    elif status == "CLAWBACK" and direction == "debit":
        # refund/reversal of a previously credited commission
        inc = {"available_balance": -amount, "total_earned": -amount}
    if inc:
        await db.wallets.update_one({"user_id": user_id},
                                    {"$inc": inc, "$set": {"updated_at": now_iso()}})
    txn.pop("_id", None)
    return txn


def money2(v) -> float:
    """Round to 2 decimals for money/points."""
    return round(float(v) + 1e-9, 2)


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
