"""Production OTP: server-generated secure OTP, delivered ONLY via a real SMS
provider (Twilio). No mock, no test OTP, no dev OTP, no OTP in API responses or
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

TWILIO_ENABLED = os.environ.get("TWILIO_ENABLED", "false").strip().lower() == "true"
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "")


def sms_configured() -> bool:
    return TWILIO_ENABLED and bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


OTP_UNAVAILABLE = HTTPException(status_code=503, detail={
    "code": "OTP_SERVICE_UNAVAILABLE",
    "message": "OTP verification is temporarily unavailable. Please try again later."})


def _normalize_mobile(m: str) -> str:
    """Return an E.164 number (+<country><number>) for Twilio. Defaults to India (+91)."""
    p = re.sub(r"\D", "", (m or ""))
    if len(p) == 10:
        p = "91" + p
    return "+" + p


def _hash(code: str) -> str:
    return hmac.new(OTP_PEPPER.encode(), (code or "").strip().encode(), hashlib.sha256).hexdigest()


async def _send_sms_otp(mobile: str, code: str) -> None:
    """Deliver OTP via Twilio Messages API. Never logs the code or provider secrets."""
    if not sms_configured():
        raise OTP_UNAVAILABLE
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {
        "To": _normalize_mobile(mobile),
        "From": TWILIO_FROM_NUMBER,
        "Body": f"Welcome to Anjali Herbal Life - a world of possibilities! Your verification code is {code}. It expires in 5 minutes. Do not share it with anyone.",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(url, data=data, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not send OTP right now. Please try again shortly.")
    if resp.status_code >= 400:
        logger.error("Twilio send rejected (status=%s)", resp.status_code)
        raise HTTPException(status_code=503, detail="Could not send OTP right now. Please try again shortly.")


async def send_account_id_sms(mobile: str, distributor_id: str) -> bool:
    """Best-effort: SMS a new distributor their Account ID (NEVER the password).
    Never raises — a delivery failure must not block registration."""
    if not sms_configured():
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = {
        "To": _normalize_mobile(mobile),
        "From": TWILIO_FROM_NUMBER,
        "Body": f"Welcome to Anjali Herbal Life - a world of possibilities! Your Distributor ID is {distributor_id}. Keep it safe to log in.",
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.post(url, data=data, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
        if resp.status_code >= 400:
            logger.error("Twilio account-ID SMS rejected (status=%s)", resp.status_code)
            return False
        return True
    except httpx.HTTPError:
        logger.error("Twilio account-ID SMS failed to send")
        return False


async def otp_create(identifier: str, purpose: str) -> dict:
    """Generate + store a hashed single-use OTP and deliver it via SMS. Returns NO code."""
    if not sms_configured():
        raise OTP_UNAVAILABLE
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
    if not sms_configured():
        raise OTP_UNAVAILABLE
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
