"""Product information management (Batch 12, Phase 4).

One product model and one validation engine for vendors and for HOME GENIES admins:

DRAFTS (`product_drafts`)  A product (new, or a change to an existing one) is prepared as a draft: saved and resumed section by
                           section, checked for completeness at any time, then SUBMITTED. Drafts never affect the live
                           catalogue, stock, orders or money.
SUBMISSION                 - a new product is created awaiting review (the existing approval pipeline);
                           - a change to a product that is not approved yet is applied as before (back to review);
                           - a change to an APPROVED product becomes a PENDING REVISION: the approved version stays exactly as it
                             is (and stays on sale) until an admin approves the revision. Rejection or a change request leaves
                             the live product untouched and tells the vendor exactly why.
REVIEW                     super_admin / admin (the vendor-lifecycle roles) approve, reject or request changes. A product that
                           an admin prepared on a vendor's behalf cannot be approved by that same admin.
INVARIANTS                 stock is never set from a form (opening stock of a new product or new variant only; everything else
                           through the journaled stock endpoints); prices are validated (no selling price above MRP); approved
                           price changes are kept in `price_history`; every step is audited.

Tax: the GST rate and HSN code are recorded as the vendor declares them; confirming tax classification is an open owner decision
(OWNER_DECISION_REGISTER D-15), so a missing HSN code is shown to the reviewer as a warning, not invented or defaulted.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from catalogue_templates import SECTIONS, TEMPLATES
from core import (P_PUBLIC, create_notification, db, get_current_user, log_audit, new_id, now_iso, require_admin,
                  require_vendor_admin)

router = APIRouter(prefix="/api", tags=["product-information"])

MAX_IMAGES = 8
MAX_HIGHLIGHTS = 6


# ------------------------------------------------------------------ completeness (strict, used at submission and on request)
def _filled(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def _field_required(f: dict, subcategory: str) -> bool:
    r = f.get("required")
    return r is True or (isinstance(r, list) and subcategory in r)


def check_product(d: Dict[str, Any]) -> dict:
    """Section-by-section completeness of a product payload. `problems` block submission; `warnings` are for the reviewer.
    Field-level validity (types, lengths, SKU format, prices) is enforced again by the shared server validation on submit."""
    sec = {s["id"]: {"problems": [], "warnings": []} for s in SECTIONS if s["id"] != "review"}
    cat = d.get("category")
    tpl = TEMPLATES.get(cat)
    sub = (d.get("subcategory") or "").strip()
    # basics
    b = sec["basics"]
    if len((d.get("name") or "").strip()) < 2:
        b["problems"].append("Add a product title.")
    if not tpl:
        b["problems"].append("Choose a category.")
    elif not sub:
        b["problems"].append("Choose a sub-category.")
    if len((d.get("short_description") or "").strip()) < 10:
        b["problems"].append("Add a short description (at least 10 characters).")
    if len((d.get("description") or "").strip()) < 30:
        b["problems"].append("Add a full description (at least 30 characters).")
    if not (d.get("brand") or "").strip():
        b["warnings"].append("No brand given; the product will show without a brand.")
    if len(d.get("highlights") or []) > MAX_HIGHLIGHTS:
        b["problems"].append(f"At most {MAX_HIGHLIGHTS} highlights.")
    # media
    imgs = d.get("images") or []
    if not imgs:
        sec["media"]["problems"].append("Add at least one product image (the first is the main image).")
    elif len(imgs) > MAX_IMAGES:
        sec["media"]["problems"].append(f"At most {MAX_IMAGES} images.")
    alt = d.get("image_alt") or {}
    if imgs and not all(_filled(alt.get(u)) for u in imgs):
        sec["media"]["warnings"].append("Describe each image (alternative text) so every shopper can understand it.")
    # pricing
    p = sec["pricing"]
    mrp, price = d.get("mrp"), d.get("selling_price")
    if not isinstance(mrp, (int, float)) or isinstance(mrp, bool) or mrp <= 0:
        p["problems"].append("Enter the MRP.")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        p["problems"].append("Enter the selling price.")
    if isinstance(mrp, (int, float)) and isinstance(price, (int, float)) and price > mrp:
        p["problems"].append("The selling price cannot be higher than the MRP.")
    gst = d.get("gst_percent")
    if not isinstance(gst, (int, float)) or isinstance(gst, bool) or not (0 <= gst <= 28):
        p["problems"].append("Enter the GST rate that applies to this product (0-28%).")
    if not (d.get("hsn_code") or "").strip():
        p["warnings"].append("No HSN code. The tax classification must be confirmed before approval.")
    # variants & stock
    v = sec["variants"]
    variants = d.get("variants") or []
    for x in variants:
        if not (x.get("sku") or "").strip():
            v["problems"].append("Every variant needs its own SKU.")
            break
    if not (d.get("sku") or "").strip():
        v["problems"].append("Add the product SKU.")
    if not variants and not isinstance(d.get("stock"), int):
        v["problems"].append("Enter the opening stock (0 is allowed).")
    # details (category template)
    if tpl:
        attrs = d.get("attributes") or {}
        missing = [f["label"] for g in tpl["groups"] for f in g["fields"]
                   if _field_required(f, sub) and not _filled(attrs.get(f["key"]))
                   and not (f.get("variant") and variants and all(_filled((x.get("attributes") or {}).get(f["key"])) for x in variants))]
        if missing:
            sec["details"]["problems"].append("Fill in: " + ", ".join(missing) + ".")
    # shipping & returns
    s = sec["shipping"]
    pkg = d.get("package") or {}
    if not _filled(pkg.get("weight_g")):
        s["problems"].append("Enter the packed shipping weight.")
    if not _filled(pkg.get("handling_days")) and pkg.get("handling_days") != 0:
        s["problems"].append("Enter the dispatch time (days to hand the order to the courier).")
    if not all(_filled(pkg.get(k)) for k in ("length_cm", "width_cm", "height_cm")):
        s["warnings"].append("Package dimensions help the courier price shipping correctly.")
    if d.get("returnable") is False and not (d.get("return_policy") or "").strip():
        s["problems"].append("Explain why this product cannot be returned. The platform return policy still protects the customer.")
    # compliance
    c = sec["compliance"]
    if tpl:
        for flag in tpl.get("review_flags", []):
            c["warnings"].append(flag)
    out = {}
    for k, val in sec.items():
        out[k] = {**val, "status": "incomplete" if val["problems"] else ("check" if val["warnings"] else "complete")}
    blocking = sum(len(x["problems"]) for x in out.values())
    return {"ok": blocking == 0, "blocking": blocking, "sections": out}


# ------------------------------------------------------------------ template
@router.get("/pim/template")
async def pim_template(user: dict = Depends(get_current_user)):
    """The product studio's structure: sections, category templates, and the platform return policy the customer always has."""
    if user.get("role") not in ("vendor", "vendor_staff", "super_admin", "admin", "accounts_admin", "support_admin"):
        raise HTTPException(status_code=403, detail="Not available for this account.")
    from returns_routes import get_returns_policy
    policy = await get_returns_policy()
    return {"sections": SECTIONS, "templates": TEMPLATES, "max_images": MAX_IMAGES, "max_highlights": MAX_HIGHLIGHTS,
            "returns_policy": {"window_days": policy.get("window_days"), "note": "Customers keep the platform return rights whatever a listing says."}}


