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
    # Batch 10 (PLT-02): every authenticated request and most order/product paths look records up by `id`.
    {"coll": "users", "keys": [("id", 1)], "name": "users_id"},
    {"coll": "orders", "keys": [("id", 1)], "name": "orders_id"},
    {"coll": "products", "keys": [("id", 1)], "name": "products_id"},
    {"coll": "payment_transactions", "keys": [("session_id", 1)], "name": "payment_transactions_session"},
    {"coll": "login_attempts", "keys": [("identifier", 1)], "name": "login_attempts_identifier"},
    {"coll": "contact_change_requests", "keys": [("user_id", 1), ("status", 1)], "name": "contact_change_user_status"},
    {"coll": "products", "keys": [("sku", 1)], "name": "products_sku_unique", "unique": True},
    {"coll": "products", "keys": [("variants.sku", 1)], "name": "products_variant_sku_unique", "unique": True, "partialFilterExpression": PARTIAL_STR("variants.sku")},
    {"coll": "products", "keys": [("vendor_id", 1), ("created_at", -1)], "name": "products_vendor_created"},
    {"coll": "commissions", "keys": [("referred_user_id", 1)], "name": "commissions_referred_user"},
    {"coll": "orders", "keys": [("order_number", 1)], "name": "orders_order_number_unique", "unique": True},
    # Batch 1 (FIN-14): one record per Razorpay event, so two concurrent deliveries cannot both claim it.
    {"coll": "webhook_events", "keys": [("event_id", 1)], "name": "webhook_events_event_unique", "unique": True,
     "partialFilterExpression": PARTIAL_STR("event_id")},
    {"coll": "orders", "keys": [("payment_method", 1), ("payment_status", 1), ("status", 1), ("created_at", 1)], "name": "orders_payment_status_created"},
    {"coll": "orders", "keys": [("fulfilments.vendor_id", 1), ("created_at", -1)], "name": "orders_fulfilment_vendor_created"},
    {"coll": "stock_txns", "keys": [("key", 1)], "name": "stock_txns_key_unique", "unique": True},
    {"coll": "stock_txns", "keys": [("status", 1), ("updated_at", 1)], "name": "stock_txns_status_updated"},
    {"coll": "rate_limits", "keys": [("key", 1), ("w", 1)], "name": "rate_limits_key_window_unique", "unique": True},
    {"coll": "rate_limits", "keys": [("expires_at", 1)], "name": "rate_limits_expires", "expireAfterSeconds": 0},
    # Batch 4 (SEC-12): revoked session ids disappear once the token would have expired anyway.
    {"coll": "revoked_tokens", "keys": [("expires_at", 1)], "name": "revoked_tokens_expires", "expireAfterSeconds": 0},
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
    # Batch 12 (Phase 4): product studio drafts; ONE open draft per existing product (a race between two tabs cannot create two)
    {"coll": "product_drafts", "keys": [("id", 1)], "name": "product_drafts_id_unique", "unique": True},
    {"coll": "product_drafts", "keys": [("vendor_id", 1), ("status", 1), ("updated_at", -1)], "name": "product_drafts_vendor_status"},
    {"coll": "product_drafts", "keys": [("product_id", 1)], "name": "product_drafts_one_open_per_product", "unique": True,
     "partialFilterExpression": {"status": "draft", "product_id": {"$type": "string"}}},
    {"coll": "products", "keys": [("pending_revision.status", 1)], "name": "products_pending_revision",
     "partialFilterExpression": {"pending_revision.status": "pending"}},
    # Batch 13 (Phase 7): address book and wishlist (one row per account + product + option)
    {"coll": "addresses", "keys": [("id", 1)], "name": "addresses_id_unique", "unique": True},
    {"coll": "addresses", "keys": [("user_id", 1), ("deleted_at", 1)], "name": "addresses_user"},
    {"coll": "wishlist_items", "keys": [("user_id", 1), ("product_id", 1), ("variant_sku", 1)], "name": "wishlist_user_product_variant_unique", "unique": True},
    # Batch 13 (Phase 8): HomeGenie metrics read attributed orders / own commissions / own withdrawals by date
    {"coll": "orders", "keys": [("seller_user_id", 1), ("created_at", -1)], "name": "orders_seller_created"},
    # Batch 13 (Phase 11): catalogue search. One text index per collection (MongoDB limit); "none" = no stemming / stop words, so
    # Hindi and brand names match as typed. Filters and sorts on products that are on sale use the compound index.
    {"coll": "products", "keys": [("name", "text"), ("brand", "text"), ("keywords", "text"), ("subcategory", "text"), ("short_description", "text")],
     "name": "products_text", "weights": {"name": 10, "brand": 5, "keywords": 5, "subcategory": 3, "short_description": 1}},
    {"coll": "products", "keys": [("is_active", 1), ("approval_status", 1), ("category", 1), ("selling_price", 1)], "name": "products_shop_category_price"},
    {"coll": "merch_sections", "keys": [("status", 1), ("position", 1)], "name": "merch_sections_status_position"},
    # Batch 14: payment event reconciliation (finance inbox by status; look-up by our payment attempt)
    {"coll": "webhook_events", "keys": [("status", 1), ("created_at", -1)], "name": "webhook_events_status_created"},
    {"coll": "webhook_events", "keys": [("session_id", 1)], "name": "webhook_events_session"},
    {"coll": "commissions", "keys": [("user_id", 1), ("created_at", -1)], "name": "commissions_user_created"},
    {"coll": "withdrawal_requests", "keys": [("user_id", 1), ("created_at", -1)], "name": "withdrawal_requests_user_created"},
    # Vendor Pillar: public "Apply to sell" applications. One OPEN application per mobile (open_mobile is unset when closed),
    # and at most one vendor / one owner account per application (conversion is idempotent through these).
    {"coll": "vendor_applications", "keys": [("id", 1)], "name": "vendor_applications_id_unique", "unique": True},
    {"coll": "vendor_applications", "keys": [("number", 1)], "name": "vendor_applications_number_unique", "unique": True},
    {"coll": "vendor_applications", "keys": [("open_mobile", 1)], "name": "vendor_applications_open_mobile_unique", "unique": True,
     "partialFilterExpression": PARTIAL_STR("open_mobile")},
    {"coll": "vendor_applications", "keys": [("status", 1), ("created_at", -1)], "name": "vendor_applications_status_created"},
    {"coll": "vendors", "keys": [("application_id", 1)], "name": "vendors_application_unique", "unique": True,
     "partialFilterExpression": PARTIAL_STR("application_id")},
    {"coll": "users", "keys": [("vendor_application_id", 1)], "name": "users_vendor_application_unique", "unique": True,
     "partialFilterExpression": PARTIAL_STR("vendor_application_id")},
    # Programme 01: open-order count per account (B-006), duplicate-submission claims expire (B-006), completion markers (B-003)
    {"coll": "orders", "keys": [("user_id", 1), ("payment_status", 1)], "name": "orders_user_payment_status"},
    {"coll": "order_submissions", "keys": [("expires_at", 1)], "name": "order_submissions_expires", "expireAfterSeconds": 0},
    {"coll": "orders", "keys": [("completion_due", 1)], "name": "orders_completion_due", "partialFilterExpression": {"completion_due": True}},
    # Programme 02 / W5 — each index below serves a named query (see HOME_GENIES_DATABASE_INDEX_AND_REPAIR_AUDIT_W5.md §5 for the
    # query, its frequency and the write cost). All are additive; none is unique except the three integrity constraints at the end.
    {"coll": "stock_txns", "keys": [("id", 1)], "name": "stock_txns_id"},                         # stock._status per journal step
    {"coll": "stock_movements", "keys": [("txn_id", 1), ("line", 1)], "name": "stock_movements_txn_line"},   # _log_movement per line
    {"coll": "stock_movements", "keys": [("product_id", 1), ("created_at", -1)], "name": "stock_movements_product_created"},
    {"coll": "stock_movements", "keys": [("order_id", 1)], "name": "stock_movements_order"},
    {"coll": "commissions", "keys": [("id", 1)], "name": "commissions_id"},
    {"coll": "commissions", "keys": [("order_id", 1)], "name": "commissions_order"},
    {"coll": "order_refunds", "keys": [("id", 1)], "name": "order_refunds_id"},
    {"coll": "order_refunds", "keys": [("order_id", 1), ("created_at", 1)], "name": "order_refunds_order_created"},
    {"coll": "refund_cases", "keys": [("id", 1)], "name": "refund_cases_id"},
    {"coll": "refund_cases", "keys": [("order_id", 1), ("created_at", 1)], "name": "refund_cases_order_created"},
    {"coll": "return_cases", "keys": [("id", 1)], "name": "return_cases_id"},
    {"coll": "return_cases", "keys": [("order_id", 1), ("created_at", 1)], "name": "return_cases_order_created"},
    {"coll": "settlements", "keys": [("id", 1)], "name": "settlements_id"},
    {"coll": "withdrawal_requests", "keys": [("id", 1)], "name": "withdrawal_requests_id"},
    # Programme 03-B (P03-A02): the late-payment repair finds payments on cancelled orders whose decision was interrupted.
    {"coll": "orders", "keys": [("late_payment_due.lease_until", 1), ("id", 1)], "name": "orders_late_payment_due",
     "partialFilterExpression": {"late_payment_due": {"$exists": True}}},
    # Programme 03 (B-022): one withdrawal request per (member, idempotency key); the repair sweep finds interrupted requests.
    {"coll": "withdrawal_requests", "keys": [("user_id", 1), ("request_key", 1)], "name": "withdrawal_requests_user_key_unique",
     "unique": True, "partialFilterExpression": PARTIAL_STR("request_key")},
    {"coll": "withdrawal_requests", "keys": [("status", 1), ("id", 1)], "name": "withdrawal_requests_reserving",
     "partialFilterExpression": {"status": "reserving"}},
    {"coll": "withdrawal_requests", "keys": [("effects_due", 1), ("id", 1)], "name": "withdrawal_requests_effects_due",
     "partialFilterExpression": {"effects_due": True}},
    {"coll": "payment_transactions", "keys": [("order_id", 1), ("created_at", 1)], "name": "payment_transactions_order_created"},
    {"coll": "users", "keys": [("role", 1)], "name": "users_role"},
    {"coll": "users", "keys": [("sponsor_user_id", 1), ("status", 1)], "name": "users_sponsor_status"},
    {"coll": "referral_relationships", "keys": [("sponsor_id", 1)], "name": "referral_relationships_sponsor"},
    {"coll": "referral_relationships", "keys": [("referred_user_id", 1)], "name": "referral_relationships_referred"},
    {"coll": "referral_codes", "keys": [("code", 1)], "name": "referral_codes_code"},
    {"coll": "files", "keys": [("storage_path", 1)], "name": "files_storage_path"},              # every /api/files request
    {"coll": "audit_logs", "keys": [("entity_id", 1), ("created_at", -1)], "name": "audit_logs_entity_created"},
    {"coll": "audit_logs", "keys": [("created_at", -1)], "name": "audit_logs_created"},
    {"coll": "vendor_agreements", "keys": [("vendor_id", 1), ("status", 1), ("effective_from", -1)], "name": "vendor_agreements_vendor_status"},
    {"coll": "password_reset_tokens", "keys": [("token_hash", 1)], "name": "password_reset_tokens_hash"},
    {"coll": "orders", "keys": [("payment_status", 1), ("created_at", -1)], "name": "orders_payment_status_created_at"},
    {"coll": "job_failures", "keys": [("job", 1)], "name": "job_failures_job"},                  # read at the start of every sweep
    # Login: `{"$or": [{"email": x}, {"mobile": x}, {"distributor_id": x}]}` cannot use the PARTIAL unique e-mail index (the planner
    # does not infer `$type: string` from an equality), and one unindexed $or branch makes the whole query scan every user - on
    # every member login. A plain lookup index beside the unique one (same keys, no filter; MongoDB allows both) fixes the branch;
    # uniqueness stays with users_email_partial_unique. Admin login / team checks look users up by `username` (no index at all).
    {"coll": "users", "keys": [("email", 1)], "name": "users_email_lookup"},
    {"coll": "users", "keys": [("username", 1)], "name": "users_username"},
    # Repair sweeps that run INSIDE requests (checkout / order views run journal recovery and restock intents; the returns page runs
    # the refund-obligation sweeps). Their selections key on a rare state, but the runner sorts by `id`, so without these the planner
    # walked every order / journal row on every such request (measured: 30,000-120,000 documents examined with nothing to repair).
    # Equality / `$ne` on the leading field lets the index skip settled rows; the partial ones hold only flagged documents.
    {"coll": "stock_txns", "keys": [("finalized", 1), ("status", 1), ("updated_at", 1)], "name": "stock_txns_unfinalized"},
    {"coll": "stock_txns", "keys": [("bound", 1), ("kind", 1), ("status", 1), ("updated_at", 1)], "name": "stock_txns_unbound"},
    {"coll": "stock_txns", "keys": [("pruned", 1), ("updated_at", 1)], "name": "stock_txns_unpruned"},
    {"coll": "orders", "keys": [("updated_at", 1)], "name": "orders_restock_intents_open",
     "partialFilterExpression": {"restock_intents.0": {"$exists": True}}},
    {"coll": "orders", "keys": [("needs_refund", 1)], "name": "orders_needs_refund", "partialFilterExpression": {"needs_refund": True}},
    {"coll": "orders", "keys": [("fulfilments.refund_due", 1)], "name": "orders_fulfilment_refund_due",
     "partialFilterExpression": {"fulfilments.refund_due": True}},
    {"coll": "orders", "keys": [("refund_due_cancel", 1)], "name": "orders_refund_due_cancel", "partialFilterExpression": {"refund_due_cancel": True}},
    {"coll": "commissions", "keys": [("release.applied", 1)], "name": "commissions_release_unapplied",
     "partialFilterExpression": {"release.applied": False}},
    # integrity: one counter per sequence (two first-time upserts issued the same invoice / refund / settlement number), one cron run
    # per delivery id, one KYC record per member (a double submission created two). Each is refused by apply() while duplicates exist.
    {"coll": "counters", "keys": [("id", 1)], "name": "counters_id_unique", "unique": True},
    {"coll": "cron_runs", "keys": [("run_id", 1)], "name": "cron_runs_run_id_unique", "unique": True},
    {"coll": "kyc_records", "keys": [("user_id", 1)], "name": "kyc_records_user_unique", "unique": True},
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
    {"coll": "kyc_records", "name": "kyc_records_user", "replaced_by": "kyc_records_user_unique",
     "reason": "W5: one KYC record per member (a double submission created two); same keys, so the non-unique index must go"},
]

