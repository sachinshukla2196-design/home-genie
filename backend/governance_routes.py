"""Vendor governance & service: status history, KYC documents, bank-change requests, support tickets, notifications,
account security and signed (Cloudinary) uploads.

Nothing here invents a requirement: the list of mandatory vendor documents is EMPTY until an admin configures it, and the vendor
UI says so. Sensitive files and bank details are only ever returned to the owning vendor (masked) and to admins.
"""
import hashlib
import os
import time
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from core import (db, now_iso, new_id, get_current_user, require_admin, log_audit, create_notification, next_sequence, rate_limit,
                  client_ip, verify_password, password_update, create_token, clean_user)
from pagination import clamp_page, page_meta
from validators import safe_image_refs
from vendor_routes import require_vendor_user, require_approved_vendor, _vendor_of, _mask
from vendor_history import record_vendor_status

router = APIRouter(prefix="/api", tags=["governance"])

DOC_TYPES = ("pan", "gst", "bank_proof", "address_proof", "identity", "business_registration", "other")
VENDOR_POLICY_ID = "vendor_policy"
TERMS_VERSION = os.environ.get("VENDOR_TERMS_VERSION", "1.0")


async def _notify_admins(title: str, msg: str, meta: dict = None, roles=("super_admin", "admin", "support_admin")):
    for a in await db.users.find({"role": {"$in": list(roles)}}, {"_id": 0, "id": 1}).to_list(30):
        await create_notification(a["id"], "vendor", title, msg, meta=meta)


