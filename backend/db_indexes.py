"""Database indexes: the one list of what must exist, and the only code that may change them.

- `SPECS` is the complete list of required indexes. Nothing else creates or drops indexes.
- `check_missing()` is read-only. Application startup calls it and logs what is missing; it never changes an index.
- `plan()` is read-only. It reports, for every spec, whether it is present, missing or in conflict.
- `apply()` changes indexes. It is called only by the migration (scripts/vendor_foundation_migrate.py, or vendor_lifecycle.migrate with
  apply=True). It creates missing indexes, replaces the two legacy indexes listed in `LEGACY` (only after the replacement has been
  confirmed to hold no duplicates), and refuses anything else. It never deletes documents.

Reports contain counts and index names only. They never include the duplicated values (those are personal data).
"""
import logging

from core import db

logger = logging.getLogger("homegenies")

PARTIAL_STR = lambda field: {field: {"$type": "string"}}           # noqa: E731

SPECS = [
    {"coll": "users", "keys": [("email", 1)], "name": "users_email_partial_unique", "unique": True, "partialFilterExpression": PARTIAL_STR("email")},
    {"coll": "users", "keys": [("distributor_id", 1)], "name": "users_distributor_id_unique", "unique": True},
    {"coll": "users", "keys": [("mobile", 1)], "name": "users_mobile_unique", "unique": True, "sparse": True},
    {"coll": "products", "keys": [("sku", 1)], "name": "products_sku_unique", "unique": True},
    {"coll": "products", "keys": [("variants.sku", 1)], "name": "products_variant_sku_unique", "unique": True, "partialFilterExpression": PARTIAL_STR("variants.sku")},
    {"coll": "products", "keys": [("vendor_id", 1), ("created_at", -1)], "name": "products_vendor_created"},
    {"coll": "commissions", "keys": [("referred_user_id", 1)], "name": "commissions_referred_user"},
    {"coll": "orders", "keys": [("order_number", 1)], "name": "orders_order_number_unique", "unique": True},
    {"coll": "orders", "keys": [("payment_method", 1), ("payment_status", 1), ("status", 1), ("created_at", 1)], "name": "orders_payment_status_created"},
    {"coll": "orders", "keys": [("fulfilments.vendor_id", 1), ("created_at", -1)], "name": "orders_fulfilment_vendor_created"},
    {"coll": "stock_txns", "keys": [("key", 1)], "name": "stock_txns_key_unique", "unique": True},
    {"coll": "stock_txns", "keys": [("status", 1), ("updated_at", 1)], "name": "stock_txns_status_updated"},
    {"coll": "rate_limits", "keys": [("key", 1), ("w", 1)], "name": "rate_limits_key_window_unique", "unique": True},
    {"coll": "rate_limits", "keys": [("expires_at", 1)], "name": "rate_limits_expires", "expireAfterSeconds": 0},
    {"coll": "support_tickets", "keys": [("vendor_id", 1), ("updated_at", -1)], "name": "support_vendor_updated"},
    {"coll": "support_tickets", "keys": [("status", 1), ("urgent", -1), ("updated_at", -1)], "name": "support_status_urgent_updated"},
    {"coll": "vendor_documents", "keys": [("vendor_id", 1), ("created_at", -1)], "name": "vendor_documents_vendor_created"},
    {"coll": "vendor_status_history", "keys": [("vendor_id", 1), ("at", -1)], "name": "vendor_history_vendor_at"},
    {"coll": "vendor_ledger", "keys": [("source_key", 1)], "name": "vendor_ledger_source_key_unique", "unique": True},
    {"coll": "vendor_ledger", "keys": [("vendor_id", 1), ("posted_at", -1)], "name": "vendor_ledger_vendor_posted"},
    {"coll": "refund_cases", "keys": [("source_key", 1)], "name": "refund_cases_source_key_unique", "unique": True},
    {"coll": "refund_cases", "keys": [("status", 1), ("created_at", 1)], "name": "refund_cases_status_created"},
    {"coll": "return_cases", "keys": [("vendor_id", 1), ("created_at", -1)], "name": "return_cases_vendor_created"},
    {"coll": "return_cases", "keys": [("user_id", 1), ("created_at", -1)], "name": "return_cases_user_created"},
    {"coll": "settlements", "keys": [("vendor_id", 1), ("created_at", -1)], "name": "settlements_vendor_created"},
    {"coll": "settlements", "keys": [("vendor_id", 1)], "name": "settlements_one_open_per_vendor", "unique": True,
     "partialFilterExpression": {"status": {"$in": ["requested", "approved"]}}},
    {"coll": "wallet_transactions", "keys": [("user_id", 1)], "name": "wallet_transactions_user"},
    # one wallet per user: concurrent first-time creation could otherwise create two wallets and split the balance
    {"coll": "wallets", "keys": [("user_id", 1)], "name": "wallets_user_unique", "unique": True},
    # one ledger row per logical money movement (release / clawback intent); see financial_ops
    {"coll": "wallet_transactions", "keys": [("op_key", 1)], "name": "wallet_transactions_op_key_unique", "unique": True,
     "partialFilterExpression": PARTIAL_STR("op_key")},
    {"coll": "notifications", "keys": [("user_id", 1)], "name": "notifications_user"},
    {"coll": "otp_sessions", "keys": [("identifier", 1), ("purpose", 1)], "name": "otp_identifier_purpose"},
    {"coll": "vendors", "keys": [("id", 1)], "name": "vendors_id_unique", "unique": True},
    {"coll": "vendors", "keys": [("user_id", 1)], "name": "vendors_user_unique", "unique": True},
    {"coll": "vendors", "keys": [("vendor_code", 1)], "name": "vendors_code_unique", "unique": True, "partialFilterExpression": PARTIAL_STR("vendor_code")},
    {"coll": "vendor_members", "keys": [("vendor_id", 1), ("user_id", 1)], "name": "members_vendor_user_v2", "unique": True, "partialFilterExpression": PARTIAL_STR("user_id")},
    {"coll": "vendor_members", "keys": [("user_id", 1)], "name": "members_user_unique", "unique": True, "partialFilterExpression": PARTIAL_STR("user_id")},
    {"coll": "vendor_members", "keys": [("vendor_id", 1), ("status", 1)], "name": "members_vendor_status"},
    {"coll": "vendor_members", "keys": [("token_hash", 1)], "name": "members_token"},
    {"coll": "benefit_programmes", "keys": [("key", 1)], "name": "benefit_programmes_key_unique", "unique": True},
    {"coll": "benefit_grants", "keys": [("vendor_id", 1), ("programme_id", 1), ("status", 1)], "name": "benefit_grants_vendor_programme_status"},
    {"coll": "account_invitations", "keys": [("token_hash", 1)], "name": "account_invitations_token_unique", "unique": True},
    {"coll": "account_invitations", "keys": [("user_id", 1), ("status", 1)], "name": "account_invitations_user_status"},
    {"coll": "product_categories", "keys": [("name", 1)], "name": "product_categories_name_unique", "unique": True},
]

