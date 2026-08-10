"""Authentication & registration routes."""
import re
import random
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from core import (db, now_iso, new_id, hash_password, verify_password, create_token,
                  clean_user, get_current_user, next_distributor_id, get_or_create_wallet,
                  create_notification, log_audit, send_email, email_shell)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class SendOtp(BaseModel):
    email: EmailStr
    mobile: str


class RegisterBody(BaseModel):
    full_name: str
    email: EmailStr
    mobile: str
    password: str = Field(min_length=6)
    confirm_password: str
    otp: str
    sponsor_id: Optional[str] = ""
    address: str = ""
    state: str = ""
    city: str = ""
    pincode: str = ""
    accept_terms: bool = False


class LoginBody(BaseModel):
    email: EmailStr
    password: str


def _valid_mobile(m: str) -> bool:
    return bool(re.fullmatch(r"[6-9]\d{9}", (m or "").strip()))


@router.post("/send-otp")
async def send_otp(body: SendOtp, request: Request):
    """Generate an OTP for registration. Email/SMS delivery is MOCKED in preview;
    the OTP is returned as dev_otp and logged server-side."""
    email = body.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="This email is already registered. Please log in.")
    if not _valid_mobile(body.mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    code = f"{random.randint(0, 999999):06d}"
    await db.otp_codes.delete_many({"email": email, "purpose": "register"})
    await db.otp_codes.insert_one({
        "id": new_id(), "email": email, "mobile": body.mobile, "code": code,
        "purpose": "register", "verified": False, "created_at": now_iso(),
    })
    print(f"[OTP] register {email} -> {code}")
    html = email_shell("Verify your email", f"""
      <p style="color:#66736B;font-size:14px;">Use the code below to complete your Anjali Herbal Life registration. It is valid for a short time.</p>
      <div style="margin:20px 0;text-align:center;">
        <span style="display:inline-block;background:#EAF5ED;color:#0B4D2E;font-size:30px;font-weight:bold;letter-spacing:8px;padding:14px 24px;border-radius:12px;">{code}</span>
      </div>
      <p style="color:#66736B;font-size:12px;">If you didn't request this, you can ignore this email.</p>""")
    sent = await send_email(email, "Your Anjali Herbal Life OTP", html)
    return {"message": "OTP sent to your email.", "email_sent": sent, "dev_otp": code}


@router.post("/register")
async def register(body: RegisterBody, request: Request):
    email = body.email.lower().strip()
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if not body.accept_terms:
        raise HTTPException(status_code=400, detail="Please accept the Terms & Conditions.")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="This email is already registered. Please log in.")

    otp = await db.otp_codes.find_one({"email": email, "purpose": "register"})
    if not otp or otp["code"] != body.otp.strip():
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

    # sponsor resolution
    sponsor = None
    sid = (body.sponsor_id or "").strip().upper()
    if sid:
        sponsor = await db.users.find_one({"distributor_id": sid}, {"_id": 0})
        if not sponsor:
            raise HTTPException(status_code=400, detail="Invalid sponsor / referral ID.")

    distributor_id = await next_distributor_id()
    uid = new_id()
    user = {
        "id": uid,
        "distributor_id": distributor_id,
        "full_name": body.full_name.strip(),
        "email": email,
        "mobile": body.mobile.strip(),
        "password_hash": hash_password(body.password),
        "role": "distributor",
        "status": "red",  # red = registered/not activated, green = activated
        "mobile_verified": True,
        "email_verified": True,
        "sponsor_id": sponsor["distributor_id"] if sponsor else None,
        "sponsor_user_id": sponsor["id"] if sponsor else None,
        "address": body.address, "state": body.state, "city": body.city, "pincode": body.pincode,
        "kyc_status": "not_started",
        "activation_date": None, "activation_order_id": None, "activation_amount": None,
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.users.insert_one(dict(user))
    await get_or_create_wallet(uid)

    if sponsor:
        await db.referral_relationships.insert_one({
            "id": new_id(),
            "sponsor_id": sponsor["id"],
            "sponsor_distributor_id": sponsor["distributor_id"],
            "referred_user_id": uid,
            "referred_distributor_id": distributor_id,
            "commission_paid": False,
            "created_at": now_iso(),
        })
        await create_notification(sponsor["id"], "referral_join",
                                  "New referral joined",
                                  f"{user['full_name']} ({distributor_id}) registered using your referral.",
                                  "नया रेफ़रल जुड़ा",
                                  f"{user['full_name']} ({distributor_id}) ने आपके रेफ़रल से रजिस्टर किया।")

    await db.otp_codes.delete_many({"email": email, "purpose": "register"})
    await create_notification(uid, "welcome", "Welcome to Anjali Herbal Life",
                              f"Your Distributor ID is {distributor_id}. Activate your account to unlock income.",
                              "अंजलि हर्बल लाइफ में आपका स्वागत है",
                              f"आपकी डिस्ट्रीब्यूटर आईडी {distributor_id} है। आय अनलॉक करने के लिए खाता सक्रिय करें।")
    await log_audit(clean_user(user), "register", "user", uid, request=request)

    token = create_token(uid)
    return {"token": token, "user": clean_user(user)}


@router.post("/login")
async def login(body: LoginBody, request: Request):
    email = body.email.lower().strip()
    ident = f"{request.client.host if request.client else 'x'}:{email}"
    la = await db.login_attempts.find_one({"identifier": ident})
    if la and la.get("count", 0) >= 5:
        last = la.get("last")
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in a few minutes.")

    user = await db.users.find_one({"email": email})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        await db.login_attempts.update_one({"identifier": ident},
                                           {"$inc": {"count": 1}, "$set": {"last": now_iso()}}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    await db.login_attempts.delete_one({"identifier": ident})
    await log_audit(clean_user(user), "login", "user", user["id"], request=request)
    token = create_token(user["id"])
    return {"token": token, "user": clean_user(user)}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return clean_user(user)


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user), request: Request = None):
    await log_audit(user, "logout", "user", user["id"], request=request)
    return {"message": "Logged out"}
