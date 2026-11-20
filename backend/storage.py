"""Emergent Object Storage: image uploads for profile photos and product images."""
import os
import uuid
import logging
import asyncio
import requests
from fastapi import APIRouter, HTTPException, Request, Depends, UploadFile, File
from fastapi.responses import Response
from core import db, now_iso, new_id, get_current_user, require_admin

logger = logging.getLogger("homegenies")
router = APIRouter(prefix="/api", tags=["files"])

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
APP_NAME = "home-genies"
MAX_BYTES = 5 * 1024 * 1024
ALLOWED = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_storage_key = None


def init_storage(force: bool = False):
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    if not EMERGENT_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY is not configured")
    resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    resp.raise_for_status()
    _storage_key = resp.json()["storage_key"]
    return _storage_key


def _put(path: str, data: bytes, content_type: str) -> dict:
    for attempt in range(2):
        key = init_storage(force=attempt == 1)
        resp = requests.put(f"{STORAGE_URL}/objects/{path}",
                            headers={"X-Storage-Key": key, "Content-Type": content_type}, data=data, timeout=120)
        if resp.status_code == 404 and attempt == 0:
            continue
        resp.raise_for_status()
        return resp.json()


def _get(path: str) -> tuple[bytes, str]:
    for attempt in range(2):
        key = init_storage(force=attempt == 1)
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
        if resp.status_code == 404 and attempt == 0:
            continue
        resp.raise_for_status()
        return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


def _public_url(request: Request, path: str) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    scheme = "http" if host.startswith(("localhost", "127.0.0.1")) else "https"
    return f"{scheme}://{host}/api/files/{path}"


def sniff_image_type(data: bytes) -> str:
    """CAT-08: the real type from the file's first bytes. The browser's Content-Type header is not trusted."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


async def _upload_image(request: Request, file: UploadFile, folder: str, owner_id: str) -> str:
    ctype = (file.content_type or "").lower()
    if ctype not in ALLOWED:
        raise HTTPException(status_code=400, detail="Only JPG, PNG or WebP images are allowed.")
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image too large. Maximum size is 5 MB.")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    real = sniff_image_type(data)
    if not real:
        raise HTTPException(status_code=400, detail="This file is not a real JPG, PNG or WebP image.")
    ctype = real                        # store and serve it as what it really is
    path = f"{APP_NAME}/{folder}/{owner_id}/{uuid.uuid4()}.{ALLOWED[ctype]}"
    try:
        result = await asyncio.to_thread(_put, path, data, ctype)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        logger.error("Storage upload failed (status=%s)", status)
        if status == 439:
            raise HTTPException(status_code=507, detail="Storage quota exceeded. Please contact support.")
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")
    except Exception:
        logger.exception("Storage upload error")
        raise HTTPException(status_code=502, detail="Image upload failed. Please try again.")
    await db.files.insert_one({
        "id": new_id(), "storage_path": result["path"], "original_filename": file.filename or "",
        "content_type": ctype, "size": result.get("size", len(data)), "folder": folder,
        "owner_id": owner_id, "is_deleted": False, "created_at": now_iso(),
    })
    return _public_url(request, result["path"])


@router.post("/uploads/profile-photo")
async def upload_profile_photo(request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    url = await _upload_image(request, file, "profile", user["id"])
    return {"url": url}


@router.post("/admin/uploads/product-image")
async def upload_product_image(request: Request, file: UploadFile = File(...), admin: dict = Depends(require_admin)):
    url = await _upload_image(request, file, "products", admin["id"])
    return {"url": url}


@router.get("/files/{path:path}")
async def serve_file(path: str):
    record = await db.files.find_one({"storage_path": path, "is_deleted": False}, {"_id": 0})
    if not record:
        raise HTTPException(status_code=404, detail="File not found")
    try:
        data, ctype = await asyncio.to_thread(_get, path)
    except Exception:
        logger.exception("Storage read error")
        raise HTTPException(status_code=502, detail="Could not load file.")
    return Response(content=data, media_type=record.get("content_type") or ctype,
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})
