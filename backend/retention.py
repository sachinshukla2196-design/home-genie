"""Programme 02 / W5: READ-ONLY retention / TTL eligibility report. Nothing here deletes, expires or changes a document or an index.

Retention periods are an owner decision (P0-05, unresolved). This module therefore states, for every collection that might one day be
expired, what the record is for, which time field governs it, whether that field could carry a TTL index at all (MongoDB TTL works
only on BSON dates; most of this code stores ISO strings), what deleting it would risk, and what value it has - and measures the data
(document count, age profile, records already past their OWN expiry field). It never proposes a number of days.

Classes:
  - "ttl in place"       : an operational TTL that already exists in db_indexes.SPECS (unchanged by W5).
  - "owner decision"     : could be expired once P0-05 sets a period (and, where `ttl_capable` is False, after a date field is added).
  - "never auto-delete"  : financial, payment, refund, settlement, identity, audit or live-recovery records. Age alone is never a reason.
"""
from datetime import datetime, timedelta, timezone

from core import db

TTL_IN_PLACE, OWNER, NEVER = "ttl in place", "owner decision", "never auto-delete"

# collection, class, purpose, time field, own expiry field, field holds BSON dates?, risk of deleting, value of keeping
CANDIDATES = [
    ("rate_limits", TTL_IN_PLACE, "fixed-window request counters", "expires_at", "expires_at", True,
     "none after the window", "none after the window"),
    ("revoked_tokens", TTL_IN_PLACE, "logged-out session ids (jti)", "expires_at", "expires_at", True,
     "none: the token is expired by then", "none after token expiry"),
    ("order_submissions", TTL_IN_PLACE, "duplicate-order submission claims", "expires_at", "expires_at", True,
     "none after the claim window", "none after the window"),
    ("otp_sessions", OWNER, "one-time passcodes (hashed) and attempt counts", "created_at", "expires_at", False,
     "deleting an unexpired record breaks verification; expired ones remove abuse-investigation evidence", "security investigation"),
    ("password_reset_tokens", OWNER, "single-use reset tokens (hashed)", "created_at", "expires_at", False,
     "none for expired tokens beyond investigation", "security investigation"),
    ("login_attempts", OWNER, "failed-login counters used for lockout", "last", None, False,
     "deleting resets a lockout (security control)", "lockout enforcement, abuse investigation"),
    ("password_reset_requests", OWNER, "admin-handled password reset requests", "created_at", None, False,
     "loses who asked for a reset and how it was handled", "account-takeover investigation (audit)"),
    ("registration_requests", OWNER, "sign-up records incl. address / Aadhaar number (personal data)", "created_at", None, False,
     "loses the registration record kept as evidence", "personal data: DPDP minimisation argues for a period; legal input"),
    ("contact_change_requests", OWNER, "admin-initiated contact changes with history", "requested_at", "expires_at", False,
     "loses identity-change history", "identity audit"),
    ("account_invitations", OWNER, "vendor owner / staff invitations (token hashes)", "created_at", "expires_at", False,
     "loses who was invited when", "vendor onboarding audit"),
    ("notifications", OWNER, "in-app messages to members / customers", "created_at", None, False,
     "members lose their message history", "customer service context"),
    ("cron_runs", OWNER, "scheduled-run records (counts, no personal data)", "created_at", None, False,
     "loses operational history; the run-id de-duplication needs recent rows", "operations evidence"),
    ("job_runs", OWNER, "repair / release sweep run records (counts)", "started_at", None, False,
     "loses repair history", "operations and reconciliation evidence"),
    ("test_sms_outbox", OWNER, "test SMS adapter outbox (codes; test servers only)", "created_at", None, False,
     "none outside tests", "none (should not exist in production)"),
    ("test_sms_notices", OWNER, "test SMS adapter notices (test servers only)", "created_at", None, False,
     "none outside tests", "none (should not exist in production)"),
    ("files", OWNER, "upload records; only soft-deleted ones (is_deleted) are candidates", "created_at", None, False,
     "a live record's image would stop being served", "evidence of uploaded documents"),
    ("job_failures", NEVER, "open repair failures (retry state)", "first_at", None, False,
     "a failing record would be forgotten and never retried", "live recovery state"),
    ("job_checkpoints", NEVER, "sweep resume points", "updated_at", None, False, "a sweep would restart or skip", "live recovery state"),
    ("index_migrations", NEVER, "index migration runs", "started_at", None, False, "loses migration history", "change audit"),
    ("stock_txns", NEVER, "stock journal (crash recovery, idempotency)", "updated_at", None, False,
     "recovery and stock audit evidence lost", "stock reconciliation evidence"),
    ("stock_movements", NEVER, "stock movement history", "created_at", None, False, "inventory audit trail lost", "inventory audit"),
    ("audit_logs", NEVER, "who did what", "created_at", None, False, "audit trail lost", "legal / audit"),
    ("orders", NEVER, "orders", "created_at", None, False, "order and tax evidence lost", "financial / tax"),
    ("payment_transactions", NEVER, "payment attempts", "created_at", None, False, "payment evidence lost", "financial"),
    ("webhook_events", NEVER, "gateway events (idempotency + evidence)", "created_at", None, False,
     "a replayed event could be processed twice; evidence lost", "financial"),
    ("payment_references", NEVER, "UPI / bank references (replay protection)", "created_at", None, False,
     "a reused reference could be accepted again", "financial"),
    ("order_refunds", NEVER, "refunds", "created_at", None, False, "refund evidence lost", "financial"),
    ("refund_cases", NEVER, "refund obligations", "created_at", None, False, "refund evidence lost", "financial"),
    ("return_cases", NEVER, "returns", "created_at", None, False, "return evidence lost", "financial"),
    ("settlements", NEVER, "vendor settlements", "created_at", None, False, "settlement evidence lost", "financial"),
    ("vendor_ledger", NEVER, "vendor ledger", "posted_at", None, False, "ledger evidence lost", "financial"),
    ("wallet_transactions", NEVER, "member wallet ledger", "created_at", None, False, "ledger evidence lost", "financial"),
    ("commissions", NEVER, "commission records", "created_at", None, False, "commission evidence lost", "financial"),
    ("withdrawal_requests", NEVER, "member withdrawals", "created_at", None, False, "payout evidence lost", "financial"),
    ("withdrawal_payout_refs", NEVER, "payout references (replay protection)", "at", None, False,
     "a payout reference could be reused", "financial"),
    ("financial_approvals", NEVER, "maker-checker approvals", "created_at", None, False, "approval evidence lost", "financial / audit"),
    ("kyc_records", NEVER, "identity / bank details", "created_at", None, False,
     "identity evidence lost; deletion is a P0-05 / L12 decision, not an age rule", "legal / identity (P0-05, W2)"),
    ("vendor_documents", NEVER, "vendor documents", "created_at", None, False, "compliance evidence lost", "legal"),
    ("vendor_agreements", NEVER, "commercial agreements", "created_at", None, False, "contract evidence lost", "legal / financial"),
]