# Indexes that a spec replaces. Dropped only after the replacement is confirmed safe to create (no duplicates). A legacy index with
# the same keys as its replacement cannot coexist with it, which is why the replacement cannot simply be added beside it.
LEGACY = [
    {"coll": "users", "name": "email_1", "replaced_by": "users_email_partial_unique",
     "reason": "a non-partial e-mail index rejects several users without an e-mail address"},
    {"coll": "vendor_members", "name": "members_vendor_user_unique", "replaced_by": "members_vendor_user_v2",
     "reason": "invited members have no user yet, so the uniqueness must apply only to members who have one"},
    {"coll": "vendor_members", "name": "members_user", "replaced_by": "members_user_unique",
     "reason": "one staff login may belong to one vendor only"},
]

# Each index key pattern, with the options that define it.
OPTION_KEYS = ("unique", "sparse", "partialFilterExpression", "expireAfterSeconds")


def _key(spec_or_info):
    return [tuple(k) for k in (spec_or_info.get("keys") or spec_or_info.get("key") or [])]


def _options(d):
    return {k: d[k] for k in OPTION_KEYS if k in d and d[k] is not None}


def _info_as_spec(info: dict) -> dict:
    opts = {k: info[k] for k in OPTION_KEYS if k in info}
    return {"keys": [tuple(k) for k in info["key"]], **opts}


