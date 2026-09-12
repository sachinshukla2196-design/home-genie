"""Authentication & registration routes."""
import os
import re
import hmac
import random
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from core import (db, now_iso, new_id, hash_password, verify_password, create_token,
                  clean_user, get_current_user, next_distributor_id, get_or_create_wallet,
                  create_notification, log_audit, send_email, email_shell)
from providers import otp_create, otp_verify

router = APIRouter(prefix="/api/auth", tags=["auth"])

ADMIN_PASSCODE = os.environ.get("ADMIN_PASSCODE") or "admin123"
ADMIN_ROLES = {"super_admin", "admin", "accounts_admin", "support_admin"}


class SendOtp(BaseModel):
    email: EmailStr
    mobile: str
    sponsor_id: str = ""


class RegisterBody(BaseModel):
    full_name: str
    email: EmailStr
    mobile: str
    aadhaar_number: str = ""
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
    email: str
    password: str


def _valid_mobile(m: str) -> bool:
    return bool(re.fullmatch(r"[6-9]\d{9}", (m or "").strip()))


def _valid_aadhaar(a: str) -> bool:
    return bool(re.fullmatch(r"\d{12}", (a or "").strip()))


def _valid_email(e: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (e or "").strip()))


async def _resolve_sponsor(sid_raw: str) -> dict:
    """Referral ID mandatory + must be an ACTIVE (GREEN) distributor, an admin, or an admin-generated code."""
    sid = (sid_raw or "").strip().upper()
    if not sid:
        raise HTTPException(status_code=400, detail="A referral / sponsor ID is required to register.")
    rc = await db.referral_codes.find_one({"code": sid, "active": True})
    if rc:
        admin = await db.users.find_one({"id": rc.get("created_by")}) or await db.users.find_one({"role": "super_admin"})
        if admin:
            await db.referral_codes.update_one({"code": sid}, {"$inc": {"uses": 1}})
            return admin
    sponsor = await db.users.find_one({"distributor_id": sid})
    if not sponsor:
        raise HTTPException(status_code=400, detail="Invalid referral / sponsor ID. Please check and try again.")
    if sponsor.get("role") not in ADMIN_ROLES and sponsor.get("status") != "green":
        raise HTTPException(status_code=400, detail="This referral ID belongs to an inactive member. Please use an active (GREEN) distributor's referral ID.")
    return sponsor