# Each index key pattern, with the options that define it. W5: collation is part of the definition (a case-insensitive unique
# index enforces a different rule), so an unexpected collation is a conflict, not a match.
OPTION_KEYS = ("unique", "sparse", "partialFilterExpression", "expireAfterSeconds", "collation")
TEXT_LANGUAGE = "none"                       # every text index is created without stemming / stop words (Batch 13)


def _key(spec_or_info):
    return [tuple(k) for k in (spec_or_info.get("keys") or spec_or_info.get("key") or [])]


def _options(d):
    out = {k: d[k] for k in OPTION_KEYS if k in d and d[k] is not None}
    if "collation" in out:                   # the server reports the ICU `version`; it is not an input option
        out["collation"] = {k: v for k, v in dict(out["collation"]).items() if k != "version"}
    return out


def _info_as_spec(info: dict) -> dict:
    opts = {k: info[k] for k in OPTION_KEYS if k in info}
    return {"keys": [tuple(k) for k in info["key"]], **opts}


def _is_text(spec_or_info) -> bool:
    return any(k[1] == "text" for k in _key(spec_or_info))


def _matches(info: dict, spec: dict) -> bool:
    # Batch 13: MongoDB reports a text index as ("_fts", "text") + ("_ftsx", 1) with its field weights, so it is compared by
    # its weights (which list the indexed fields) instead of its key pattern.
    # W5: the language is compared too (another default language would stem and drop stop words, changing search results).
    if _is_text(spec):
        return (_is_text(info) and info.get("weights") == spec.get("weights")
                and info.get("default_language", "english") == TEXT_LANGUAGE and "collation" not in info)
    return _key(info) == _key(spec) and _options(_info_as_spec(info)) == _options(spec)


