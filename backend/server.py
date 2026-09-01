"""Anjali Herbal Life Ayurveda - Distributor & E-Commerce Platform (Phase 1)."""
import os
import asyncio
import logging
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from core import (db, client, now_iso, new_id, hash_password, verify_password,
                  get_settings, DEFAULT_SETTINGS)
import auth_routes
import shop_routes
import wallet_routes
import admin_routes

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("anjali")

app = FastAPI(title="Anjali Herbal Life Ayurveda API")


@app.get("/api/")
async def root():
    return {"message": "Anjali Herbal Life Ayurveda API"}


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
        "activation_amount": s.get("activation_amount"),
        "referral_commission": s.get("referral_commission"),
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


PRODUCT_SEED = [
    {"sku": "ANJ-STARTER", "name": "Distributor Starter Kit", "name_hi": "डिस्ट्रीब्यूटर स्टार्टर किट",
     "description": "Official activation kit with a curated set of Ayurvedic wellness products. Qualifying purchase to activate your distributor account.",
     "description_hi": "आधिकारिक सक्रियण किट, चुनिंदा आयुर्वेदिक वेलनेस उत्पादों के साथ। डिस्ट्रीब्यूटर खाता सक्रिय करने हेतु योग्य खरीद।",
     "images": ["https://images.pexels.com/photos/7615621/pexels-photo-7615621.jpeg"],
     "mrp": 1800.0, "selling_price": 1500.0, "gst_percent": 5.0, "stock": 999,
     "category": "Starter Kit", "is_active": True, "is_activation_product": True},
    {"sku": "ANJ-ASH-01", "name": "Ashwagandha Wellness Capsules", "name_hi": "अश्वगंधा वेलनेस कैप्सूल",
     "description": "Premium Ashwagandha root extract for stress relief, energy and vitality. 60 capsules.",
     "description_hi": "तनाव राहत, ऊर्जा और जीवन शक्ति के लिए प्रीमियम अश्वगंधा रूट अर्क। 60 कैप्सूल।",
     "images": ["https://images.pexels.com/photos/4174743/pexels-photo-4174743.jpeg"],
     "mrp": 799.0, "selling_price": 649.0, "gst_percent": 5.0, "stock": 500,
     "category": "Immunity", "is_active": True, "is_activation_product": False},
    {"sku": "ANJ-CHY-01", "name": "Chyawanprash Immunity Booster", "name_hi": "च्यवनप्राश इम्युनिटी बूस्टर",
     "description": "Classical Ayurvedic Chyawanprash with 40+ herbs for natural immunity. 500g.",
     "description_hi": "प्राकृतिक इम्युनिटी के लिए 40+ जड़ी-बूटियों के साथ शास्त्रीय च्यवनप्राश। 500 ग्राम।",
     "images": ["https://images.unsplash.com/photo-1664786908163-85ca46f85138?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"],
     "mrp": 550.0, "selling_price": 449.0, "gst_percent": 5.0, "stock": 400,
     "category": "Immunity", "is_active": True, "is_activation_product": False},
    {"sku": "ANJ-TUL-01", "name": "Tulsi Green Tea", "name_hi": "तुलसी ग्रीन टी",
     "description": "Antioxidant-rich Tulsi green tea blend for daily detox and calm. 25 tea bags.",
     "description_hi": "दैनिक डिटॉक्स और शांति के लिए एंटीऑक्सीडेंट युक्त तुलसी ग्रीन टी। 25 टी बैग।",
     "images": ["https://images.pexels.com/photos/1638280/pexels-photo-1638280.jpeg"],
     "mrp": 349.0, "selling_price": 279.0, "gst_percent": 5.0, "stock": 600,
     "category": "Wellness", "is_active": True, "is_activation_product": False},
    {"sku": "ANJ-ALO-01", "name": "Aloe Vera Juice", "name_hi": "एलोवेरा जूस",
     "description": "Pure cold-pressed Aloe Vera juice for digestion and skin health. 1L.",
     "description_hi": "पाचन और त्वचा स्वास्थ्य के लिए शुद्ध कोल्ड-प्रेस्ड एलोवेरा जूस। 1 लीटर।",
     "images": ["https://images.unsplash.com/photo-1672330413099-4e57b686760d?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"],
     "mrp": 499.0, "selling_price": 399.0, "gst_percent": 5.0, "stock": 350,
     "category": "Wellness", "is_active": True, "is_activation_product": False},
    {"sku": "ANJ-HAIR-01", "name": "Herbal Hair Oil", "name_hi": "हर्बल हेयर ऑयल",
     "description": "Bhringraj & Amla enriched hair oil for stronger, healthier hair. 200ml.",
     "description_hi": "मजबूत, स्वस्थ बालों के लिए भृंगराज और आंवला युक्त हेयर ऑयल। 200ml।",
     "images": ["https://images.unsplash.com/photo-1699373381616-6133334e754e?crop=entropy&cs=srgb&fm=jpg&q=85&w=1200"],
     "mrp": 399.0, "selling_price": 329.0, "gst_percent": 5.0, "stock": 450,
     "category": "Personal Care", "is_active": True, "is_activation_product": False},
]

CATEGORY_SEED = ["Starter Kit", "Immunity", "Wellness", "Personal Care"]


@app.on_event("startup")
async def startup():
    # Run DB initialisation in the background so a transient Atlas hiccup
    # (e.g. "no primary available for writes" during a primary election)
    # can never crash the process before /health can respond. The pod
    # becomes ready immediately; init retries until MongoDB is reachable.
    asyncio.create_task(_run_db_init_with_retry())


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

    # categories
    for c in CATEGORY_SEED:
        if not await db.product_categories.find_one({"name": c}):
            await db.product_categories.insert_one({"id": new_id(), "name": c, "created_at": now_iso()})

    # products — seed ONCE only when the catalogue is empty.
    # Never re-add products that an admin deleted afterward.
    if await db.products.count_documents({}) == 0:
        for p in PRODUCT_SEED:
            doc = dict(p)
            doc.update({"id": new_id(), "created_at": now_iso(), "updated_at": now_iso()})
            await db.products.insert_one(doc)

    # admin seed
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@anjaliherballife.in").lower()
    admin_password = os.environ.get("ADMIN_PASSWORD") or "admin123"
    admin_username = os.environ.get("ADMIN_USERNAME") or "admin"
    existing = await db.users.find_one({"email": admin_email})
    if not existing:
        await db.users.insert_one({
            "id": new_id(), "distributor_id": "ANJ000000", "full_name": "Platform Administrator",
            "email": admin_email, "username": admin_username, "mobile": "9999999999",
            "password_hash": hash_password(admin_password),
            "role": "super_admin", "status": "green", "mobile_verified": True, "email_verified": True,
            "sponsor_id": None, "sponsor_user_id": None, "kyc_status": "verified",
            "created_at": now_iso(), "updated_at": now_iso(),
        })
        logger.info(f"Seeded admin {admin_email}")
    elif not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one({"email": admin_email},
                                  {"$set": {"password_hash": hash_password(admin_password),
                                            "role": "super_admin"}})
    # always keep the admin username in sync with env
    await db.users.update_one({"email": admin_email}, {"$set": {"username": admin_username}})

    # demo data seeder is PERMANENTLY DISABLED — demo accounts/orders will never
    # be re-created on restart, regardless of the SEED_DEMO environment variable.


@app.on_event("shutdown")
async def shutdown():
    client.close()