# ================================================================== history, verification, requirements
@router.get("/vendor/me/history")
async def my_history(user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    if not v:
        return {"items": []}
    rows = await db.vendor_status_history.find({"vendor_id": v["id"]}, {"_id": 0, "internal_note": 0, "actor": 0}).sort("at", -1).to_list(200)
    return {"items": rows, "terms_version_accepted": v.get("terms_version"), "terms_version_current": TERMS_VERSION}


@router.get("/vendor/me/verification")
async def my_verification(user: dict = Depends(require_vendor_user)):
    """Honest contact-verification status: an SMS/e-mail verification provider is only 'available' if one is configured."""
    sms = os.environ.get("TWILIO_ENABLED", "").lower() == "true"
    email = bool(os.environ.get("EMERGENT_EMAIL_KEY"))
    return {"mobile": {"verified": bool(user.get("mobile_verified")), "provider_available": sms},
            "email": {"verified": bool(user.get("email_verified")), "provider_available": email},
            "note": None if (sms and email) else "Automatic contact verification is not available yet; the HOME GENIES team verifies contact details during review."}


async def get_vendor_policy() -> dict:
    return await db.vendor_policy.find_one({"id": VENDOR_POLICY_ID}, {"_id": 0}) or {"id": VENDOR_POLICY_ID, "required_documents": [], "version": 0}


@router.get("/vendor/me/requirements")
async def my_requirements(user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    pol = await get_vendor_policy()
    have = {d["type"] for d in await db.vendor_documents.find({"vendor_id": (v or {}).get("id"), "status": {"$ne": "rejected"}}, {"_id": 0, "type": 1}).to_list(50)}
    req = pol["required_documents"]
    return {"configured": bool(req), "required": req, "missing": [r for r in req if r not in have],
            "note": None if req else "HOME GENIES has not decided which documents are mandatory yet. You may upload any you have; none is required to submit."}


class PolicyIn(BaseModel):
    required_documents: List[str] = []


@router.put("/admin/vendor-policy")
async def set_vendor_policy(body: PolicyIn, request: Request, admin: dict = Depends(require_admin)):
    if admin.get("role") not in ("super_admin", "admin"):
        raise HTTPException(status_code=403, detail="Only a super admin can change vendor requirements.")
    bad = [d for d in body.required_documents if d not in DOC_TYPES]
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown document type(s): {', '.join(bad)}.")
    old = await get_vendor_policy()
    new = {"id": VENDOR_POLICY_ID, "required_documents": sorted(set(body.required_documents)), "version": old.get("version", 0) + 1,
           "updated_by": admin["id"], "updated_at": now_iso()}
    await db.vendor_policy.update_one({"id": VENDOR_POLICY_ID}, {"$set": new}, upsert=True)
    await log_audit(admin, "vendor_policy_changed", "vendor_policy", VENDOR_POLICY_ID, old_value=old.get("required_documents"), new_value=new["required_documents"], request=request)
    return new


@router.get("/admin/vendors/{vendor_id}/history")
async def admin_vendor_history(vendor_id: str, admin: dict = Depends(require_admin)):
    return {"items": await db.vendor_status_history.find({"vendor_id": vendor_id}, {"_id": 0}).sort("at", -1).to_list(300)}


# ================================================================== KYC / compliance documents
class DocIn(BaseModel):
    type: str
    url: str
    note: str = Field(default="", max_length=200)
    expires_at: Optional[str] = None

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        return safe_image_refs([v], 1)[0]


@router.get("/vendor/documents")
async def my_documents(user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    return {"items": await db.vendor_documents.find({"vendor_id": (v or {}).get("id"), "deleted": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(50)}


@router.post("/vendor/documents")
async def add_document(body: DocIn, request: Request, user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    if not v:
        raise HTTPException(status_code=404, detail="Vendor profile not found.")
    if body.type not in DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Document type must be one of: {', '.join(DOC_TYPES)}.")
    if body.expires_at:
        from pagination import is_real_date
        if not is_real_date(body.expires_at):
            raise HTTPException(status_code=400, detail="expires_at must be a date like 2027-03-31.")
    if await db.vendor_documents.count_documents({"vendor_id": v["id"], "deleted": {"$ne": True}}) >= 20:
        raise HTTPException(status_code=400, detail="At most 20 documents.")
    d = {"id": new_id(), "vendor_id": v["id"], "type": body.type, "url": body.url, "note": body.note.strip(), "expires_at": body.expires_at,
         "status": "submitted", "review_note": "", "reviewed_by": None, "reviewed_at": None, "created_at": now_iso()}   # never 'verified' from a vendor
    await db.vendor_documents.insert_one(dict(d))
    await log_audit(user, "vendor_document_added", "vendor", v["id"], new_value={"type": body.type}, request=request)
    await _notify_admins("Vendor document to review", f"{v['business_name']} uploaded a {body.type} document.", {"vendor_id": v["id"]})
    d.pop("_id", None)
    return d


@router.delete("/vendor/documents/{doc_id}")
async def remove_document(doc_id: str, user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    d = await db.vendor_documents.find_one({"id": doc_id, "vendor_id": (v or {}).get("id"), "deleted": {"$ne": True}}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found.")
    if d["status"] == "verified":
        raise HTTPException(status_code=409, detail="A verified document cannot be removed. Contact support to replace it.")
    await db.vendor_documents.update_one({"id": doc_id}, {"$set": {"deleted": True, "deleted_at": now_iso()}})   # kept for audit
    return {"ok": True}


@router.get("/admin/vendors/{vendor_id}/documents")
async def admin_vendor_documents(vendor_id: str, admin: dict = Depends(require_admin)):
    return {"items": await db.vendor_documents.find({"vendor_id": vendor_id, "deleted": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(50)}


class DocReview(BaseModel):
    status: str                       # verified | rejected
    note: str = Field(default="", max_length=300)


@router.post("/admin/vendor-documents/{doc_id}/review")
async def review_document(doc_id: str, body: DocReview, request: Request, admin: dict = Depends(require_admin)):
    if body.status not in ("verified", "rejected"):
        raise HTTPException(status_code=400, detail="status must be verified or rejected.")
    if body.status == "rejected" and len(body.note.strip()) < 5:
        raise HTTPException(status_code=400, detail="Tell the vendor what is wrong (at least 5 characters).")
    d = await db.vendor_documents.find_one({"id": doc_id, "deleted": {"$ne": True}}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found.")
    now = now_iso()
    claim = await db.vendor_documents.update_one({"id": doc_id, "status": d["status"]}, {"$set": {"status": body.status, "review_note": body.note.strip(),
                                                                                                    "reviewed_by": admin["id"], "reviewed_at": now}})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="Just updated by someone else. Refresh.")
    v = await db.vendors.find_one({"id": d["vendor_id"]}, {"_id": 0, "user_id": 1})
    await create_notification(v["user_id"], "vendor", f"Document {body.status}", f"Your {d['type']} document was {body.status}." + (f" {body.note.strip()}" if body.note.strip() else ""))
    await log_audit(admin, "vendor_document_reviewed", "vendor", d["vendor_id"], new_value={"doc": doc_id, "status": body.status}, request=request)
    return await db.vendor_documents.find_one({"id": doc_id}, {"_id": 0})


# ================================================================== bank-detail change requests (after approval)
class BankChangeIn(BaseModel):
    bank_account_name: str = Field(min_length=2, max_length=120)
    bank_account: str = Field(min_length=6, max_length=24, pattern=r"^[0-9A-Za-z]+$")
    ifsc: str = Field(pattern=r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$")
    reason: str = Field(min_length=5, max_length=200)


@router.post("/vendor/me/bank-change")
async def request_bank_change(body: BankChangeIn, request: Request, user: dict = Depends(require_approved_vendor)):
    v = user["_vendor"]
    if await db.vendor_change_requests.find_one({"vendor_id": v["id"], "kind": "bank", "status": "pending"}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="You already have a bank-detail change waiting for review.")
    r = {"id": new_id(), "vendor_id": v["id"], "kind": "bank", "payload": {"bank_account_name": body.bank_account_name.strip(),
         "bank_account": body.bank_account.strip(), "ifsc": body.ifsc.strip().upper()}, "reason": body.reason.strip(), "status": "pending",
         "admin_note": "", "created_at": now_iso()}
    await db.vendor_change_requests.insert_one(dict(r))
    await log_audit(user, "vendor_bank_change_requested", "vendor", v["id"], new_value={"ifsc": r["payload"]["ifsc"]}, request=request)
    await _notify_admins("Bank change to review", f"{v['business_name']} asked to change settlement bank details.", {"vendor_id": v["id"]}, roles=("super_admin", "accounts_admin"))
    return _bank_view(r)


def _bank_view(r: dict) -> dict:
    p = r["payload"]
    return {"id": r["id"], "status": r["status"], "reason": r["reason"], "admin_note": r.get("admin_note", ""), "created_at": r["created_at"],
            "payload": {"bank_account_name": p["bank_account_name"], "bank_account": _mask(p["bank_account"]), "ifsc": p["ifsc"]}}


@router.get("/vendor/me/bank-change")
async def my_bank_changes(user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    rows = await db.vendor_change_requests.find({"vendor_id": (v or {}).get("id"), "kind": "bank"}, {"_id": 0}).sort("created_at", -1).to_list(20)
    return {"items": [_bank_view(r) for r in rows]}


@router.get("/admin/vendor-change-requests")
async def admin_change_requests(status: str = "pending", admin: dict = Depends(require_admin)):
    rows = await db.vendor_change_requests.find({"status": status}, {"_id": 0}).sort("created_at", 1).to_list(100)
    out = []
    for r in rows:
        v = await db.vendors.find_one({"id": r["vendor_id"]}, {"_id": 0, "business_name": 1, "bank_account": 1, "bank_account_name": 1, "ifsc": 1})
        out.append({**r, "payload": {**r["payload"], "bank_account": _mask(r["payload"]["bank_account"])}, "vendor": {"business_name": (v or {}).get("business_name"),
                    "current_bank_account": _mask((v or {}).get("bank_account", "")), "current_ifsc": (v or {}).get("ifsc")}})
    return {"items": out}


class ChangeDecision(BaseModel):
    decision: str
    note: str = Field(default="", max_length=300)


@router.post("/admin/vendor-change-requests/{rid}/decision")
async def decide_change(rid: str, body: ChangeDecision, request: Request, admin: dict = Depends(require_admin)):
    if admin.get("role") not in ("super_admin", "accounts_admin"):
        raise HTTPException(status_code=403, detail="Finance access required.")
    if body.decision not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="decision must be approve or reject.")
    if body.decision == "reject" and len(body.note.strip()) < 5:
        raise HTTPException(status_code=400, detail="A reason is required.")
    r = await db.vendor_change_requests.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    to = "approved" if body.decision == "approve" else "rejected"
    claim = await db.vendor_change_requests.update_one({"id": rid, "status": "pending"}, {"$set": {"status": to, "admin_note": body.note.strip(), "decided_by": admin["id"], "decided_at": now_iso()}})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="This request was already decided.")
    if to == "approved":
        await db.vendors.update_one({"id": r["vendor_id"]}, {"$set": {**r["payload"], "updated_at": now_iso()}})
    v = await db.vendors.find_one({"id": r["vendor_id"]}, {"_id": 0, "user_id": 1})
    await create_notification(v["user_id"], "vendor", f"Bank details change {to}", f"Your request to change settlement bank details was {to}." + (f" {body.note.strip()}" if body.note.strip() else ""))
    await log_audit(admin, f"vendor_bank_change_{to}", "vendor", r["vendor_id"], new_value={"ifsc": r["payload"]["ifsc"]}, request=request)
    return {"ok": True, "status": to}


# ================================================================== support tickets
CATEGORIES = ("order", "payment", "product", "settlement", "return", "kyc", "technical", "other")
URGENT = {"payment", "settlement"}          # money problems are never 'low priority'
TICKET_FLOW = {"open": {"in_progress", "resolved", "waiting_vendor"}, "in_progress": {"resolved", "waiting_vendor", "open"},
               "waiting_vendor": {"in_progress", "resolved", "open"}, "resolved": {"closed", "open"}, "closed": set()}


class TicketIn(BaseModel):
    category: str
    subject: str = Field(min_length=3, max_length=120)
    body: str = Field(min_length=5, max_length=3000)
    priority: str = "normal"
    related_type: Optional[str] = None      # order | product | settlement | return
    related_id: Optional[str] = None
    attachments: List[str] = []

    @field_validator("attachments")
    @classmethod
    def _att(cls, v):
        return safe_image_refs(v, 5)


async def _check_related(v: dict, rtype: Optional[str], rid: Optional[str]) -> Optional[dict]:
    if not rtype and not rid:
        return None
    if not (rtype and rid):
        raise HTTPException(status_code=400, detail="Give both the related type and id, or neither.")
    q = {"order": ("orders", {"id": rid, "fulfilments.vendor_id": v["id"]}), "product": ("products", {"id": rid, "vendor_id": v["id"]}),
         "settlement": ("settlements", {"id": rid, "vendor_id": v["id"]}), "return": ("return_cases", {"id": rid, "vendor_id": v["id"]})}.get(rtype)
    if not q:
        raise HTTPException(status_code=400, detail="related_type must be order, product, settlement or return.")
    doc = await db[q[0]].find_one(q[1], {"_id": 0, "id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="The related record was not found among your own records.")
    return {"type": rtype, "id": rid}


@router.post("/vendor/support/tickets")
async def create_ticket(body: TicketIn, request: Request, user: dict = Depends(require_approved_vendor)):
    v = user["_vendor"]
    await rate_limit("support_ticket", v["id"])
    if body.category not in CATEGORIES or body.priority not in ("low", "normal", "high"):
        raise HTTPException(status_code=400, detail="Unknown category or priority.")
    rel = await _check_related(v, body.related_type, body.related_id)
    now = now_iso()
    t = {"id": new_id(), "number": await next_sequence("ticket", "TKT", 6), "vendor_id": v["id"], "vendor_name": v["business_name"], "user_id": user["id"],
         "category": body.category, "subject": body.subject.strip(), "priority": "high" if body.category in URGENT and body.priority == "low" else body.priority,
         "urgent": body.category in URGENT, "status": "open", "related": rel,
         "messages": [{"id": new_id(), "role": "vendor", "by": user["id"], "body": body.body.strip(), "attachments": body.attachments, "at": now}],
         "created_at": now, "updated_at": now, "resolution": None}
    await db.support_tickets.insert_one(dict(t))
    await _notify_admins(("URGENT: " if t["urgent"] else "") + "Vendor support ticket", f"{t['number']} from {v['business_name']}: {t['subject']}", {"ticket": t["id"]})
    await log_audit(user, "support_ticket_created", "ticket", t["id"], new_value={"category": body.category}, request=request)
    t.pop("_id", None)
    return t


@router.get("/vendor/support/tickets")
async def my_tickets(status: Optional[str] = None, page: int = 1, page_size: int = 20, user: dict = Depends(require_approved_vendor)):
    page, page_size = clamp_page(page, page_size)
    q = {"vendor_id": user["_vendor"]["id"], **({"status": status} if status else {})}
    total = await db.support_tickets.count_documents(q)
    rows = await db.support_tickets.find(q, {"_id": 0, "messages": {"$slice": -1}}).sort("updated_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": rows, **page_meta(total, page, page_size)}


async def _own_ticket(user: dict, tid: str) -> dict:
    t = await db.support_tickets.find_one({"id": tid, "vendor_id": user["_vendor"]["id"]}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return t


@router.get("/vendor/support/tickets/{tid}")
async def my_ticket(tid: str, user: dict = Depends(require_approved_vendor)):
    return await _own_ticket(user, tid)


class ReplyIn(BaseModel):
    body: str = Field(min_length=2, max_length=3000)
    attachments: List[str] = []

    @field_validator("attachments")
    @classmethod
    def _att(cls, v):
        return safe_image_refs(v, 5)


@router.post("/vendor/support/tickets/{tid}/reply")
async def vendor_reply(tid: str, body: ReplyIn, user: dict = Depends(require_approved_vendor)):
    t = await _own_ticket(user, tid)
    if t["status"] == "closed":
        raise HTTPException(status_code=409, detail="This ticket is closed. Open a new ticket if you still need help.")
    now = now_iso()
    msg = {"id": new_id(), "role": "vendor", "by": user["id"], "body": body.body.strip(), "attachments": body.attachments, "at": now}
    new_status = "open" if t["status"] in ("waiting_vendor", "resolved") else t["status"]
    await db.support_tickets.update_one({"id": tid}, {"$push": {"messages": msg}, "$set": {"updated_at": now, "status": new_status}})
    await _notify_admins("Vendor replied", f"{t['number']}: new reply from {t['vendor_name']}", {"ticket": tid})
    return await _own_ticket(user, tid)


# ----- admin side
@router.get("/admin/support/tickets")
async def admin_tickets(status: Optional[str] = None, category: Optional[str] = None, page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    page, page_size = clamp_page(page, page_size)
    q = {**({"status": status} if status else {}), **({"category": category} if category else {})}
    total = await db.support_tickets.count_documents(q)
    rows = await db.support_tickets.find(q, {"_id": 0, "messages": {"$slice": -1}}).sort([("urgent", -1), ("updated_at", -1)]).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": rows, **page_meta(total, page, page_size)}


@router.get("/admin/support/tickets/{tid}")
async def admin_ticket(tid: str, admin: dict = Depends(require_admin)):
    t = await db.support_tickets.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    return t


class AdminReply(BaseModel):
    body: str = Field(min_length=2, max_length=3000)
    status: Optional[str] = None
    resolution_note: str = Field(default="", max_length=500)


@router.post("/admin/support/tickets/{tid}/reply")
async def admin_reply(tid: str, body: AdminReply, request: Request, admin: dict = Depends(require_admin)):
    t = await db.support_tickets.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found.")
    target = body.status or ("in_progress" if t["status"] == "open" else t["status"])
    if target != t["status"] and target not in TICKET_FLOW.get(t["status"], set()):
        raise HTTPException(status_code=400, detail=f"A '{t['status']}' ticket cannot move to '{target}'.")
    if target in ("resolved", "closed") and len((body.resolution_note or "").strip()) < 5 and not t.get("resolution"):
        raise HTTPException(status_code=400, detail="Add a resolution note (at least 5 characters).")
    now = now_iso()
    sets = {"updated_at": now, "status": target}
    if target in ("resolved", "closed") and body.resolution_note.strip():
        sets["resolution"] = {"note": body.resolution_note.strip(), "by": admin["id"], "at": now}
    msg = {"id": new_id(), "role": "admin", "by": admin["id"], "body": body.body.strip(), "attachments": [], "at": now}
    claim = await db.support_tickets.update_one({"id": tid, "status": t["status"]}, {"$push": {"messages": msg}, "$set": sets})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="The ticket just changed. Refresh and try again.")
    await create_notification(t["user_id"], "vendor", "Support replied", f"{t['number']}: {body.body.strip()[:140]}", meta={"ticket": tid})
    await log_audit(admin, "support_ticket_reply", "ticket", tid, new_value={"status": target}, request=request)
    return await db.support_tickets.find_one({"id": tid}, {"_id": 0})


# ================================================================== vendor notifications
@router.get("/vendor/notifications")
async def vendor_notifications(unread: bool = False, type: Optional[str] = None, page: int = 1, page_size: int = 20, user: dict = Depends(require_vendor_user)):
    page, page_size = clamp_page(page, page_size)
    q = {"user_id": user["id"], **({"read": False} if unread else {}), **({"type": type} if type else {})}
    total = await db.notifications.count_documents(q)
    rows = await db.notifications.find(q, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": rows, "unread": await db.notifications.count_documents({"user_id": user["id"], "read": False}), **page_meta(total, page, page_size)}


# ================================================================== account security
class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.put("/auth/change-password")
async def change_password(body: ChangePasswordIn, request: Request, user: dict = Depends(get_current_user)):
    """Change your own password. All OTHER sessions are signed out (older tokens stop working); a fresh token is returned."""
    await rate_limit("change_password", user["id"])
    full = await db.users.find_one({"id": user["id"]}, {"_id": 0})
    if not verify_password(body.current_password, full.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Your current password is not correct.")
    import re
    pw = body.new_password
    strong = len(pw) >= 14 and re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw) and re.search(r"\d", pw) and re.search(r"[^A-Za-z0-9]", pw)
    if user.get("role") in ("super_admin", "admin", "accounts_admin", "support_admin") and not strong:
        raise HTTPException(status_code=400, detail="Admin passwords need 14+ characters with upper, lower, a digit and a symbol.")
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        raise HTTPException(status_code=400, detail="Use at least 8 characters with letters and numbers.")
    if verify_password(pw, full.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Choose a password you have not used just now.")
    await db.users.update_one({"id": user["id"]}, {"$set": {**password_update(pw), "updated_at": now_iso()}})
    await log_audit(user, "password_changed", "user", user["id"], request=request)
    await create_notification(user["id"], "security", "Password changed", "Your password was changed. If this was not you, contact support immediately.")
    return {"ok": True, "token": create_token(user["id"])}


# ================================================================== signed uploads (Cloudinary)
def _cloud() -> dict:
    cfg = {k: os.environ.get(f"CLOUDINARY_{k.upper()}", "").strip() for k in ("cloud_name", "api_key", "api_secret", "upload_preset")}
    return cfg


def cloudinary_signature(params: dict, secret: str) -> str:
    """Cloudinary's signing rule: SHA-1 of the sorted 'k=v' pairs joined by '&', followed by the API secret."""
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] not in (None, ""))
    return hashlib.sha1((to_sign + secret).encode()).hexdigest()


class SignIn(BaseModel):
    kind: str = "product"                 # product | document


@router.post("/vendor/uploads/sign")
async def sign_upload(body: SignIn, request: Request, user: dict = Depends(require_approved_vendor)):
    """Server-authorised direct upload: the SERVER fixes the folder, id and allowed formats; the browser only uploads the file.
    The API secret never leaves the server. Without Cloudinary configuration this returns 503 and the UI keeps the URL field."""
    cfg = _cloud()
    if not (cfg["cloud_name"] and cfg["api_key"] and cfg["api_secret"]):
        raise HTTPException(status_code=503, detail="Image upload is not configured yet. Paste an https image link instead.")
    if body.kind not in ("product", "document"):
        raise HTTPException(status_code=400, detail="kind must be product or document.")
    vid = user["_vendor"]["id"]
    await rate_limit("upload_sign", vid)
    params = {"folder": f"homegenies/vendors/{vid}/{'products' if body.kind == 'product' else 'documents'}", "public_id": new_id().replace("-", ""),
              "timestamp": int(time.time()), "overwrite": "false", "allowed_formats": "jpg,png,webp" if body.kind == "product" else "jpg,png,webp,pdf"}
    if cfg["upload_preset"]:
        params["upload_preset"] = cfg["upload_preset"]
    if body.kind == "document":
        params["type"] = "authenticated"          # documents are NOT publicly readable
    await log_audit(user, "vendor_upload_signed", "vendor", vid, new_value={"kind": body.kind}, request=request)
    return {"cloud_name": cfg["cloud_name"], "api_key": cfg["api_key"], "signature": cloudinary_signature(params, cfg["api_secret"]), "params": params,
            "upload_url": f"https://api.cloudinary.com/v1_1/{cfg['cloud_name']}/{'image' if body.kind == 'product' else 'auto'}/upload",
            "max_bytes": 5 * 1024 * 1024}


def validate_image_ownership(urls: List[str], vendor_id: str):
    """When Cloudinary is configured, a Cloudinary URL must live in THIS vendor's folder of OUR cloud (so nobody can attach
    another vendor's or a third party's asset). Other https links and local paths keep working unchanged."""
    cloud = _cloud()["cloud_name"]
    if not cloud:
        return
    for u in urls:
        p = urlparse(u)
        if p.scheme == "https" and p.hostname == "res.cloudinary.com":
            if not p.path.startswith(f"/{cloud}/image/upload/") or f"/homegenies/vendors/{vendor_id}/" not in p.path:
                raise ValueError("This Cloudinary image does not belong to your account.")
