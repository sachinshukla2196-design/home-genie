"""HOME GENIES - Marketplace Platform (Phase 1)."""
import os
import asyncio
import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from core import (db, client, now_iso, new_id, hash_password, verify_password,
                  get_settings, DEFAULT_SETTINGS, password_update, log_audit)
import auth_routes
import shop_routes
import wallet_routes
import admin_routes
import vendor_routes
import storage

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("homegenies")

app = FastAPI(title="HOME GENIES API")


@app.get("/api/")
async def root():
    return {"message": "HOME GENIES API"}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/health")
async def health_root():
    return {"status": "ok"}


@app.get("/api/settings/public")
async def public_settings():
    s = await get_settings()
    return {
        "commission_direct_pct": s.get("commission_direct_pct"),
        "commission_referral_pct": s.get("commission_referral_pct"),
        "commission_team_pct": s.get("commission_team_pct"),
        "return_window_days": s.get("return_window_days"),
        "point_value": s.get("point_value"),
        "cod_enabled": s.get("cod_enabled"),
        "cod_fee": s.get("cod_fee"),
        "currency_symbol": s.get("currency_symbol", "₹"),
        "gst_percent": s.get("gst_percent", 5.0),
        "company_name": s.get("company_name"),
        "company_email": s.get("company_email"),
        "company_phone": s.get("company_phone"),
    }


app.include_router(auth_routes.router)
app.include_router(shop_routes.router)
app.include_router(wallet_routes.router)
app.include_router(admin_routes.router)
app.include_router(vendor_routes.router)
app.include_router(storage.router)
import cron_routes
app.include_router(cron_routes.router)

_cors_raw = os.environ.get("CORS_ALLOWED_ORIGINS") or os.environ.get("CORS_ORIGINS", "")
_cors = [o.strip() for o in _cors_raw.split(",") if o.strip() and o.strip() != "*"]
if not _cors:
    raise RuntimeError("CORS_ORIGINS is not configured with explicit production origin(s).")


def _strong_enough(pw: str) -> bool:
    return (len(pw) >= 14 and any(c.islower() for c in pw) and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw) and any(not c.isalnum() for c in pw))


PRODUCT_SEED = []

CATEGORY_SEED = ["Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"]


# Serverless hosts (Vercel) may not run startup hooks or keep background tasks alive, so there
# DB initialisation (indexes, categories, admin seed) runs once, inline, on the first request.
ON_VERCEL = bool(os.environ.get("VERCEL"))
_init_lock = asyncio.Lock()
_init_ok = False


DB_PING_TIMEOUT = 5  # seconds; keeps an unreachable database from hanging requests past the 60 s limit


@app.middleware("http")
async def _ensure_initialised(request, call_next):
    global _init_ok
    if ON_VERCEL and not _init_ok and request.method != "OPTIONS":
        async with _init_lock:
            if not _init_ok:
                try:
                    # One quick reachability check first: when MongoDB is unreachable every init step
                    # would wait for its own server-selection timeout, adding up to a gateway timeout.
                    await asyncio.wait_for(client.admin.command("ping"), DB_PING_TIMEOUT)
                except Exception as e:
                    logger.error(f"MongoDB unreachable ({type(e).__name__}); returning 503, will retry on next request")
                    return JSONResponse({"detail": "Service temporarily unavailable. Please try again shortly."}, status_code=503)
                try:
                    await _init_db()
                    _init_ok = True
                except Exception as e:  # pragma: no cover - retried on the next request
                    logger.error(f"DB init failed ({e}); will retry on next request")
    return await call_next(request)


# Registered after the middleware above so CORS is the OUTERMOST layer: preflights are answered
# immediately, and every response (including the 503 above) carries the CORS headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    if ON_VERCEL:
        return
    # Run DB initialisation in the background so a transient Atlas hiccup
    # (e.g. "no primary available for writes" during a primary election)
    # can never crash the process before /health can respond. The pod
    # becomes ready immediately; init retries until MongoDB is reachable.
    asyncio.create_task(_run_db_init_with_retry())
    asyncio.create_task(_init_storage())


async def _init_storage():
    try:
        await asyncio.to_thread(storage.init_storage)
        logger.info("Object storage initialised")
    except Exception as e:
        logger.error("Object storage init failed: %s", e)


async def _run_db_init_with_retry():
    for attempt in range(1, 61):
        try:
            await _init_db()
            logger.info("DB initialisation complete")
            return
        except Exception as e:
            logger.error(f"DB init attempt {attempt} failed ({e}); retrying in 5s")
            await asyncio.sleep(5)
    logger.error("DB init did not complete after retries; continuing (ops will retry lazily)")


async def _safe(coro):
    """Run a single DB init step without letting one failure abort the rest."""
    try:
        await coro
    except Exception as e:
        logger.warning(f"DB init step skipped: {e}")