def _same_slot(info: dict, spec: dict) -> bool:
    """True when `info` occupies the place of `spec`: same key pattern (or, for text, any text index - one per collection)."""
    return _key(info) == _key(spec) or (_is_text(spec) and _is_text(info))


async def _existing(coll: str) -> dict:
    try:
        return await db[coll].index_information()
    except Exception:                       # collection does not exist yet: no indexes
        return {}


async def plan() -> dict:
    """Read-only. Compares the database with SPECS and LEGACY."""
    existing = {c: await _existing(c) for c in {s["coll"] for s in SPECS} | {l["coll"] for l in LEGACY}}
    legacy_names = {(l["coll"], l["name"]) for l in LEGACY}
    spec_names = {(s["coll"], s["name"]) for s in SPECS}
    present, missing, conflict = [], [], []
    for s in SPECS:
        infos = existing[s["coll"]]
        # a legacy index is expected to be replaced, so it is not a conflict; another SPECIFIED index on the same keys (W5: the
        # plain e-mail lookup index beside the partial unique one) is judged under its own spec, so it is not a conflict either
        others = {n: i for n, i in infos.items() if (s["coll"], n) not in legacy_names and (s["coll"], n) not in spec_names}
        # W5: present means the index exists UNDER ITS OWN NAME with exactly this definition - the same test money_guard applies.
        # (An identical index under another name used to count as present here while the guard refused it, so apply() never
        # repaired the state and the money area stayed blocked.)
        if s["name"] in infos and _matches(infos[s["name"]], s):
            present.append(s["name"])
        elif s["name"] in infos:
            conflict.append({"index": s["name"], "collection": s["coll"], "reason": "the index exists under this name with a different definition"})
        elif any(_matches(i, s) for i in others.values()):
            other = next(n for n, i in others.items() if _matches(i, s))
            conflict.append({"index": s["name"], "collection": s["coll"],
                             "reason": f"the same definition exists under another name ({other}); rename it deliberately"})
        elif any(_same_slot(i, s) for i in others.values()):
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