AGES = (1, 7, 30, 90, 365)


def _cut(days: int, dates: bool):
    t = datetime.now(timezone.utc) - timedelta(days=days)
    return t if dates else t.isoformat()


async def expiry_report() -> dict:
    """Read-only. One row per candidate collection; counts only (no document content)."""
    now_dt = datetime.now(timezone.utc)
    rows = []
    for coll, cls, purpose, tfield, efield, dates, risk, value in CANDIDATES:
        n = await db[coll].count_documents({})
        row = {"collection": coll, "class": cls, "purpose": purpose, "time_field": tfield, "expiry_field": efield,
               "ttl_capable": dates, "risk_if_deleted": risk, "value": value, "documents": n,
               "decision": "P0-05" if cls == OWNER else ("—" if cls == TTL_IN_PLACE else "never (age is not a reason)")}
        if n:
            typ = {"$type": "date"} if dates else {"$type": "string"}
            row["older_than_days"] = {str(d): await db[coll].count_documents({tfield: {**typ, "$lt": _cut(d, dates)}}) for d in AGES}
            if efield:
                row["past_own_expiry"] = await db[coll].count_documents({efield: {**typ, "$lt": now_dt if dates else now_dt.isoformat()}})
            if coll == "files":
                row["soft_deleted"] = await db.files.count_documents({"is_deleted": True})
        elif efield:
            row["past_own_expiry"] = 0
        rows.append(row)
    return {"generated_at": now_dt.isoformat(), "read_only": True,
            "note": "No retention period is proposed here; periods are owner decision P0-05. TTL needs a BSON date field.",
            "collections": rows}