@router.post("/send-otp")
async def send_otp(body: SendOtp, request: Request):
    """Registration mobile OTP (mock provider in beta). Also emails the code when available."""
    email = body.email.lower().strip()
    mobile = body.mobile.strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="This email is already registered. Please log in.")
    if await db.users.find_one({"mobile": mobile}):
        raise HTTPException(status_code=400, detail="This mobile number is already registered.")
    if not _valid_mobile(mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    await _resolve_sponsor(body.sponsor_id)
    res = await otp_create(mobile, "register")
    if res.get("dev_otp"):
        html = email_shell("Verify your mobile", f"""
      <p style="color:#66736B;font-size:14px;">Use the code below to verify your mobile and complete registration. It expires shortly.</p>
      <div style="margin:20px 0;text-align:center;">
        <span style="display:inline-block;background:#EAF5ED;color:#0B4D2E;font-size:30px;font-weight:bold;letter-spacing:8px;padding:14px 24px;border-radius:12px;">{res['dev_otp']}</span>
      </div>""")
        await send_email(email, "Your Anjali Herbal Life OTP", html)
    return {"message": "OTP sent to your mobile.", **res}


class RegRequestBody(BaseModel):
    full_name: str
    mobile: str
    password: str = Field(min_length=6)
    confirm_password: str
    email: str = ""
    address: str = ""
    state: str = ""
    city: str = ""
    pincode: str = ""
    sponsor_id: str = ""
    aadhaar_number: str = ""


@router.post("/register-request")
async def register_request(body: RegRequestBody):
    """BETA: simple registration request (no OTP). Creates a PENDING request for admin approval."""
    mobile = body.mobile.strip()
    email = (body.email or "").strip().lower()
    if not _valid_mobile(mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    if email and not _valid_email(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address, or leave it blank.")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if not _valid_aadhaar(body.aadhaar_number):
        raise HTTPException(status_code=400, detail="A valid 12-digit Aadhaar number is required.")
    if not body.state.strip() or not body.city.strip() or not body.pincode.strip():
        raise HTTPException(status_code=400, detail="State, City and Pincode are required.")
    sponsor_raw = (body.sponsor_id or "").strip().upper()
    if not sponsor_raw:
        raise HTTPException(status_code=400, detail="Sponsor / Referral ID is required.")
    sponsor_ok = (sponsor_raw == "ANJ000000"
                  or await db.referral_codes.find_one({"code": sponsor_raw, "active": True})
                  or await db.users.find_one({"distributor_id": sponsor_raw}))
    if not sponsor_ok:
        raise HTTPException(status_code=400, detail="Invalid referral / sponsor ID. Enter a valid Distributor ID or referral code.")
    if await db.users.find_one({"mobile": mobile}):
        raise HTTPException(status_code=400, detail="An account already exists for this mobile number.")
    if email and await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="An account already exists for this email.")
    if await db.registration_requests.find_one({"mobile": mobile, "status": "pending"}):
        raise HTTPException(status_code=400, detail="A registration request for this mobile is already pending admin approval.")
    if email and await db.registration_requests.find_one({"email": email, "status": "pending"}):
        raise HTTPException(status_code=400, detail="A registration request for this email is already pending admin approval.")
    doc = {
        "id": new_id(), "full_name": body.full_name.strip(), "mobile": mobile,
        "email": email,
        "password_hash": hash_password(body.password),
        "address": body.address.strip(), "state": body.state.strip(),
        "city": body.city.strip(), "pincode": body.pincode.strip(),
        "sponsor_id": (body.sponsor_id or "").strip().upper() or None,
        "aadhaar_number": body.aadhaar_number.strip(),
        "status": "pending", "created_at": now_iso(),
    }
    await db.registration_requests.insert_one(dict(doc))
    return {"message": "Your registration request has been submitted. Please wait for Admin approval."}


@router.get("/reference-codes")
async def public_reference_codes():
    """Public: active admin-created reference codes for the registration dropdown (code + label only)."""
    codes = await db.referral_codes.find(
        {"active": True}, {"_id": 0, "code": 1, "label": 1, "is_master": 1}
    ).sort([("is_master", -1), ("created_at", 1)]).to_list(200)
    return codes


@router.post("/register")
async def register(body: RegisterBody, request: Request):
    email = body.email.lower().strip()
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if not body.accept_terms:
        raise HTTPException(status_code=400, detail="Please accept the Terms & Conditions.")
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="This email is already registered. Please log in.")
    mobile = body.mobile.strip()
    if await db.users.find_one({"mobile": mobile}):
        raise HTTPException(status_code=400, detail="This mobile number is already registered.")

    await otp_verify(mobile, "register", body.otp)

    if not _valid_aadhaar(body.aadhaar_number):
        raise HTTPException(status_code=400, detail="A valid 12-digit Aadhaar number is required.")

    # sponsor resolution — referral ID is mandatory + must be an active (GREEN) member or admin-generated code
    sponsor = await _resolve_sponsor(body.sponsor_id)

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
        "aadhaar_number": body.aadhaar_number.strip(),
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
    ident = email
    la = await db.login_attempts.find_one({"identifier": ident})
    if la and la.get("count", 0) >= 5:
        try:
            recent = (datetime.now(timezone.utc) - datetime.fromisoformat(la["last"])).total_seconds() < 900
        except Exception:
            recent = False
        if recent:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Please try again in about 15 minutes.")
        await db.login_attempts.delete_one({"identifier": ident})

    user = await db.users.find_one({"$or": [{"email": ident}, {"mobile": body.email.strip()}, {"distributor_id": body.email.strip().upper()}]})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        await db.login_attempts.update_one({"identifier": ident},
                                           {"$inc": {"count": 1}, "$set": {"last": now_iso()}}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid credentials. Use your Distributor ID / email / mobile and password.")
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail="Your account has been blocked. Please contact the admin.")

    await db.login_attempts.delete_one({"identifier": ident})
    await log_audit(clean_user(user), "login", "user", user["id"], request=request)
    token = create_token(user["id"])
    return {"token": token, "user": clean_user(user)}


class AdminLoginBody(BaseModel):
    username: str
    password: str
    passcode: str


@router.post("/admin-login")
async def admin_login(body: AdminLoginBody, request: Request):
    """Secured admin entry: username + password + separate admin passcode. Admin roles only."""
    uname = (body.username or "").strip()
    ukey = uname.lower()
    ident = f"admin:{ukey}"
    la = await db.login_attempts.find_one({"identifier": ident})
    if la and la.get("count", 0) >= 5:
        try:
            recent = (datetime.now(timezone.utc) - datetime.fromisoformat(la["last"])).total_seconds() < 900
        except Exception:
            recent = False
        if recent:
            raise HTTPException(status_code=429, detail="Too many failed attempts. Please try again in about 15 minutes.")
        await db.login_attempts.delete_one({"identifier": ident})

    passcode_ok = bool(ADMIN_PASSCODE) and hmac.compare_digest((body.passcode or "").strip(), ADMIN_PASSCODE)
    user = await db.users.find_one({"$or": [{"username": uname}, {"email": ukey}]})
    valid = bool(
        user
        and verify_password(body.password, user.get("password_hash", ""))
        and user.get("role") in ADMIN_ROLES
        and passcode_ok
    )
    if not valid:
        await db.login_attempts.update_one({"identifier": ident},
                                           {"$inc": {"count": 1}, "$set": {"last": now_iso()}}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid admin credentials or passcode.")

    await db.login_attempts.delete_one({"identifier": ident})
    await log_audit(clean_user(user), "admin_login", "user", user["id"], request=request)
    return {"token": create_token(user["id"]), "user": clean_user(user)}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return clean_user(user)


class PhotoBody(BaseModel):
    photo: str = ""


@router.put("/profile/photo")
async def update_photo(body: PhotoBody, request: Request, user: dict = Depends(get_current_user)):
    photo = (body.photo or "").strip()
    if photo and not (photo.startswith("data:image/") or photo.startswith("http")):
        raise HTTPException(status_code=400, detail="Invalid image format.")
    if len(photo) > 4_000_000:
        raise HTTPException(status_code=400, detail="Image too large. Please choose a smaller photo.")
    await db.users.update_one({"id": user["id"]}, {"$set": {"photo": photo, "updated_at": now_iso()}})
    await log_audit(user, "profile_photo_updated", "user", user["id"], request=request)
    updated = await db.users.find_one({"id": user["id"]})
    return clean_user(updated)


class ProfileUpdateBody(BaseModel):
    full_name: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None


@router.put("/profile")
async def update_profile(body: ProfileUpdateBody, request: Request, user: dict = Depends(get_current_user)):
    """Distributor updates their own permitted profile fields. Identity fields
    (mobile, email, Aadhaar, distributor_id, status) are NOT editable here."""
    upd = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if upd:
        await db.users.update_one({"id": user["id"]}, {"$set": {**upd, "updated_at": now_iso()}})
        await log_audit(user, "profile_updated", "user", user["id"], request=request)
    updated = await db.users.find_one({"id": user["id"]})
    return clean_user(updated)


# ---------------- Mobile OTP: login / forgot / change-mobile ----------------
class MobileBody(BaseModel):
    mobile: str


class MobileOtpBody(BaseModel):
    mobile: str
    otp: str


class EmailBody(BaseModel):
    email: EmailStr


class ForgotResetBody(BaseModel):
    email: EmailStr
    otp: str
    password: str = Field(min_length=6)


@router.post("/login-otp/send")
async def login_otp_send(body: MobileBody):
    mobile = body.mobile.strip()
    if not await db.users.find_one({"mobile": mobile}):
        raise HTTPException(status_code=404, detail="No account found for this mobile number.")
    res = await otp_create(mobile, "login")
    return {"message": "OTP sent to your mobile.", **res}


@router.post("/login-otp/verify")
async def login_otp_verify(body: MobileOtpBody, request: Request):
    mobile = body.mobile.strip()
    user = await db.users.find_one({"mobile": mobile})
    if not user:
        raise HTTPException(status_code=404, detail="No account found for this mobile number.")
    await otp_verify(mobile, "login", body.otp)
    await log_audit(clean_user(user), "login_otp", "user", user["id"], request=request)
    return {"token": create_token(user["id"]), "user": clean_user(user)}


class ForgotRequestBody(BaseModel):
    identifier: str


@router.post("/forgot/send")
async def forgot_request(body: ForgotRequestBody):
    """Admin-only password recovery: the user submits a request and an admin resets the
    password manually. NO OTP, NO SMS, NO email reset, NO external service."""
    ident = (body.identifier or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="Enter your Distributor ID or registered mobile number.")
    user = await db.users.find_one({"$or": [{"distributor_id": ident.upper()}, {"mobile": ident}]})
    if not user:
        raise HTTPException(status_code=404, detail="No account found for that Distributor ID / mobile number.")
    if not await db.password_reset_requests.find_one({"user_id": user["id"], "status": "pending"}):
        await db.password_reset_requests.insert_one({
            "id": new_id(), "user_id": user["id"], "distributor_id": user.get("distributor_id"),
            "full_name": user.get("full_name"), "mobile": user.get("mobile"),
            "status": "pending", "created_at": now_iso(),
        })
    return {"message": "Your request has been sent to the admin. Our team will reset your password and contact you shortly."}


@router.put("/change-mobile/send")
async def change_mobile_send(body: MobileBody, user: dict = Depends(get_current_user)):
    new_mobile = body.mobile.strip()
    if not _valid_mobile(new_mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    other = await db.users.find_one({"mobile": new_mobile})
    if other and other["id"] != user["id"]:
        raise HTTPException(status_code=400, detail="This mobile number is already attached to another account.")
    res = await otp_create(new_mobile, "change")
    return {"message": "OTP sent to the new mobile number.", **res}


@router.put("/change-mobile/verify")
async def change_mobile_verify(body: MobileOtpBody, request: Request, user: dict = Depends(get_current_user)):
    new_mobile = body.mobile.strip()
    other = await db.users.find_one({"mobile": new_mobile})
    if other and other["id"] != user["id"]:
        raise HTTPException(status_code=400, detail="This mobile number is already attached to another account.")
    await otp_verify(new_mobile, "change", body.otp)
    await db.users.update_one({"id": user["id"]}, {"$set": {"mobile": new_mobile, "updated_at": now_iso()}})
    await log_audit(user, "mobile_changed", "user", user["id"], request=request)
    updated = await db.users.find_one({"id": user["id"]})
    return clean_user(updated)


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user), request: Request = None):
    await log_audit(user, "logout", "user", user["id"], request=request)
    return {"message": "Logged out"}