# ------------------------------------------------------------------ drafts
class DraftIn(BaseModel):
    product_id: Optional[str] = None           # set when the draft changes an existing product
    vendor_id: Optional[str] = None            # admin drafts only: the vendor the product belongs to
    data: Dict[str, Any] = {}
    note: str = Field(default="", max_length=300)


class DraftSave(BaseModel):
    data: Dict[str, Any]
    version: int                               # the draft version the editor started from (stale saves are refused)
    note: str = Field(default="", max_length=300)


def _draft_view(dr: dict) -> dict:
    out = {k: v for k, v in dr.items() if k != "_id"}
    out["check"] = check_product(dr.get("data") or {})
    return out


def _editable_from_product(p: dict) -> dict:
    keep = ("sku", "name", "name_hi", "description", "description_hi", "short_description", "images", "image_alt", "highlights",
            "model_number", "mrp", "selling_price", "gst_percent", "hsn_code", "stock", "low_stock_threshold", "category", "subcategory",
            "brand", "keywords", "options", "attributes", "package", "variants", "compliance_documents", "declarations", "returnable",
            "return_policy")
    return {k: p.get(k) for k in keep if k in p}


async def _new_draft(owner_vendor_id: str, actor: dict, body: DraftIn, request: Request, on_behalf: bool) -> dict:
    data = dict(body.data or {})
    if body.product_id:
        p = await db.products.find_one({"id": body.product_id, "vendor_id": owner_vendor_id}, P_PUBLIC)
        if not p:
            raise HTTPException(status_code=404, detail="Product not found.")
        if p.get("archived"):
            raise HTTPException(status_code=409, detail="Restore this product from the archive before editing it.")
        open_draft = await db.product_drafts.find_one({"product_id": body.product_id, "status": "draft"}, {"_id": 0})
        if open_draft:
            return _draft_view(open_draft)        # one open draft per product; resume it
        data = {**_editable_from_product(p), **data}
    now = now_iso()
    dr = {"id": new_id(), "vendor_id": owner_vendor_id, "product_id": body.product_id, "status": "draft", "version": 1, "data": data,
          "created_by": actor["id"], "created_by_role": actor.get("role"), "on_behalf": on_behalf, "updated_by": actor["id"],
          "created_at": now, "updated_at": now, "history": [{"at": now, "by": actor["id"], "action": "created", "note": body.note}]}
    try:
        await db.product_drafts.insert_one(dict(dr))
    except DuplicateKeyError:                    # another tab opened a draft for this product at the same moment
        return _draft_view(await db.product_drafts.find_one({"product_id": body.product_id, "status": "draft"}, {"_id": 0}))
    await log_audit(actor, "product_draft_created", "product_draft", dr["id"], new_value={"product_id": body.product_id,
                                                                                         "vendor_id": owner_vendor_id, "on_behalf": on_behalf}, request=request)
    return _draft_view(dr)


