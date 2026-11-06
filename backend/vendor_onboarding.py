"""Vendor onboarding: the admin-run registration that turns an accepted application into an operational vendor.

OWNER-LOCKED FLOW (Vendor Pillar)
    application -> [admin converts] -> onboarding -> [admin submits, checklist enforced] -> ready_for_review
                -> [super_admin] approve | request changes (back to onboarding) | reject
    approve -> owner account activated through a single-use owner invitation -> owner sets a password -> vendor panel.

- The owner account exists from the start (so its mobile/email are reserved) but is `pending_approval`: no sign-in path accepts it
  (core.not_activated). It becomes `invited` at final approval and `active` only when the owner accepts the invitation.
- The registration is saved section by section. Saving checks the FORMAT of what is given; completeness is a separate,
  backend-enforced checklist, so an admin can save progress and return later.
- Documents follow a REQUIRED / CONDITIONAL / OPTIONAL model that depends on the business type and answers; only documents that a
  reviewer has verified count.
- Commercial preparation reuses the existing agreements (finance drafts, a second finance admin approves).
- Nothing here touches HomeGenie identity, commissions, wallets or settlements.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from catalogue import PILLARS
from core import (db, now_iso, new_id, hash_password, next_sequence, require_admin, require_vendor_admin, log_audit,
                  create_notification)
from validators import safe_image_refs
from vendor_history import record_vendor_status
from vendor_lifecycle import move, VENDOR_ACCOUNT_STATUS

router = APIRouter(prefix="/api", tags=["vendor-onboarding"])

VIEW_ROLES = ("super_admin", "admin", "support_admin")          # support may look; only super_admin/admin change anything

BUSINESS_TYPES = {"proprietorship": "Proprietorship", "partnership": "Partnership firm", "llp": "Limited Liability Partnership (LLP)",
                  "private_limited": "Private Limited Company", "public_limited": "Public Limited Company", "other": "Other"}
SUPPLIER_ROLES = {"manufacturer": "Manufacturer", "brand_owner": "Brand owner", "wholesaler": "Wholesaler", "distributor": "Distributor",
                  "reseller": "Reseller / retailer", "other": "Other"}
RELATIONSHIPS = {"proprietor": "Proprietor", "partner": "Partner", "director": "Director", "employee": "Employee / manager",
                 "other": "Other"}
ACCOUNT_TYPES = {"current": "Current", "savings": "Savings", "other": "Other"}
RESPONSIBILITY = {"vendor": "Vendor", "platform": "HOME GENIES"}
COMPANY_TYPES = ("partnership", "llp", "private_limited", "public_limited")
INDIAN_STATES = (
    "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir",
    "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh",
    "Uttarakhand", "West Bengal")

MOBILE = re.compile(r"[6-9]\d{9}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PAN = re.compile(r"[A-Z]{5}\d{4}[A-Z]")
GSTIN = re.compile(r"\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]")
LLPIN = re.compile(r"[A-Z]{3}-\d{4}")
CIN = re.compile(r"[LU]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}")
IFSC = re.compile(r"[A-Z]{4}0[A-Z0-9]{6}")
PINCODE = re.compile(r"[1-9]\d{5}")
ACCOUNT = re.compile(r"[0-9A-Za-z]{6,24}")
UDYAM = re.compile(r"UDYAM-[A-Z]{2}-\d{2}-\d{7}")

SECTIONS = {"business": "Business identity", "person": "Authorised person", "legal": "Legal & tax", "addresses": "Addresses",
            "operations": "Operations", "bank": "Bank & settlement", "documents": "Documents", "commercial": "Commercial terms"}
EDITABLE = ("business", "person", "legal", "addresses", "operations", "bank")
ADDRESS_KINDS = {"registered": "Registered / legal address", "pickup": "Pickup / warehouse address", "return": "Return address",
                 "correspondence": "Correspondence address"}
SAME_AS = {"pickup": ("registered",), "return": ("registered", "pickup"), "correspondence": ("registered",)}

DOC_LABELS = {"pan": "PAN card", "gst": "GST registration certificate", "bank_proof": "Cancelled cheque / bank proof",
              "address_proof": "Business address proof", "identity": "Authorised person's identity proof",
              "business_registration": "Business registration (deed / incorporation certificate)",
              "authorisation_letter": "Authorisation letter for the signatory", "other": "Other supporting document"}


def _bad(msg: str):
    raise HTTPException(status_code=400, detail=msg)


def _text(d: dict, key: str, label: str, lo: int = 1, hi: int = 120) -> Optional[str]:
    v = d.get(key)
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if not isinstance(v, str) or not (lo <= len(v.strip()) <= hi):
        _bad(f"{label} must be {lo}-{hi} characters.")
    return v.strip()


def _choice(d: dict, key: str, options, label: str) -> Optional[str]:
    v = d.get(key)
    if v in (None, ""):
        return None
    if v not in options:
        _bad(f"Choose a valid {label}.")
    return v


def _bool(d: dict, key: str) -> Optional[bool]:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, bool):
        _bad(f"'{key}' must be yes or no.")
    return v


def _pattern(d: dict, key: str, rx, label: str, upper: bool = True) -> Optional[str]:
    v = d.get(key)
    if v in (None, ""):
        return None
    v = str(v).strip().upper() if upper else str(v).strip()
    if not rx.fullmatch(v):
        _bad(f"Enter a valid {label}.")
    return v


def _url(d: dict, key: str) -> Optional[str]:
    v = (d.get(key) or "").strip()
    if not v:
        return None
    if len(v) > 200 or not v.startswith("https://") or any(ch in v for ch in " <>\"'"):
        _bad("Website must be a full https:// address.")
    return v


def _address(a, label: str) -> Optional[dict]:
    if a in (None, {}):
        return None
    if not isinstance(a, dict):
        _bad(f"{label} is not valid.")
    out = {"line1": _text(a, "line1", f"{label}: address line 1", 3, 160), "line2": _text(a, "line2", f"{label}: address line 2", 1, 160),
           "landmark": _text(a, "landmark", f"{label}: landmark", 1, 80), "city": _text(a, "city", f"{label}: city", 2, 60),
           "state": _choice(a, "state", INDIAN_STATES, f"{label} state"), "pincode": _pattern(a, "pincode", PINCODE, f"{label} PIN code")}
    return {k: v for k, v in out.items() if v is not None}


# ------------------------------------------------------------------ section validation (format only)
def clean_section(key: str, d: dict, current: dict) -> dict:
    """Validates the format of a section and returns the cleaned values. Missing fields are allowed (save progress)."""
    if not isinstance(d, dict):
        _bad("Section data must be an object.")
    if key == "business":
        cats = d.get("categories")
        if cats is not None and (not isinstance(cats, list) or any(c not in PILLARS for c in cats)):
            _bad("Categories must be chosen from the four HOME GENIES pillars.")
        roles = d.get("supplier_roles")
        if roles is not None and (not isinstance(roles, list) or any(r not in SUPPLIER_ROLES for r in roles)):
            _bad("Choose valid supplier roles.")
        year = d.get("year_established")
        if year not in (None, ""):
            if isinstance(year, bool) or not isinstance(year, int) or not (1900 <= year <= datetime.now().year):
                _bad("Year established must be a year between 1900 and this year.")
        else:
            year = None
        out = {"legal_name": _text(d, "legal_name", "Legal business name", 2, 160), "display_name": _text(d, "display_name", "Store name", 2, 120),
               "business_type": _choice(d, "business_type", BUSINESS_TYPES, "business type"),
               "business_type_other": _text(d, "business_type_other", "Business type (other)", 2, 80),
               "supplier_roles": sorted(set(roles)) if roles else None, "description": _text(d, "description", "Business description", 20, 1000),
               "categories": [c for c in PILLARS if c in cats] if cats else None, "year_established": year, "website": _url(d, "website")}
    elif key == "person":
        out = {"full_name": _text(d, "full_name", "Full name", 2, 80), "designation": _text(d, "designation", "Designation", 2, 60),
               "mobile": _pattern(d, "mobile", MOBILE, "10-digit Indian mobile number", upper=False),
               "email": (_pattern(d, "email", EMAIL, "email address", upper=False) or "").lower() or None,
               "alternate_mobile": _pattern(d, "alternate_mobile", MOBILE, "alternate mobile number", upper=False),
               "relationship": _choice(d, "relationship", RELATIONSHIPS, "relationship to the business"),
               "is_authorised_signatory": _bool(d, "is_authorised_signatory"),
               "signatory_name": _text(d, "signatory_name", "Authorised signatory's name", 2, 80)}
        if out["alternate_mobile"] and out["alternate_mobile"] == out["mobile"]:
            _bad("The alternate mobile must be different from the main mobile.")
    elif key == "legal":
        out = {"pan": _pattern(d, "pan", PAN, "PAN (e.g. ABCDE1234F)"), "gst_registered": _bool(d, "gst_registered"),
               "gstin": _pattern(d, "gstin", GSTIN, "GSTIN (15 characters)"), "gst_exemption_declared": _bool(d, "gst_exemption_declared"),
               "llpin": _pattern(d, "llpin", LLPIN, "LLPIN (e.g. AAB-1234)"), "cin": _pattern(d, "cin", CIN, "CIN (21 characters)"),
               "udyam": _pattern(d, "udyam", UDYAM, "Udyam number (UDYAM-XX-00-0000000)")}
        if out["gstin"] and out["pan"] and out["gstin"][2:12] != out["pan"]:
            _bad("The GSTIN does not match the PAN (characters 3-12 of a GSTIN are the PAN).")
        if out["gst_registered"] is False:
            out["gstin"] = None
    elif key == "addresses":
        out = {}
        for kind, label in ADDRESS_KINDS.items():
            same = d.get(f"{kind}_same_as")
            if same not in (None, ""):
                if same not in SAME_AS.get(kind, ()):
                    _bad(f"{label}: choose a valid 'same as' option.")
                out[f"{kind}_same_as"] = same
            else:
                out[kind] = _address(d.get(kind), label)
        out["pickup_contact_name"] = _text(d, "pickup_contact_name", "Pickup contact name", 2, 80)
        out["pickup_contact_phone"] = _pattern(d, "pickup_contact_phone", MOBILE, "pickup contact mobile", upper=False)
    elif key == "operations":
        hd = d.get("handling_days")
        if hd not in (None, ""):
            if isinstance(hd, bool) or not isinstance(hd, int) or not (1 <= hd <= 15):
                _bad("Usual dispatch time must be 1 to 15 days.")
        else:
            hd = None
        out = {"handling_days": hd, "support_phone": _pattern(d, "support_phone", MOBILE, "support mobile number", upper=False),
               "support_email": (_pattern(d, "support_email", EMAIL, "support email", upper=False) or "").lower() or None,
               "support_hours": _text(d, "support_hours", "Support hours", 3, 80),
               "packaging_by": _choice(d, "packaging_by", RESPONSIBILITY, "packaging responsibility"),
               "shipping_by": _choice(d, "shipping_by", RESPONSIBILITY, "shipping responsibility"),
               "notes": _text(d, "notes", "Operational notes", 1, 500)}
    elif key == "bank":
        acct = d.get("account_number")
        if acct not in (None, ""):
            acct = str(acct).strip()
            if not ACCOUNT.fullmatch(acct):
                _bad("Account number must be 6-24 letters or digits.")
            if str(d.get("account_number_confirm") or "").strip() != acct:
                _bad("The account numbers do not match.")
        else:
            acct = (current or {}).get("account_number")       # blank = keep what is stored (the screen only ever shows it masked)
        out = {"account_holder": _text(d, "account_holder", "Account holder name", 2, 120), "bank_name": _text(d, "bank_name", "Bank name", 2, 80),
               "account_number": acct, "ifsc": _pattern(d, "ifsc", IFSC, "IFSC (e.g. SBIN0001234)"),
               "account_type": _choice(d, "account_type", ACCOUNT_TYPES, "account type"), "branch": _text(d, "branch", "Branch", 2, 80)}
    else:
        _bad("Unknown section.")
    return {k: v for k, v in out.items() if v is not None}


def resolve_address(addresses: dict, kind: str, _depth: int = 0) -> Optional[dict]:
    same = addresses.get(f"{kind}_same_as")
    if same and _depth < 3:
        return resolve_address(addresses, same, _depth + 1)
    return addresses.get(kind)


def _address_complete(a: Optional[dict]) -> bool:
    return bool(a) and all(a.get(k) for k in ("line1", "city", "state", "pincode"))


# ------------------------------------------------------------------ documents: required / conditional / optional
def document_rules(onb: dict, policy_required: list) -> dict:
    biz, person, legal = onb.get("business") or {}, onb.get("person") or {}, onb.get("legal") or {}
    required = ["pan", "bank_proof", "address_proof", "identity"]
    conditional = []
    if legal.get("gst_registered"):
        conditional.append({"type": "gst", "reason": "GST registered"})
    if biz.get("business_type") in COMPANY_TYPES:
        conditional.append({"type": "business_registration", "reason": BUSINESS_TYPES[biz["business_type"]]})
    if person.get("is_authorised_signatory") is False:
        conditional.append({"type": "authorisation_letter", "reason": "The contact person is not the authorised signatory"})
    for t in policy_required:                                   # anything HOME GENIES has made mandatory in the vendor policy
        if t not in required and t not in [c["type"] for c in conditional]:
            required.append(t)
    needed = set(required) | {c["type"] for c in conditional}
    optional = [t for t in DOC_LABELS if t not in needed]
    return {"required": required, "conditional": conditional, "optional": optional}


# ------------------------------------------------------------------ the checklist (backend-enforced)
async def checklist(vendor: dict) -> dict:
    onb = vendor.get("onboarding") or {}
    biz, person, legal = onb.get("business") or {}, onb.get("person") or {}, onb.get("legal") or {}
    addrs, ops, bank = onb.get("addresses") or {}, onb.get("operations") or {}, onb.get("bank") or {}
    miss = {k: [] for k in SECTIONS}

    for f, lbl in (("legal_name", "Legal business name"), ("display_name", "Store name"), ("business_type", "Business type"),
                   ("description", "Business description")):
        if not biz.get(f):
            miss["business"].append(lbl)
    if biz.get("business_type") == "other" and not biz.get("business_type_other"):
        miss["business"].append("Describe the business type")
    if not biz.get("supplier_roles"):
        miss["business"].append("Supplier role")
    if not biz.get("categories"):
        miss["business"].append("At least one product category")

    for f, lbl in (("full_name", "Full name"), ("designation", "Designation"), ("mobile", "Mobile"), ("email", "Email"),
                   ("relationship", "Relationship to the business")):
        if not person.get(f):
            miss["person"].append(lbl)
    if person.get("is_authorised_signatory") is None:
        miss["person"].append("Is this person the authorised signatory?")
    elif person.get("is_authorised_signatory") is False and not person.get("signatory_name"):
        miss["person"].append("Authorised signatory's name")

    if not legal.get("pan"):
        miss["legal"].append("PAN")
    if legal.get("gst_registered") is None:
        miss["legal"].append("Is the business GST registered?")
    elif legal.get("gst_registered") and not legal.get("gstin"):
        miss["legal"].append("GSTIN")
    elif legal.get("gst_registered") is False and not legal.get("gst_exemption_declared"):
        miss["legal"].append("GST non-registration declaration")
    if biz.get("business_type") == "llp" and not legal.get("llpin"):
        miss["legal"].append("LLPIN")
    if biz.get("business_type") in ("private_limited", "public_limited") and not legal.get("cin"):
        miss["legal"].append("CIN")

    for kind, lbl in (("registered", "Registered address"), ("pickup", "Pickup address"), ("return", "Return address")):
        if not _address_complete(resolve_address(addrs, kind)):
            miss["addresses"].append(lbl)
    if not addrs.get("pickup_contact_name"):
        miss["addresses"].append("Pickup contact name")
    if not addrs.get("pickup_contact_phone"):
        miss["addresses"].append("Pickup contact mobile")

    for f, lbl in (("handling_days", "Usual dispatch time"), ("support_phone", "Support mobile"), ("support_hours", "Support hours"),
                   ("packaging_by", "Packaging responsibility"), ("shipping_by", "Shipping responsibility")):
        if not ops.get(f):
            miss["operations"].append(lbl)

    for f, lbl in (("account_holder", "Account holder name"), ("bank_name", "Bank name"), ("account_number", "Account number"),
                   ("ifsc", "IFSC"), ("account_type", "Account type")):
        if not bank.get(f):
            miss["bank"].append(lbl)

    policy = await db.vendor_policy.find_one({"id": "vendor_policy"}, {"_id": 0}) or {}
    rules = document_rules(onb, policy.get("required_documents") or [])
    docs = await db.vendor_documents.find({"vendor_id": vendor["id"], "deleted": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(50)
    best = {}
    for d in docs:                                              # verified beats submitted beats rejected
        rank = {"verified": 3, "submitted": 2, "rejected": 1}.get(d.get("status"), 0)
        if rank > best.get(d["type"], (0, None))[0]:
            best[d["type"]] = (rank, d.get("status"))
    doc_state = {t: s for t, (_, s) in best.items()}
    for t in rules["required"] + [c["type"] for c in rules["conditional"]]:
        if doc_state.get(t) != "verified":
            state = doc_state.get(t)
            miss["documents"].append(f"{DOC_LABELS.get(t, t)}" + (" (uploaded, awaiting verification)" if state == "submitted"
                                                                   else " (rejected, upload again)" if state == "rejected" else ""))

    agreement = await db.vendor_agreements.find_one({"vendor_id": vendor["id"], "status": "approved"}, {"_id": 0},
                                                    sort=[("effective_from", -1), ("version", -1)])
    draft = None if agreement else await db.vendor_agreements.find_one({"vendor_id": vendor["id"], "status": "draft"}, {"_id": 0, "id": 1})
    if not agreement:
        miss["commercial"].append("An approved commercial agreement (finance drafts it; a second finance admin approves it)"
                                  + (" - a draft is waiting for approval" if draft else ""))

    sections = [{"key": k, "label": lbl, "complete": not miss[k], "missing": miss[k], "editable": k in EDITABLE} for k, lbl in SECTIONS.items()]
    return {"sections": sections, "complete": all(s["complete"] for s in sections), "documents": {**rules, "state": doc_state},
            "agreement": ({"id": agreement["id"], "version": agreement["version"], "commission_pct": agreement["commission_pct"],
                           "fixed_fee_paise": agreement["fixed_fee_paise"], "effective_from": agreement["effective_from"],
                           "settlement_schedule": agreement.get("settlement_schedule")} if agreement else None),
            "agreement_draft_waiting": bool(draft)}


# ------------------------------------------------------------------ creating an onboarding vendor (no login, no invitation)
async def _account_in_use(mobile: Optional[str], email: Optional[str], allow_user_id: Optional[str] = None) -> bool:
    ors = ([{"mobile": mobile}] if mobile else []) + ([{"email": email}] if email else [])
    if not ors:
        return False
    q = {"$or": ors}
    if allow_user_id:
        q["id"] = {"$ne": allow_user_id}
    return bool(await db.users.find_one(q, {"_id": 1}))


IN_USE = ("This mobile number or email already belongs to an existing HOME GENIES account. Existing accounts are never converted into "
          "vendors: use the business's own mobile number and email for the vendor owner.")


async def create_onboarding_vendor(*, business_name: str, contact_name: str, mobile: str, email: Optional[str], admin: dict,
                                   application: Optional[dict] = None, request=None) -> dict:
    """Creates the owner account (pending_approval, unusable password, no invitation) and the vendor in `onboarding`.
    Idempotent per application: a retry after an interruption finds and reuses what was already created."""
    app_id = (application or {}).get("id")
    user = await db.users.find_one({"vendor_application_id": app_id}, {"_id": 0}) if app_id else None
    if not user:
        if await _account_in_use(mobile, email):
            raise HTTPException(status_code=409, detail=IN_USE)
        code = await next_sequence("vendor", "VD", 6)
        while await db.users.find_one({"distributor_id": code}):
            code = await next_sequence("vendor", "VD", 6)
        now = now_iso()
        user = {"id": new_id(), "distributor_id": code, "full_name": contact_name.strip(), "mobile": mobile, "email": email or None,
                "password_hash": hash_password(secrets.token_urlsafe(32)), "role": "vendor", "status": VENDOR_ACCOUNT_STATUS,
                "account_status": "pending_approval", "mobile_verified": False, "email_verified": False, "kyc_status": "not_started",
                "sponsor_id": None, "sponsor_user_id": None, "created_at": now, "updated_at": now}
        if app_id:
            user["vendor_application_id"] = app_id
        try:
            await db.users.insert_one(dict(user))
        except DuplicateKeyError:
            again = await db.users.find_one({"vendor_application_id": app_id}, {"_id": 0}) if app_id else None
            if not again:
                raise HTTPException(status_code=409, detail=IN_USE)
            user = again
    vendor = await db.vendors.find_one({"user_id": user["id"]}, {"_id": 0})
    if vendor:
        return vendor
    app = application or {}
    now = now_iso()
    onboarding = {"business": {k: v for k, v in {"legal_name": business_name.strip(), "display_name": business_name.strip(),
                                                   "business_type": app.get("business_type"), "description": app.get("description"),
                                                   "categories": app.get("categories") or None, "website": app.get("website")}.items() if v},
                  "person": {k: v for k, v in {"full_name": contact_name.strip(), "mobile": mobile, "email": email}.items() if v}}
    if app.get("city") or app.get("state"):
        onboarding["addresses"] = {"registered": {k: v for k, v in {"city": app.get("city"), "state": app.get("state")}.items() if v}}
    vendor = {"id": new_id(), "user_id": user["id"], "vendor_code": user["distributor_id"], "business_name": business_name.strip(),
              "contact_person": contact_name.strip(), "phone": mobile, "support_email": email or "", "status": "onboarding",
              "onboarding_path": True, "onboarding": onboarding, "categories": app.get("categories") or [],
              "owner_activation": "not_started", "created_by": admin["id"], "created_at": now, "updated_at": now}
    if app_id:
        vendor["application_id"] = app_id
    try:
        await db.vendors.insert_one(dict(vendor))
    except DuplicateKeyError:
        return await db.vendors.find_one({"user_id": user["id"]}, {"_id": 0})
    await record_vendor_status(vendor["id"], None, "onboarding", admin["id"],
                               "Onboarding started from application " + app["number"] if app_id else "Onboarding started by HOME GENIES")
    await log_audit(admin, "vendor_onboarding_started", "vendor", vendor["id"],
                    new_value={"vendor_code": vendor["vendor_code"], "application": app.get("number")}, request=request)
    return vendor


# ------------------------------------------------------------------ owner activation (single invitation, repairable)
CLAIM_STALE = timedelta(minutes=2)


async def ensure_owner_invitation(vendor_id: str, admin: dict, request=None, resend: bool = False) -> dict:
    """After final approval: move the owner from pending_approval to invited and issue ONE invitation.
    Concurrent calls issue at most one invitation (atomic claim). A run interrupted mid-way can be repaired after CLAIM_STALE.
    `resend` explicitly replaces a pending invitation (the old link stops working)."""
    from vendor_invitations import issue
    from vendor_lifecycle import SELLING
    v = await db.vendors.find_one({"id": vendor_id}, {"_id": 0})
    if not v or v.get("status") not in SELLING:
        raise HTTPException(status_code=409, detail="The owner can be invited only after final approval.")
    owner = await db.users.find_one({"id": v["user_id"]}, {"_id": 0})
    if not owner or owner.get("role") != "vendor":
        raise HTTPException(status_code=409, detail="This vendor has no owner account.")
    if owner.get("account_status") == "active":
        await db.vendors.update_one({"id": vendor_id}, {"$set": {"owner_activation": "active"}})
        return {"status": "active", "token": None}
    stale = (datetime.now(timezone.utc) - CLAIM_STALE).isoformat()
    open_states = ["not_started", "pending", None]
    flt = {"id": vendor_id, "$or": [{"owner_activation": {"$in": open_states}}, {"owner_activation": {"$exists": False}},
                                    {"owner_activation": "issuing", "owner_activation_claimed_at": {"$lt": stale}}]}
    if resend:
        flt["$or"].append({"owner_activation": "invited"})
    claim = await db.vendors.update_one(flt, {"$set": {"owner_activation": "issuing", "owner_activation_claimed_at": now_iso()}})
    if claim.modified_count != 1:
        fresh = await db.vendors.find_one({"id": vendor_id}, {"_id": 0, "owner_activation": 1})
        return {"status": fresh.get("owner_activation"), "token": None}
    await db.users.update_one({"id": owner["id"], "account_status": {"$in": ["pending_approval", "invited"]}},
                              {"$set": {"account_status": "invited", "updated_at": now_iso()}})
    inv = await issue(owner, v, admin, request)
    await db.vendors.update_one({"id": vendor_id, "owner_activation": "issuing"},
                                {"$set": {"owner_activation": "invited", "owner_invited_at": now_iso(), "owner_invite_expires_at": inv["expires_at"]}})
    await create_notification(owner["id"], "vendor", "Welcome to HOME GENIES", "Your vendor registration is approved. Use your invitation link to set your password.")
    return {"status": "invited", **inv}


async def owner_access(vendor: dict) -> dict:
    owner = await db.users.find_one({"id": vendor["user_id"]}, {"_id": 0, "account_status": 1, "mobile": 1, "email": 1, "full_name": 1})
    inv = await db.account_invitations.find_one({"vendor_id": vendor["id"], "kind": "vendor_owner", "status": "pending"},
                                                {"_id": 0, "expires_at": 1, "created_at": 1})
    expired = bool(inv) and datetime.fromisoformat(inv["expires_at"]) <= datetime.now(timezone.utc)
    return {"account_status": (owner or {}).get("account_status"), "activation": vendor.get("owner_activation"),
            "invitation": None if not inv else {"status": "expired" if expired else "pending", "expires_at": inv["expires_at"]}}


# ------------------------------------------------------------------ views and routes
def _masked(v: str) -> str:
    v = str(v or "")
    return ("*" * max(len(v) - 4, 0)) + v[-4:] if v else ""


def _onboarding_view(v: dict) -> dict:
    onb = {k: dict(x) for k, x in (v.get("onboarding") or {}).items()}
    if onb.get("bank", {}).get("account_number"):
        onb["bank"]["account_number"] = _masked(onb["bank"]["account_number"])
    return onb


async def _require_view(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") not in VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Your role cannot view vendor onboarding.")
    return admin


async def _vendor(vid: str) -> dict:
    v = await db.vendors.find_one({"id": vid}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    return v


@router.get("/admin/vendor-onboarding/options")
async def onboarding_options(admin: dict = Depends(_require_view)):
    return {"business_types": BUSINESS_TYPES, "supplier_roles": SUPPLIER_ROLES, "relationships": RELATIONSHIPS, "account_types": ACCOUNT_TYPES,
            "responsibility": RESPONSIBILITY, "states": INDIAN_STATES, "categories": PILLARS, "sections": SECTIONS,
            "address_kinds": ADDRESS_KINDS, "same_as": SAME_AS, "document_labels": DOC_LABELS}


@router.get("/admin/vendors/{vid}/onboarding")
async def get_onboarding(vid: str, admin: dict = Depends(_require_view)):
    v = await _vendor(vid)
    history = await db.vendor_status_history.find({"vendor_id": vid}, {"_id": 0}).sort("at", 1).to_list(100)
    docs = await db.vendor_documents.find({"vendor_id": vid, "deleted": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(50)
    app = await db.vendor_applications.find_one({"id": v.get("application_id")}, {"_id": 0, "number": 1, "id": 1, "created_at": 1}) if v.get("application_id") else None
    return {"vendor": {k: v.get(k) for k in ("id", "vendor_code", "business_name", "status", "status_reason", "onboarding_path", "review_feedback",
                                             "review_feedback_at", "submitted_for_approval_at", "approved_at", "rejection_reason", "created_at")},
            "onboarding": _onboarding_view(v), "checklist": await checklist(v), "documents": docs, "history": history,
            "owner": await owner_access(v), "application": app}


@router.put("/admin/vendors/{vid}/onboarding/{section}")
async def save_section(vid: str, section: str, body: dict, request: Request, admin: dict = Depends(require_vendor_admin)):
    if section not in EDITABLE:
        raise HTTPException(status_code=400, detail="Unknown section.")
    v = await _vendor(vid)
    if v.get("status") != "onboarding":
        raise HTTPException(status_code=409, detail="This registration can be edited only while it is in onboarding.")
    current = {k: val for k, val in ((v.get("onboarding") or {}).get(section) or {}).items() if k not in ("saved_at", "saved_by")}
    given = clean_section(section, body, current)
    # Merge: fields not sent keep their saved value; a field sent empty is cleared; an address and its "same as" replace each other.
    data = {**current, **given}
    for k, val in body.items():
        if val in (None, "", []) and k not in given:
            data.pop(k, None)
    if section == "addresses":
        for kind in ADDRESS_KINDS:
            if f"{kind}_same_as" in given:
                data.pop(kind, None)
            elif kind in given:
                data.pop(f"{kind}_same_as", None)
    sets = {f"onboarding.{section}": {**data, "saved_at": now_iso(), "saved_by": admin["id"]}, "updated_at": now_iso()}
    # Keep the fields the rest of the platform already reads in step with the registration.
    if section == "business":
        if data.get("display_name"):
            sets["business_name"] = data["display_name"]
        if data.get("categories"):
            sets["categories"] = data["categories"]
    elif section == "person":
        if data.get("full_name"):
            sets["contact_person"] = data["full_name"]
        owner = await db.users.find_one({"id": v["user_id"]}, {"_id": 0})
        changes = {k: data[k] for k in ("mobile", "email") if data.get(k) and data.get(k) != (owner or {}).get(k)}
        if changes:
            if (owner or {}).get("account_status") != "pending_approval":
                raise HTTPException(status_code=409, detail="The owner's login contact cannot be changed here after approval.")
            if await _account_in_use(changes.get("mobile"), changes.get("email"), allow_user_id=v["user_id"]):
                raise HTTPException(status_code=409, detail=IN_USE)
            try:
                await db.users.update_one({"id": v["user_id"], "account_status": "pending_approval"},
                                          {"$set": {**changes, "full_name": data.get("full_name") or owner.get("full_name"), "updated_at": now_iso()}})
            except DuplicateKeyError:
                raise HTTPException(status_code=409, detail=IN_USE)
            if changes.get("mobile"):
                sets["phone"] = changes["mobile"]
    elif section == "legal":
        sets.update({"pan": data.get("pan", ""), "gstin": data.get("gstin", "")})
    elif section == "addresses":
        reg, ret = resolve_address({**data}, "registered"), resolve_address({**data}, "return")
        fmt = lambda a: ", ".join(x for x in (a.get("line1"), a.get("line2"), a.get("city"), a.get("state"), a.get("pincode")) if x) if a else ""  # noqa: E731
        sets.update({"address": fmt(reg), "city": (reg or {}).get("city", ""), "state": (reg or {}).get("state", ""),
                     "pincode": (reg or {}).get("pincode", ""), "return_address": fmt(ret)})
    elif section == "operations":
        if data.get("support_email"):
            sets["support_email"] = data["support_email"]
    elif section == "bank":
        sets.update({"bank_account_name": data.get("account_holder", ""), "bank_account": data.get("account_number", ""),
                     "ifsc": data.get("ifsc", "")})
    res = await db.vendors.update_one({"id": vid, "status": "onboarding"}, {"$set": sets})
    if res.matched_count != 1:
        raise HTTPException(status_code=409, detail="This registration just left onboarding. Reload the page.")
    logged = {k: ("(masked)" if k == "account_number" else val) for k, val in given.items()}
    await log_audit(admin, "vendor_onboarding_saved", "vendor", vid, new_value={"section": section, "fields": sorted(logged)}, request=request)
    return await get_onboarding(vid, admin)


class AdminDocIn(BaseModel):
    type: str
    url: str
    note: str = Field(default="", max_length=200)
    expires_at: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return safe_image_refs([v], 1)[0]


@router.post("/admin/vendors/{vid}/onboarding/documents")
async def add_document(vid: str, body: AdminDocIn, request: Request, admin: dict = Depends(require_vendor_admin)):
    v = await _vendor(vid)
    if v.get("status") != "onboarding":
        raise HTTPException(status_code=409, detail="Documents can be added here only while the registration is in onboarding.")
    if body.type not in DOC_LABELS:
        raise HTTPException(status_code=400, detail="Choose a document type from the list.")
    if body.expires_at:
        from pagination import is_real_date
        if not is_real_date(body.expires_at):
            raise HTTPException(status_code=400, detail="Expiry must be a date like 2027-03-31.")
    if await db.vendor_documents.count_documents({"vendor_id": vid, "deleted": {"$ne": True}}) >= 30:
        raise HTTPException(status_code=400, detail="At most 30 documents.")
    d = {"id": new_id(), "vendor_id": vid, "type": body.type, "url": body.url, "note": body.note.strip(), "expires_at": body.expires_at,
         "status": "submitted", "uploaded_by": admin["id"], "uploaded_by_admin": True, "review_note": "", "reviewed_by": None,
         "reviewed_at": None, "created_at": now_iso()}                     # verification is a separate review step
    await db.vendor_documents.insert_one(dict(d))
    await log_audit(admin, "vendor_document_added_by_admin", "vendor", vid, new_value={"type": body.type}, request=request)
    d.pop("_id", None)
    return d


@router.post("/admin/vendors/{vid}/submit-for-approval")
async def submit_for_approval(vid: str, request: Request, admin: dict = Depends(require_vendor_admin)):
    v = await _vendor(vid)
    if v.get("status") != "onboarding":
        raise HTTPException(status_code=409, detail="Only a registration in onboarding can be submitted for approval.")
    cl = await checklist(v)
    if not cl["complete"]:
        missing = [f"{s['label']}: {', '.join(s['missing'])}" for s in cl["sections"] if s["missing"]]
        raise HTTPException(status_code=400, detail={"message": "The registration is not complete yet.", "missing": missing})
    from vendor_lifecycle import admin_actor
    await move(v, "ready_for_review", admin_actor(admin), admin["id"], "Submitted for final approval",
               extra={"submitted_for_approval_by": admin["id"], "submitted_for_approval_at": now_iso()})
    await log_audit(admin, "vendor_submitted_for_approval", "vendor", vid, request=request)
    for a in await db.users.find({"role": "super_admin"}, {"_id": 0, "id": 1}).to_list(20):
        await create_notification(a["id"], "vendor", "Vendor ready for approval", f"{v['business_name']} ({v['vendor_code']}) is ready for your final review.",
                                  meta={"vendor_id": vid})
    return await get_onboarding(vid, admin)


class FinalReviewIn(BaseModel):
    action: str                                              # approve | request_changes | reject | reopen
    reason: str = Field(default="", max_length=500)


async def _require_super_admin(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can make the final vendor decision.")
    return admin


@router.post("/admin/vendors/{vid}/final-review")
async def final_review(vid: str, body: FinalReviewIn, request: Request, admin: dict = Depends(_require_super_admin)):
    v = await _vendor(vid)
    reason = body.reason.strip()
    if body.action == "approve":
        if v.get("status") != "ready_for_review":
            raise HTTPException(status_code=409, detail="Only a registration that is ready for review can be approved.")
        cl = await checklist(v)                              # re-checked at the moment of approval (e.g. a document was rejected since)
        if not cl["complete"]:
            missing = [f"{s['label']}: {', '.join(s['missing'])}" for s in cl["sections"] if s["missing"]]
            raise HTTPException(status_code=400, detail={"message": "The registration is no longer complete.", "missing": missing})
        await move(v, "approved", "super_admin", admin["id"], reason or "Final approval",
                   extra={"approved_by": admin["id"], "approved_at": now_iso(), "owner_activation": "pending", "review_feedback": ""})
        await log_audit(admin, "vendor_final_approved", "vendor", vid, request=request)
        owner = await ensure_owner_invitation(vid, admin, request)
        out = await get_onboarding(vid, admin)
        return {**out, "invitation": owner}
    if body.action in ("request_changes", "reject"):
        if len(reason) < 5:
            raise HTTPException(status_code=400, detail="Give a reason (at least 5 characters).")
        if v.get("status") != "ready_for_review":
            raise HTTPException(status_code=409, detail="Only a registration that is ready for review can be sent back or rejected.")
        if body.action == "request_changes":
            await move(v, "onboarding", "super_admin", admin["id"], reason, extra={"review_feedback": reason, "review_feedback_at": now_iso()})
        else:
            await move(v, "rejected", "super_admin", admin["id"], reason, extra={"rejection_reason": reason})
        await log_audit(admin, f"vendor_final_{body.action}", "vendor", vid, new_value={"reason": reason}, request=request)
        if v.get("submitted_for_approval_by"):
            await create_notification(v["submitted_for_approval_by"], "vendor", "Vendor registration " + ("sent back" if body.action == "request_changes" else "rejected"),
                                      f"{v['business_name']}: {reason}", meta={"vendor_id": vid})
        return await get_onboarding(vid, admin)
    if body.action == "reopen":
        if v.get("status") != "rejected" or not v.get("onboarding_path"):
            raise HTTPException(status_code=409, detail="Only a rejected onboarding registration can be reopened.")
        await move(v, "onboarding", "super_admin", admin["id"], reason or "Reopened for onboarding")
        await log_audit(admin, "vendor_onboarding_reopened", "vendor", vid, request=request)
        return await get_onboarding(vid, admin)
    raise HTTPException(status_code=400, detail="Unknown action.")


class OwnerAccessIn(BaseModel):
    resend: bool = False


@router.post("/admin/vendors/{vid}/owner-access")
async def owner_access_route(vid: str, body: OwnerAccessIn, request: Request, admin: dict = Depends(_require_super_admin)):
    """Issue the owner invitation if approval was interrupted before it, or (resend=true) replace a pending one."""
    await _vendor(vid)
    out = await ensure_owner_invitation(vid, admin, request, resend=body.resend)
    return {**out, "owner": await owner_access(await _vendor(vid))}