async def _init_db():
    # indexes
    try:
        await db.users.drop_index("email_1")
    except Exception:
        pass
    await _safe(db.users.create_index("email", unique=True, partialFilterExpression={"email": {"$type": "string"}}))
    await _safe(db.users.create_index("distributor_id", unique=True))
    await _safe(db.products.create_index("sku", unique=True))
    await _safe(db.commissions.create_index("referred_user_id"))
    await _safe(db.orders.create_index("order_number", unique=True))
    await _safe(db.wallet_transactions.create_index("user_id"))
    await _safe(db.notifications.create_index("user_id"))
    await _safe(db.otp_sessions.create_index([("identifier", 1), ("purpose", 1)]))
    await _safe(db.users.create_index("mobile", unique=True, sparse=True))

    # settings
    await get_settings()

    # products & categories — ONE-TIME bootstrap only. After the first successful
    # bootstrap a flag is set so deleted products/categories NEVER reappear on restart.
    boot = await db.business_settings.find_one({"id": "catalogue_bootstrap"})
    if not boot:
        for c in CATEGORY_SEED:
            if not await db.product_categories.find_one({"name": c}):
                await db.product_categories.insert_one({"id": new_id(), "name": c, "created_at": now_iso()})
        if await db.products.count_documents({}) == 0:
            for p in PRODUCT_SEED:
                doc = dict(p)
                doc.update({"id": new_id(), "created_at": now_iso(), "updated_at": now_iso()})
                await db.products.insert_one(doc)
        await db.business_settings.insert_one({"id": "catalogue_bootstrap", "done_at": now_iso()})

    # admin seed — credential comes strictly from the environment (no hardcoded fallback).
    # Preferred: ADMIN_PASSWORD_HASH (a bcrypt hash from backend/scripts/hash_admin_password.py), so the
    # plaintext never sits in any env store. ADMIN_PASSWORD (plaintext) is still accepted.
    admin_email = os.environ.get("ADMIN_EMAIL", "").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD")
    admin_hash = (os.environ.get("ADMIN_PASSWORD_HASH") or "").strip()
    admin_username = os.environ.get("ADMIN_USERNAME") or "admin"
    if admin_hash and not admin_hash.startswith(("$2a$", "$2b$", "$2y$")):
        logger.error("ADMIN_PASSWORD_HASH is not a bcrypt hash; ignoring it.")
        admin_hash = ""
    if not admin_email or not (admin_hash or admin_password):
        logger.error("ADMIN_EMAIL and ADMIN_PASSWORD_HASH (or ADMIN_PASSWORD) not configured; skipping admin seed.")
        return
    if admin_password and not admin_hash and not _strong_enough(admin_password):
        logger.warning("ADMIN_PASSWORD is weak (use 14+ chars with upper, lower, digit and symbol). Value not logged.")

    def _env_credential_set():
        if admin_hash:
            return {"password_hash": admin_hash, "password_changed_at": now_iso()}
        return password_update(admin_password)

    def _matches_env(stored_hash: str) -> bool:
        return stored_hash == admin_hash if admin_hash else verify_password(admin_password, stored_hash)

    existing = await db.users.find_one({"$or": [{"email": admin_email},
                                                {"role": "super_admin", "mobile": "9999999999"}]})
    if existing and existing.get("email") != admin_email:
        # owner changed ADMIN_EMAIL: move the seeded admin to the new identity
        await db.users.update_one({"id": existing["id"]},
                                  {"$set": {"email": admin_email, "updated_at": now_iso()}})
        existing["email"] = admin_email
    if not existing:
        await db.users.insert_one({
            "id": new_id(), "distributor_id": "HGADMIN001", "full_name": "Platform Administrator",
            "email": admin_email, "username": admin_username, "mobile": "9999999999",
            **_env_credential_set(),
            "role": "super_admin", "status": "green", "mobile_verified": True, "email_verified": True,
            "sponsor_id": None, "sponsor_user_id": None, "kyc_status": "verified",
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        logger.info(f"Seeded admin {admin_email}")
    elif not _matches_env(existing.get("password_hash", "")):
        # Credential rotated via env: store it and revoke sessions issued with the old password.
        await db.users.update_one({"email": admin_email},
                                  {"$set": {**_env_credential_set(), "role": "super_admin", "updated_at": now_iso()}})
        await log_audit(None, "admin_credential_rotated", "user", existing.get("id", ""))
        logger.info(f"Admin credential for {admin_email} rotated from environment; older sessions revoked.")
    # always keep the admin username in sync with env
    await db.users.update_one({"email": admin_email}, {"$set": {"username": admin_username}})

    # demo data seeder is PERMANENTLY DISABLED — demo accounts/orders will never
    # be re-created on restart, regardless of the SEED_DEMO environment variable.


@app.on_event("shutdown")
async def shutdown():
    client.close()