def duplicate_pipeline(spec: dict, with_ids: bool = False) -> list:
    """Aggregation that yields one row per key value held by MORE THAN ONE DOCUMENT, exactly as the unique index would see it
    (W5 corrections):
      - array (multikey) fields are unwound, so a value shared by two documents' arrays is found even when the arrays differ;
        repeats inside one document's own array are not duplicates for a unique index and are not counted;
      - a missing field and an explicit null are the same key (MongoDB indexes a missing field as null);
      - the partial filter / sparse rule limits the documents considered, as it limits the index."""
    match = dict(spec.get("partialFilterExpression") or {})
    if spec.get("sparse"):
        match.update({f: {"$exists": True} for f, _ in spec["keys"]})
    pipe = [{"$match": match}]
    for prefix in sorted({f.split(".")[0] for f, _ in spec["keys"] if "." in f}):
        pipe.append({"$unwind": {"path": f"${prefix}", "preserveNullAndEmptyArrays": True}})
    for f, _ in spec["keys"]:
        if "." not in f:                     # a top-level array of scalars is multikey too
            pipe.append({"$unwind": {"path": f"${f}", "preserveNullAndEmptyArrays": True}})
    group_id = {f.replace(".", "_"): {"$ifNull": [f"${f}", None]} for f, _ in spec["keys"]}
    ident = {"$ifNull": ["$id", {"$toString": "$_id"}]}
    pipe += [{"$group": {"_id": group_id, "docs": {"$addToSet": "$_id"}, **({"ids": {"$addToSet": ident}} if with_ids else {})}},
             {"$match": {"docs.1": {"$exists": True}}}]
    return pipe


