"""Lightweight provider abstraction (BETA mock providers).
Switchable via env without touching business logic. Production blocks mocks."""
import os
import hashlib
import secrets
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from core import db, now_iso, JWT_SECRET

APP_ENV = os.environ.get("APP_ENV", "production")
OTP_PROVIDER = os.environ.get("OTP_PROVIDER", "mock")
OTP_TTL = int(os.environ.get("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = int(os.environ.get("OTP_MAX_ATTEMPTS", "5"))
OTP_RESEND_COOLDOWN = int(os.environ.get("OTP_RESEND_COOLDOWN", "30"))
TEST_NUMBERS = set(x.strip() for x in os.environ.get("OTP_TEST_NUMBERS", "9999999999").split(",") if x.strip())
TEST_OTP = "123456"


def is_test_number(m: str) -> bool:
    return (m or "").strip() in TEST_NUMBERS


def _hash(code: str) -> str:
    return hashlib.sha256(f"{code}:{JWT_SECRET}".encode()).hexdigest()


async def otp_create(identifier: str, purpose: str) -> dict:
    # Production must use a real provider; mock is blocked.
    if APP_ENV == "production" and OTP_PROVIDER == "mock":
        raise HTTPException(status_code=503, detail="OTP service is not configured.")
    last = await db.otp_sessions.find_one({"identifier": identifier, "purpose": purpose}, sort=[("created_at", -1)])
    if last:
        try:
            if (datetime.now(timezone.utc) - datetime.fromisoformat(last["created_at"])).total_seconds() < OTP_RESEND_COOLDOWN:
                raise HTTPException(status_code=429, detail="Please wait a few seconds before requesting another OTP.")
        except HTTPException:
            raise
        except Exception:
            pass
    code = TEST_OTP if is_test_number(identifier) else f"{secrets.randbelow(1000000):06d}"
    # invalidate any prior pending OTP for this identifier/purpose (non-destructive)
    await db.otp_sessions.update_many(
        {"identifier": identifier, "purpose": purpose, "used": False},
        {"$set": {"used": True}})
    await db.otp_sessions.insert_one({
        "identifier": identifier, "purpose": purpose, "code_hash": _hash(code),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=OTP_TTL)).isoformat(),
        "attempts": 0, "used": False, "created_at": now_iso(),
    })
    print(f"[OTP:{purpose}] {identifier} -> {code}")  # dev/admin log only
    # dev_otp exposed only in non-production beta, and never for approved test numbers
    dev = None if (APP_ENV == "production" or is_test_number(identifier)) else code
    return {"dev_otp": dev, "test_number": is_test_number(identifier)}


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
    if _hash((code or "").strip()) != rec["code_hash"]:
        await db.otp_sessions.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="Invalid OTP.")
    await db.otp_sessions.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return True
