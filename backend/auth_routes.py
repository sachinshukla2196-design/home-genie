"""Authentication & registration routes."""
import os
import re
import random
import secrets
import hashlib
import logging
import httpx
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from core import (db, now_iso, new_id, hash_password, verify_password, create_token,
                  clean_user, get_current_user, next_distributor_id, get_or_create_wallet,
                  create_notification, log_audit, send_email, email_shell, password_update)
from providers import otp_create, otp_verify, send_account_id_sms
from pymongo import ReturnDocument

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger("homegenies")

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


async def _find_referrer(sid_raw: str) -> tuple:
    """Referral is OPTIONAL. Blank -> (None, None): no sponsor, no default. Given -> it must be an active admin
    code or an active member, and is returned as (sponsor, code). Read-only: the code's use counter is incremented
    by the caller only when an account is actually created."""
    sid = (sid_raw or "").strip().upper()
    if not sid:
        return None, None
    rc = await db.referral_codes.find_one({"code": sid, "active": True})
    if rc:
        admin = await db.users.find_one({"id": rc.get("created_by")}) or await db.users.find_one({"role": "super_admin"})
        if admin:
            return admin, sid
    sponsor = await db.users.find_one({"distributor_id": sid})
    if not sponsor:
        raise HTTPException(status_code=400, detail="Invalid referral / sponsor ID. Please check and try again, or leave it blank if you were not referred.")
    if sponsor.get("role") not in ADMIN_ROLES and sponsor.get("status") != "green":
        raise HTTPException(status_code=400, detail="This referral ID belongs to an inactive member. Please use an active HomeGenie referral ID.")
    return sponsor, None