async def _duplicates(spec: dict) -> int:
    """How many key values are held by more than one document (for a unique index). Counts only."""
    rows = await db[spec["coll"]].aggregate(duplicate_pipeline(spec) + [{"$count": "dups"}]).to_list(1)
    return rows[0]["dups"] if rows else 0


def spec_version() -> str:
    """W5: a fingerprint of SPECS + LEGACY (name, collection, keys, options). Migration runs record it, so it is always known which
    definition set a database was last migrated to; any change to an index definition changes it."""
    import hashlib
    import json
    canon = [{"c": s["coll"], "n": s["name"], "k": [list(k) for k in s["keys"]], "o": _options(s), "w": s.get("weights")}
             for s in sorted(SPECS, key=lambda x: x["name"])] + [{"legacy": l["coll"] + "." + l["name"], "by": l["replaced_by"]} for l in LEGACY]
    return hashlib.sha256(json.dumps(canon, sort_keys=True, default=str).encode()).hexdigest()[:16]


async def dry_run() -> dict:
    """W5: read-only preview of apply(): every index it would create, every create it would refuse (with the number of duplicate
    key values - counts only, never the values), every legacy index it would replace, and every conflict it will leave for a
    person. Nothing is written."""
    p = await plan()
    by_name = {s["name"]: s for s in SPECS}
    legacy_by_replacement = {l["replaced_by"]: l for l in LEGACY}
    would_create, would_fail, would_replace = [], [], []
    for name in p["missing"]:
        spec = by_name[name]
        dups = await _duplicates(spec) if spec.get("unique") else 0
        row = {"index": name, "collection": spec["coll"], "keys": [list(k) for k in spec["keys"]], "options": _options(spec)}
        if dups:
            would_fail.append({**row, "duplicates": dups, "reason": "duplicate key values must be resolved by a person first"})
            continue
        would_create.append(row)
        legacy = legacy_by_replacement.get(name)
        if legacy and legacy["name"] in await _existing(spec["coll"]):
            would_replace.append({"index": legacy["name"], "collection": spec["coll"], "replaced_by": name, "reason": legacy["reason"]})
    return {"spec_version": spec_version(), "present": len(p["present"]), "would_create": would_create, "would_fail": would_fail,
            "would_replace": would_replace, "conflict": p["conflict"]}


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
            await db[spec["coll"]].create_index(spec["keys"], name=name, **_options(spec),
                                                **({"weights": spec["weights"], "default_language": TEXT_LANGUAGE} if _is_text(spec) else {}))
        except Exception as e:
            if legacy_info is not None:        # put the legacy index back exactly as it was
                await db[spec["coll"]].create_index(_key(legacy_info), name=legacy["name"], **_options(_info_as_spec(legacy_info)))
            report["failed"].append({"index": name, "collection": spec["coll"], "reason": type(e).__name__})
            continue
        report["created"].append(name)
        if legacy_info is not None:
            report["dropped"].append({"index": legacy["name"], "collection": spec["coll"], "replaced_by": name, "reason": legacy["reason"]})
    from money_guard import reset_cache       # Programme 01 (B-004): the money guard re-reads the indexes after a migration
    reset_cache()
    return report