async def _save(dr: dict, body: DraftSave, actor: dict, request: Request) -> dict:
    if dr["status"] != "draft":
        raise HTTPException(status_code=409, detail="This draft was already submitted. Start a new one to make more changes.")
    data = {k: v for k, v in (body.data or {}).items() if k not in ("id", "vendor_id", "approval_status", "is_active", "archived",
                                                                     "admin_takedown", "featured", "badges", "rank_boost")}
    res = await db.product_drafts.update_one({"id": dr["id"], "status": "draft", "version": body.version},
                                             {"$set": {"data": data, "updated_by": actor["id"], "updated_at": now_iso()},
                                              "$inc": {"version": 1}})
    if res.modified_count != 1:
        raise HTTPException(status_code=409, detail="This draft was changed elsewhere (another tab or a colleague). Reload it first.")
    return _draft_view(await db.product_drafts.find_one({"id": dr["id"]}, {"_id": 0}))


async def _submit(dr: dict, actor: dict, request: Request) -> dict:
    """Validate strictly, then create the product / apply the change / store a pending revision. Exactly once per draft."""
    import vendor_routes as VR
    if dr["status"] != "draft":
        raise HTTPException(status_code=409, detail="This draft was already submitted.")
    chk = check_product(dr["data"])
    if not chk["ok"]:
        raise HTTPException(status_code=422, detail={"message": "Some required information is missing.", "check": chk})
    vendor = await db.vendors.find_one({"id": dr["vendor_id"]}, {"_id": 0})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    try:
        body = VR.VendorProductIn(**dr["data"])
    except Exception as e:                       # pydantic validation error: field-level messages
        raise HTTPException(status_code=422, detail=f"Some values are not valid: {e}")
    claim = await db.product_drafts.update_one({"id": dr["id"], "status": "draft"},
                                               {"$set": {"status": "submitting", "submitted_by": actor["id"], "submitted_at": now_iso()}})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="This draft is already being submitted.")
    try:
        if not dr.get("product_id"):
            p = await VR.create_vendor_product(vendor, body, actor, request,
                                               extra={"created_on_behalf_by": actor["id"]} if dr.get("on_behalf") else None)
            outcome = {"result": "created", "product_id": p["id"]}
        else:
            outcome = await _submit_change(dr, vendor, body, actor, request)
    except HTTPException:
        await db.product_drafts.update_one({"id": dr["id"]}, {"$set": {"status": "draft"}, "$unset": {"submitted_by": "", "submitted_at": ""}})
        raise
    await db.product_drafts.update_one({"id": dr["id"]}, {"$set": {"status": "submitted", **outcome},
                                                         "$push": {"history": {"at": now_iso(), "by": actor["id"], "action": "submitted"}}})
    await log_audit(actor, "product_draft_submitted", "product_draft", dr["id"], new_value=outcome, request=request)
    return {**outcome, "draft": _draft_view(await db.product_drafts.find_one({"id": dr["id"]}, {"_id": 0}))}