@router.post("/send-otp")
async def send_otp(body: SendOtp, request: Request):
    """Registration mobile OTP via Twilio SMS. Fails safe (503) if SMS is not configured."""
    email = body.email.lower().strip()
    mobile = body.mobile.strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="This email is already registered. Please log in.")
    if await db.users.find_one({"mobile": mobile}):
        raise HTTPException(status_code=400, detail="This mobile number is already registered.")
    if not _valid_mobile(mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    await _find_referrer(body.sponsor_id)
    await otp_create(mobile, "register")
    return {"message": "OTP sent to your mobile."}


class RegRequestBody(BaseModel):
    full_name: str
    mobile: str
    password: str = ""
    confirm_password: str = ""
    email: str = ""
    address: str = ""
    state: str = ""
    city: str = ""
    pincode: str = ""
    sponsor_id: str = ""
    aadhaar_number: str = ""
    google_verified: bool = False


@router.post("/register-request")
async def register_request(body: RegRequestBody, request: Request):
    """BETA: simple registration request (no OTP). Creates a PENDING request for admin approval."""
    from core import rate_limit, client_ip
    await rate_limit("customer_register", client_ip(request))
    mobile = body.mobile.strip()
    email = (body.email or "").strip().lower()
    if not _valid_mobile(mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    if email and not _valid_email(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address, or leave it blank.")
    if body.google_verified:
        if not email:
            raise HTTPException(status_code=400, detail="Google sign-up requires an email.")
        pw_hash = hash_password(new_id() + new_id())  # Google users sign in via Google; random placeholder
    else:
        if len(body.password or "") < 6:
            raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
        if body.password != body.confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match.")
        pw_hash = hash_password(body.password)
    # HOME GENIES: Aadhaar is NOT collected at signup. If an identity document is
    # ever required (e.g. for point withdrawal), it is captured separately.
    if body.aadhaar_number and not _valid_aadhaar(body.aadhaar_number):
        raise HTTPException(status_code=400, detail="Enter a valid 12-digit Aadhaar number or leave it blank.")
    if not body.state.strip() or not body.city.strip() or not body.pincode.strip():
        raise HTTPException(status_code=400, detail="State, City and Pincode are required.")
    # HOME GENIES: a referral is OPTIONAL. Anyone may register and shop; the
    # HomeGenie selling role is granted by admin approval, not by a sponsor.
    await _find_referrer(body.sponsor_id)
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
        "email": email or None,  # blank is stored as null everywhere, so optional e-mail is not an empty string
        "password_hash": pw_hash,
        "email_verified": bool(body.google_verified),
        "google_linked": bool(body.google_verified),
        "address": body.address.strip(), "state": body.state.strip(),
        "city": body.city.strip(), "pincode": body.pincode.strip(),
        "sponsor_id": (body.sponsor_id or "").strip().upper() or None,
        "aadhaar_number": body.aadhaar_number.strip(),
        "status": "pending", "created_at": now_iso(),
    }
    await db.registration_requests.insert_one(dict(doc))
    # Normal users need no admin approval: create the account now. The request row is kept (marked approved) as a record.
    from admin_routes import activate_registration
    try:
        await activate_registration(doc)
    except HTTPException:
        await db.registration_requests.delete_one({"id": doc["id"]})
        raise
    return {"message": "Registration successful. You can log in now with your mobile/email and password."}


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

    # referral is checked BEFORE the OTP is consumed, so a bad referral does not burn the code
    sponsor, referral_code = await _find_referrer(body.sponsor_id)

    await otp_verify(mobile, "register", body.otp)

    # HOME GENIES: Aadhaar is NOT collected at signup. If an identity document is
    # ever required (e.g. for point withdrawal), it is captured separately.
    if body.aadhaar_number and not _valid_aadhaar(body.aadhaar_number):
        raise HTTPException(status_code=400, detail="Enter a valid 12-digit Aadhaar number or leave it blank.")

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
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await db.users.insert_one(dict(user))
    await get_or_create_wallet(uid)
    if referral_code:
        await db.referral_codes.update_one({"code": referral_code}, {"$inc": {"uses": 1}})

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

    await create_notification(uid, "welcome", "Welcome to HOME GENIES",
                              f"Your Member ID is {distributor_id}.",
                              "होम जीनीज़ में आपका स्वागत है",
                              f"आपकी मेंबर आईडी {distributor_id} है।")
    await log_audit(clean_user(user), "register", "user", uid, request=request)

    # Best-effort: SMS the new distributor their Account ID (never the password).
    await send_account_id_sms(user["mobile"], distributor_id)

    token = create_token(uid)
    return {"token": token, "user": clean_user(user)}


@router.post("/login")
async def login(body: LoginBody, request: Request):
    from core import rate_limit, client_ip
    await rate_limit("login_ip", client_ip(request))          # per-IP cap on top of the per-account lockout (stops password spraying)
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
    if not user:
        # A registration made while admin approval was still required may be sitting in registration_requests.
        # Normal users no longer need approval: activate it now (idempotent, no duplicate account), but only when
        # the password matches so this cannot be used to probe or create accounts for other people.
        if not user:
            pending = await db.registration_requests.find_one(
                {"status": "pending", "$or": [{"email": ident}, {"mobile": body.email.strip()}]})
            if pending and verify_password(body.password, pending.get("password_hash", "")):
                from admin_routes import activate_registration
                await activate_registration(pending)
                await db.login_attempts.delete_one({"identifier": ident})
                user = await db.users.find_one({"$or": [{"email": ident}, {"mobile": body.email.strip()}]})
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        await db.login_attempts.update_one({"identifier": ident},
                                           {"$inc": {"count": 1}, "$set": {"last": now_iso()}}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid credentials. Use your HomeGenie ID / email / mobile and password.")
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail="Your account has been blocked. Please contact the admin.")

    await db.login_attempts.delete_one({"identifier": ident})
    await log_audit(clean_user(user), "login", "user", user["id"], request=request)
    token = create_token(user["id"])
    return {"token": token, "user": clean_user(user)}


EMERGENT_SESSION_DATA_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


class GoogleSessionBody(BaseModel):
    session_id: str


async def _google_identity(session_id: str) -> dict:
    """The Google identity (email, name) behind a sign-in session, as verified by the managed Google auth service."""
    sid = (session_id or "").strip()
    if not sid:
        raise HTTPException(status_code=400, detail="Missing session. Please try signing in again.")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            resp = await client.get(EMERGENT_SESSION_DATA_URL, headers={"X-Session-ID": sid})
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Could not verify Google sign-in right now. Please try again.")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified. Please try again.")
    return resp.json()


@router.post("/google/session")
async def google_session(body: GoogleSessionBody, request: Request):
    """Emergent-managed Google sign-in for EXISTING distributors only.
    We use Emergent Auth solely to obtain the verified Google email, then match it to an
    existing account and mint the app's own JWT (same as password login). No new account
    is created here — sponsor/KYC/admin-approval rules are never bypassed."""
    data = await _google_identity(body.session_id)
    email = (data.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Google did not return an email. Please try another account.")

    user = await db.users.find_one({"email": email})
    if not user:
        # No account yet -> tell the frontend to start a Google-prefilled registration request.
        return {"mode": "register", "email": email, "name": (data.get("name") or "").strip()}
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail="Your account has been blocked. Please contact the admin.")

    await db.users.update_one({"id": user["id"]},
                              {"$set": {"google_linked": True, "email_verified": True, "updated_at": now_iso()}})
    user["google_linked"] = True
    user["email_verified"] = True
    await log_audit(clean_user(user), "login_google", "user", user["id"], request=request)
    token = create_token(user["id"])
    return {"mode": "login", "token": token, "user": clean_user(user)}


# ---------------- Password recovery with Google (mobile OTP recovery to follow) ----------------
GOOGLE_RESET_MINUTES = 15
GENERIC_RECOVERY_MESSAGE = "If an account matches this Google email, you can now set a new password."


def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


class GoogleRecoveryBody(BaseModel):
    session_id: str


class GoogleResetBody(BaseModel):
    token: str
    password: str


@router.post("/forgot/google")
async def forgot_google(body: GoogleRecoveryBody, request: Request):
    """Google-verified password recovery. Proves control of the account's Google e-mail, then issues a
    single-use reset token valid for 15 minutes. Unknown, blocked and admin accounts get the same answer
    with no token, so the endpoint cannot be used to discover accounts or to reset admin passwords."""
    from core import rate_limit, client_ip
    await rate_limit("forgot_password", client_ip(request))
    data = await _google_identity(body.session_id)
    email = (data.get("email") or "").strip().lower()
    if not email:
        return {"message": GENERIC_RECOVERY_MESSAGE}
    user = await db.users.find_one({"email": email})
    if not user or user.get("blocked") or user.get("role") in ADMIN_ROLES:
        return {"message": GENERIC_RECOVERY_MESSAGE}
    now = datetime.now(timezone.utc)
    await db.password_reset_tokens.update_many({"user_id": user["id"], "used": False}, {"$set": {"used": True}})
    token = secrets.token_urlsafe(32)
    await db.password_reset_tokens.insert_one({
        "id": new_id(), "user_id": user["id"], "token_hash": _token_hash(token), "used": False,
        "expires_at": (now + timedelta(minutes=GOOGLE_RESET_MINUTES)).isoformat(), "created_at": now.isoformat(),
    })
    await log_audit(clean_user(user), "password_reset_started_google", "user", user["id"], request=request)
    return {"message": GENERIC_RECOVERY_MESSAGE, "reset_token": token}


@router.post("/forgot/google/reset")
async def forgot_google_reset(body: GoogleResetBody, request: Request):
    """Sets the new password with a token from /forgot/google. The token is claimed atomically, so it works once."""
    from core import rate_limit, client_ip
    await rate_limit("forgot_reset", client_ip(request))
    if len(body.password or "") < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    now = datetime.now(timezone.utc).isoformat()
    row = await db.password_reset_tokens.find_one_and_update(
        {"token_hash": _token_hash(body.token), "used": False, "expires_at": {"$gt": now}},
        {"$set": {"used": True, "used_at": now}}, return_document=ReturnDocument.BEFORE)
    invalid = HTTPException(status_code=400, detail="This reset link is invalid or has expired. Please start again.")
    if not row:
        raise invalid
    user = await db.users.find_one({"id": row["user_id"]})
    if not user or user.get("blocked") or user.get("role") in ADMIN_ROLES:
        raise invalid
    await db.users.update_one({"id": user["id"]}, {"$set": {**password_update(body.password), "updated_at": now_iso()}})
    await db.password_reset_requests.update_many({"user_id": user["id"], "status": "pending"},
        {"$set": {"status": "resolved", "resolved_at": now_iso()}})
    await log_audit(clean_user(user), "password_reset_completed_google", "user", user["id"], request=request)
    return {"message": "Your password has been updated. You can log in now with the new password."}


class AdminLoginBody(BaseModel):
    username: str
    password: str
    passcode: str = ""  # no longer required; accepted and ignored for older clients


@router.post("/admin-login")
async def admin_login(body: AdminLoginBody, request: Request):
    """Admin entry: username/email + password. Admin roles only (lockout after 5 failed attempts)."""
    from core import rate_limit, client_ip
    await rate_limit("admin_login_ip", client_ip(request))
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

    user = await db.users.find_one({"$or": [{"username": uname}, {"email": ukey}]})
    valid = bool(
        user
        and verify_password(body.password, user.get("password_hash", ""))
        and user.get("role") in ADMIN_ROLES
    )
    if not valid:
        await db.login_attempts.update_one({"identifier": ident},
                                           {"$inc": {"count": 1}, "$set": {"last": now_iso()}}, upsert=True)
        raise HTTPException(status_code=401, detail="Invalid admin credentials.")

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


LOGIN_OTP_SENT = "If this mobile number is registered, an OTP has been sent to it."
LOGIN_OTP_INVALID = "The OTP is invalid or has expired. Please request a new one."


def _eligible_for_login_otp(user: Optional[dict]) -> bool:
    """Only ordinary, unblocked accounts can sign in with a mobile OTP. Admins use the secure admin login."""
    return bool(user) and user.get("role") not in ADMIN_ROLES and not user.get("blocked") \
        and user.get("account_status") != "blocked"


@router.post("/login-otp/send")
async def login_otp_send(body: MobileBody, request: Request):
    """Same public answer for registered and unregistered numbers. An OTP is sent only to an eligible account.
    Provider configuration problems are global, so they are reported the same way for every number."""
    from core import rate_limit, client_ip
    from providers import sms_available, OTP_UNAVAILABLE
    await rate_limit("login_otp_send", client_ip(request))
    mobile = body.mobile.strip()
    if not sms_available():
        raise OTP_UNAVAILABLE
    user = await db.users.find_one({"mobile": mobile})
    if _eligible_for_login_otp(user):
        try:
            await otp_create(mobile, "login")
        except HTTPException as e:
            # a cooldown (429) or a single failed delivery must not reveal that the number is registered
            if e.status_code not in (429, 503):
                raise
            logger.warning("login OTP not issued (status %s)", e.status_code)
    return {"message": LOGIN_OTP_SENT}


@router.post("/login-otp/verify")
async def login_otp_verify(body: MobileOtpBody, request: Request):
    """Unknown, ineligible, expired, reused, wrong and over-attempted codes all get the same answer."""
    from core import rate_limit, client_ip
    await rate_limit("login_otp_verify", client_ip(request))
    mobile = body.mobile.strip()
    user = await db.users.find_one({"mobile": mobile})
    if not _eligible_for_login_otp(user):
        raise HTTPException(status_code=400, detail=LOGIN_OTP_INVALID)
    try:
        await otp_verify(mobile, "login", body.otp)
    except HTTPException as e:
        if e.status_code in (400, 429):
            raise HTTPException(status_code=400, detail=LOGIN_OTP_INVALID)
        raise
    await log_audit(clean_user(user), "login_otp", "user", user["id"], request=request)
    return {"token": create_token(user["id"]), "user": clean_user(user)}


class ForgotRequestBody(BaseModel):
    identifier: str


@router.post("/forgot/send")
async def forgot_request(body: ForgotRequestBody, request: Request):
    """Admin-only password recovery: the user submits a request and an admin resets the
    password manually. NO OTP, NO SMS, NO email reset, NO external service."""
    from core import rate_limit, client_ip
    await rate_limit("forgot_password", client_ip(request))
    ident = (body.identifier or "").strip()
    if not ident:
        raise HTTPException(status_code=400, detail="Enter your HomeGenie ID or registered mobile number.")
    user = await db.users.find_one({"$or": [{"distributor_id": ident.upper()}, {"mobile": ident}]})
    # Same answer whether or not the account exists, so the endpoint cannot be used to find registered members.
    if user and not await db.password_reset_requests.find_one({"user_id": user["id"], "status": "pending"}):
        await db.password_reset_requests.insert_one({
            "id": new_id(), "user_id": user["id"], "distributor_id": user.get("distributor_id"),
            "full_name": user.get("full_name"), "mobile": user.get("mobile"),
            "status": "pending", "created_at": now_iso(),
        })
    return {"message": "If an account matches, your request has been sent to the admin. Our team will reset your password and contact you shortly."}


@router.put("/change-mobile/send")
async def change_mobile_send(body: MobileBody, user: dict = Depends(get_current_user)):
    new_mobile = body.mobile.strip()
    if not _valid_mobile(new_mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    other = await db.users.find_one({"mobile": new_mobile})
    if other and other["id"] != user["id"]:
        raise HTTPException(status_code=400, detail="This mobile number is already attached to another account.")
    await otp_create(new_mobile, "change")
    return {"message": "OTP sent to the new mobile number."}


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