def _matches(info: dict, spec: dict) -> bool:
    return _key(info) == _key(spec) and _options(_info_as_spec(info)) == _options(spec)


async def _existing(coll: str) -> dict:
    try:
        return await db[coll].index_information()
    except Exception:                       # collection does not exist yet: no indexes
        return {}


async def plan() -> dict:
    """Read-only. Compares the database with SPECS and LEGACY."""
    existing = {c: await _existing(c) for c in {s["coll"] for s in SPECS} | {l["coll"] for l in LEGACY}}
    legacy_names = {(l["coll"], l["name"]) for l in LEGACY}
    present, missing, conflict = [], [], []
    for s in SPECS:
        infos = existing[s["coll"]]
        # a legacy index is expected to be replaced, so it is not a conflict
        others = {n: i for n, i in infos.items() if (s["coll"], n) not in legacy_names}
        if any(_matches(i, s) for i in infos.values()):
            present.append(s["name"])
        elif s["name"] in infos or any(_key(i) == _key(s) for i in others.values()):
            conflict.append({"index": s["name"], "collection": s["coll"], "reason": "an index on the same keys has different options or name"})
        else:
            missing.append(s["name"])
    legacy = [{"index": l["name"], "collection": l["coll"]} for l in LEGACY if l["name"] in existing[l["coll"]]]
    return {"present": present, "missing": missing, "conflict": conflict, "legacy_to_replace": legacy}


async def check_missing() -> dict:
    """Read-only, safe to run at application startup. Logs what is missing or conflicting so an operator can run the migration."""
    result = await plan()
    if result["missing"] or result["conflict"]:
        logger.error("database indexes not in the expected state: %d missing, %d in conflict. Run the migration (apply) before relying on "
                     "the unique constraints.", len(result["missing"]), len(result["conflict"]))
    return result


async def _duplicates(spec: dict) -> int:
    """How many key values are held by more than one document (for a unique index). Counts only."""
    match = dict(spec.get("partialFilterExpression") or {})
    if spec.get("sparse"):
        match.update({f: {"$exists": True} for f, _ in spec["keys"]})
    group_id = {f.replace(".", "_"): f"${f}" for f, _ in spec["keys"]}
    rows = await db[spec["coll"]].aggregate([{"$match": match}, {"$group": {"_id": group_id, "n": {"$sum": 1}}},
                                             {"$match": {"n": {"$gt": 1}}}, {"$count": "dups"}]).to_list(1)
    return rows[0]["dups"] if rows else 0


async def apply() -> dict:
    """The only function that changes indexes. Idempotent: a second run finds everything present and does nothing."""
    before = await plan()
    report = {"created": [], "present": before["present"], "dropped": [], "skipped": [], "failed": [], "conflict": before["conflict"]}
    by_name = {s["name"]: s for s in SPECS}
    legacy_by_replacement = {l["replaced_by"]: l for l in LEGACY}
    for name in before["missing"]:
        spec = by_name[name]
        if spec.get("unique"):
            dups = await _duplicates(spec)
            if dups:
                report["failed"].append({"index": name, "collection": spec["coll"], "reason": f"{dups} duplicate value(s); resolve them first. Nothing was changed."})
                continue
        legacy = legacy_by_replacement.get(name)
        legacy_info = (await _existing(spec["coll"])).get(legacy["name"]) if legacy else None
        if legacy_info is not None:            # the legacy index has the same keys, so it must go before the replacement can exist
            await db[spec["coll"]].drop_index(legacy["name"])
        try:
            await db[spec["coll"]].create_index(spec["keys"], name=name, **_options(spec))
        except Exception as e:
            if legacy_info is not None:        # put the legacy index back exactly as it was
                await db[spec["coll"]].create_index(_key(legacy_info), name=legacy["name"], **_options(_info_as_spec(legacy_info)))
            report["failed"].append({"index": name, "collection": spec["coll"], "reason": type(e).__name__})
            continue
        report["created"].append(name)
        if legacy_info is not None:
            report["dropped"].append({"index": legacy["name"], "collection": spec["coll"], "replaced_by": name, "reason": legacy["reason"]})
    return report