async def _submit_change(dr: dict, vendor: dict, body, actor: dict, request: Request) -> dict:
    import vendor_routes as VR
    p = await db.products.find_one({"id": dr["product_id"], "vendor_id": vendor["id"]}, P_PUBLIC)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    if p.get("approval_status") != "approved":
        # not on sale yet: the change replaces the version under review, as before
        await VR.apply_product_update(p["id"], vendor["id"], body, actor, request)
        return {"result": "updated", "product_id": p["id"]}
    data = VR._clean_product_payload(body, p.get("variants"), vendor["id"])
    changed = VR.changed_review_fields(p, data)
    if not changed:
        await VR.apply_product_update(p["id"], vendor["id"], body, actor, request)      # e.g. threshold only: no review needed
        return {"result": "updated", "product_id": p["id"]}
    rev = {"id": new_id(), "status": "pending", "data": body.model_dump(), "changed": changed, "draft_id": dr["id"],
           "submitted_by": actor["id"], "submitted_by_role": actor.get("role"), "on_behalf": bool(dr.get("on_behalf")), "submitted_at": now_iso()}
    res = await db.products.update_one({"id": p["id"], "$or": [{"pending_revision": None}, {"pending_revision": {"$exists": False}},
                                                                {"pending_revision.status": {"$ne": "pending"}}]},
                                       {"$set": {"pending_revision": rev, "updated_at": now_iso()}})
    if res.modified_count != 1:
        raise HTTPException(status_code=409, detail="A change to this product is already waiting for review.")
    await _notify_reviewers(f"Product change to review: {p['name']}", {"product_id": p["id"], "revision_id": rev["id"]})
    return {"result": "revision_pending", "product_id": p["id"], "revision_id": rev["id"]}


async def _notify_reviewers(text: str, meta: dict):
    for a in await db.users.find({"role": {"$in": ["super_admin", "admin"]}}, {"_id": 0, "id": 1}).to_list(30):
        await create_notification(a["id"], "vendor", "Product review", text, meta=meta)


# --- vendor side -------------------------------------------------------------------------------------------------
def _vendor_dep():
    from vendor_routes import require_approved_vendor
    return require_approved_vendor


async def _own_draft(user: dict, draft_id: str) -> dict:
    dr = await db.product_drafts.find_one({"id": draft_id, "vendor_id": user["_vendor"]["id"]}, {"_id": 0})
    if not dr:
        raise HTTPException(status_code=404, detail="Draft not found.")
    return dr


