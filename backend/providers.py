"""Production OTP: server-generated secure OTP, delivered ONLY via a real SMS
provider (MSG91). No mock, no test OTP, no dev OTP, no OTP in API responses or
logs. If the SMS provider is not configured, OTP flows FAIL SAFELY (503)."""
import os
import re
import hmac
import hashlib
import secrets
import logging
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from core import db, now_iso

logger = logging.getLogger("anjali")

OTP_TTL = int(os.environ.get("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_COOLDOWN = int(os.environ.get("OTP_RESEND_COOLDOWN", "60"))
OTP_PEPPER = os.environ.get("OTP_PEPPER", "")

MSG91_AUTH_KEY = os.environ.get("MSG91_AUTH_KEY", "")
MSG91_SENDER_ID = os.environ.get("MSG91_SENDER_ID", "")
MSG91_TEMPLATE_ID = os.environ.get("MSG91_TEMPLATE_ID", "")
MSG91_BASE_URL = os.environ.get("MSG91_BASE_URL", "https://control.msg91.com")


def sms_configured() -> bool:
    return bool(MSG91_AUTH_KEY and MSG91_SENDER_ID and MSG91_TEMPLATE_ID)


def _normalize_mobile(m: str) -> str:
    p = re.sub(r"\D", "", (m or ""))
    if len(p) == 10:
        p = "91" + p
    return p


def _hash(code: str) -> str:
    return hmac.new(OTP_PEPPER.encode(), (code or "").strip().encode(), hashlib.sha256).hexdigest()


async def _send_sms_otp(mobile: str, code: str) -> None:
    """Deliver OTP via MSG91 Flow API. Never logs the code or provider secrets."""
    if not sms_configured():
        raise HTTPException(status_code=503, detail="OTP service is not configured. Please contact support.")
    payload = {
        "flow_id": MSG91_TEMPLATE_ID,
        "sender": MSG91_SENDER_ID,
        "recipients": [{"mobiles": _normalize_mobile(mobile), "OTP": code}],
    }
    url = MSG91_BASE_URL.rstrip("/") + "/api/v5/flow/"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(url, json=payload,
                                     headers={"authkey": MSG91_AUTH_KEY, "Content-Type": "application/json"})
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(status_code=503, detail="Could not send OTP right now. Please try again shortly.")
    if resp.status_code >= 400 or str(data.get("type")) != "success":
        logger.error("MSG91 send rejected (status=%s)", resp.status_code)
        raise HTTPException(status_code=503, detail="Could not send OTP right now. Please try again shortly.")


async def otp_create(identifier: str, purpose: str) -> dict:
    """Generate + store a hashed single-use OTP and deliver it via SMS. Returns NO code."""
    if not sms_configured():
        raise HTTPException(status_code=503, detail="OTP service is not configured. Please contact support.")
    last = await db.otp_sessions.find_one({"identifier": identifier, "purpose": purpose}, sort=[("created_at", -1)])
    if last:
        try:
            if (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds() < OTP_RESEND_COOLDOWN:
                raise HTTPException(status_code=429, detail="Please wait a few seconds before requesting another OTP.")
        except HTTPException:
            raise
        except Exception:
            pass
    code = f"{secrets.randbelow(1000000):06d}"
    await db.otp_sessions.update_many(
        {"identifier": identifier, "purpose": purpose, "used": False},
        {"$set": {"used": True}})
    await db.otp_sessions.insert_one({
        "identifier": identifier, "purpose": purpose, "code_hash": _hash(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=OTP_TTL)).isoformat(),
        "attempts": 0, "used": False, "created_at": now_iso(),
    })
    try:
        await _send_sms_otp(identifier, code)
    except HTTPException:
        # never leave a usable OTP behind after a delivery failure
        await db.otp_sessions.update_many(
            {"identifier": identifier, "purpose": purpose, "used": False},
            {"$set": {"used": True}})
        raise
    return {"sent": True}


async def otp_verify(identifier: str, purpose: str, code: str) -> bool:
    rec = await db.otp_sessions.find_one({"identifier": identifier, "purpose": purpose}, sort=[("created_at", -1)])
    if not rec:
        raise HTTPException(status_code=400, detail="Please request an OTP first.")
    if rec.get("used"):
        raise HTTPException(status_code=400, detail="This OTP was already used. Request a new one.")
    if rec.get("attempts", 0) >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts. Request a new OTP.")
    try:
        if datetime.fromisoformat(rec["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="OTP has expired. Request a new one.")
    except HTTPException:
        raise
    except Exception:
        pass
    await db.otp_sessions.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
    if not hmac.compare_digest(_hash(code), rec["code_hash"]):
        raise HTTPException(status_code=400, detail="Invalid OTP.")
    await db.otp_sessions.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return True