@router.get("/vendor/pim/drafts")
async def vendor_drafts(user: dict = Depends(_vendor_dep())):
    rows = await db.product_drafts.find({"vendor_id": user["_vendor"]["id"], "status": "draft"}, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return [{**{k: r.get(k) for k in ("id", "product_id", "version", "updated_at", "created_at", "on_behalf")},
             "name": (r.get("data") or {}).get("name") or "Untitled product", "check": check_product(r.get("data") or {})} for r in rows]


@router.post("/vendor/pim/drafts")
async def vendor_new_draft(body: DraftIn, request: Request, user: dict = Depends(_vendor_dep())):
    from vendor_staff import require_member_permission
    require_member_permission(user, "products.edit" if body.product_id else "products.create")      # Phase 5
    return await _new_draft(user["_vendor"]["id"], user, body, request, on_behalf=False)


@router.get("/vendor/pim/drafts/{draft_id}")
async def vendor_get_draft(draft_id: str, user: dict = Depends(_vendor_dep())):
    return _draft_view(await _own_draft(user, draft_id))


@router.put("/vendor/pim/drafts/{draft_id}")
async def vendor_save_draft(draft_id: str, body: DraftSave, request: Request, user: dict = Depends(_vendor_dep())):
    from vendor_staff import require_member_permission
    dr = await _own_draft(user, draft_id)
    require_member_permission(user, "products.edit" if dr.get("product_id") else "products.create")
    return await _save(dr, body, user, request)


@router.post("/vendor/pim/drafts/{draft_id}/submit")
async def vendor_submit_draft(draft_id: str, request: Request, user: dict = Depends(_vendor_dep())):
    return await _submit(await _own_draft(user, draft_id), user, request)


@router.delete("/vendor/pim/drafts/{draft_id}")
async def vendor_discard_draft(draft_id: str, request: Request, user: dict = Depends(_vendor_dep())):
    dr = await _own_draft(user, draft_id)
    res = await db.product_drafts.update_one({"id": draft_id, "status": "draft"}, {"$set": {"status": "discarded", "updated_at": now_iso()}})
    if res.modified_count != 1:
        raise HTTPException(status_code=409, detail="Only an unsubmitted draft can be discarded.")
    await log_audit(user, "product_draft_discarded", "product_draft", dr["id"], request=request)
    return {"ok": True}


@router.get("/vendor/pim/products/{product_id}/revision")
async def vendor_revision(product_id: str, user: dict = Depends(_vendor_dep())):
    p = await db.products.find_one({"id": product_id, "vendor_id": user["_vendor"]["id"]}, {"_id": 0, "pending_revision": 1, "name": 1})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    return p.get("pending_revision") or {}


# --- admin side --------------------------------------------------------------------------------------------------
@router.get("/admin/pim/drafts")
async def admin_drafts(vendor_id: Optional[str] = None, admin: dict = Depends(require_admin)):
    q: Dict[str, Any] = {"status": "draft"}
    if vendor_id:
        q["vendor_id"] = vendor_id
    rows = await db.product_drafts.find(q, {"_id": 0}).sort("updated_at", -1).to_list(200)
    return [{**{k: r.get(k) for k in ("id", "vendor_id", "product_id", "version", "updated_at", "on_behalf", "created_by")},
             "name": (r.get("data") or {}).get("name") or "Untitled product", "check": check_product(r.get("data") or {})} for r in rows]


async def _admin_draft(draft_id: str) -> dict:
    dr = await db.product_drafts.find_one({"id": draft_id}, {"_id": 0})
    if not dr:
        raise HTTPException(status_code=404, detail="Draft not found.")
    return dr


@router.post("/admin/pim/drafts")
async def admin_new_draft(body: DraftIn, request: Request, admin: dict = Depends(require_vendor_admin)):
    """An admin prepares a product ON BEHALF OF a vendor (selling vendors only). It goes through the same review; the admin who
    prepared it cannot approve it."""
    from vendor_routes import SELLING
    if not body.vendor_id:
        raise HTTPException(status_code=400, detail="Choose the vendor this product belongs to.")
    v = await db.vendors.find_one({"id": body.vendor_id}, {"_id": 0, "status": 1})
    if not v or v.get("status") not in SELLING:
        raise HTTPException(status_code=409, detail="Products can be added only for an approved, selling vendor.")
    return await _new_draft(body.vendor_id, admin, body, request, on_behalf=True)


@router.get("/admin/pim/drafts/{draft_id}")
async def admin_get_draft(draft_id: str, admin: dict = Depends(require_admin)):
    return _draft_view(await _admin_draft(draft_id))


@router.put("/admin/pim/drafts/{draft_id}")
async def admin_save_draft(draft_id: str, body: DraftSave, request: Request, admin: dict = Depends(require_vendor_admin)):
    dr = await _admin_draft(draft_id)
    if not dr.get("on_behalf"):
        raise HTTPException(status_code=403, detail="This is the vendor's own draft. Ask the vendor to change it.")
    return await _save(dr, body, admin, request)


@router.post("/admin/pim/drafts/{draft_id}/submit")
async def admin_submit_draft(draft_id: str, request: Request, admin: dict = Depends(require_vendor_admin)):
    dr = await _admin_draft(draft_id)
    if not dr.get("on_behalf"):
        raise HTTPException(status_code=403, detail="This is the vendor's own draft. The vendor submits it.")
    return await _submit(dr, admin, request)


@router.get("/admin/pim/revisions")
async def admin_revisions(admin: dict = Depends(require_admin)):
    rows = await db.products.find({"pending_revision.status": "pending"}, P_PUBLIC).sort("updated_at", -1).to_list(300)
    return [{"product": {k: p.get(k) for k in ("id", "name", "sku", "vendor_id", "vendor_name", "category", "images", "mrp", "selling_price",
                                                "approval_status", "is_active")},
             "revision": p["pending_revision"]} for p in rows]


@router.get("/admin/pim/products/{product_id}/revision")
async def admin_revision(product_id: str, admin: dict = Depends(require_admin)):
    p = await db.products.find_one({"id": product_id}, P_PUBLIC)
    if not p or not p.get("pending_revision"):
        raise HTTPException(status_code=404, detail="No change is waiting for this product.")
    rev = p["pending_revision"]
    diff = {k: {"live": p.get(k), "proposed": rev["data"].get(k)} for k in rev.get("changed", [])}
    return {"product": p, "revision": rev, "diff": diff, "check": check_product(rev["data"])}


class RevisionDecision(BaseModel):
    action: str                                  # approve | reject | request_changes
    reason: str = Field(default="", max_length=500)


@router.post("/admin/pim/products/{product_id}/revision/decision")
async def admin_revision_decision(product_id: str, body: RevisionDecision, request: Request, admin: dict = Depends(require_vendor_admin)):
    import vendor_routes as VR
    p = await db.products.find_one({"id": product_id}, P_PUBLIC)
    rev = (p or {}).get("pending_revision")
    if not p or not rev or rev.get("status") != "pending":
        raise HTTPException(status_code=404, detail="No change is waiting for this product.")
    if body.action not in ("approve", "reject", "request_changes"):
        raise HTTPException(status_code=400, detail="Unknown action.")
    if body.action != "approve" and len(body.reason.strip()) < 5:
        raise HTTPException(status_code=400, detail="Tell the vendor what to change (at least 5 characters).")
    if body.action == "approve" and rev.get("submitted_by") == admin["id"]:
        raise HTTPException(status_code=403, detail="You prepared this change, so a different admin must approve it.")
    now = now_iso()
    claim = await db.products.update_one({"id": product_id, "pending_revision.id": rev["id"], "pending_revision.status": "pending"},
                                         {"$set": {"pending_revision.status": "applying" if body.action == "approve" else
                                                   ("rejected" if body.action == "reject" else "changes_requested"),
                                                   "pending_revision.decided_by": admin["id"], "pending_revision.decided_at": now,
                                                   "pending_revision.reason": body.reason.strip()}})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="This change was just decided by someone else.")
    if body.action == "approve":
        model = VR.VendorProductIn(**rev["data"])
        try:
            await VR.apply_product_update(product_id, p["vendor_id"], model, admin, request, review=False, price_note=f"revision {rev['id']}")
        except HTTPException:
            await db.products.update_one({"id": product_id, "pending_revision.id": rev["id"]}, {"$set": {"pending_revision.status": "pending"},
                                                                                              "$unset": {"pending_revision.decided_by": ""}})
            raise
        await db.products.update_one({"id": product_id, "pending_revision.id": rev["id"]},
                                     {"$set": {"pending_revision.status": "approved", "reviewed_by": admin["id"], "reviewed_at": now}})
    v = await db.vendors.find_one({"id": p["vendor_id"]}, {"_id": 0, "user_id": 1})
    if v:
        text = {"approve": f"Your changes to {p['name']} were approved and are live.",
                "reject": f"Your changes to {p['name']} were not approved: {body.reason.strip()}. The product stays on sale as before.",
                "request_changes": f"Please update your changes to {p['name']}: {body.reason.strip()}. The product stays on sale as before."}[body.action]
        await create_notification(v["user_id"], "vendor", "Product review", text, meta={"product_id": product_id})
    await log_audit(admin, f"product_revision_{body.action}", "product", product_id,
                    new_value={"revision_id": rev["id"], "changed": rev.get("changed"), "reason": body.reason.strip()}, request=request)
    return await db.products.find_one({"id": product_id}, P_PUBLIC)


@router.get("/admin/pim/products/{product_id}/price-history")
async def admin_price_history(product_id: str, admin: dict = Depends(require_admin)):
    p = await db.products.find_one({"id": product_id}, {"_id": 0, "price_history": 1})
    if p is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    return p.get("price_history") or []


def section_list() -> List[str]:
    return [s["id"] for s in SECTIONS]
