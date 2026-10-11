"""Rule 6 — Additional Income rules (LOCKED RATES ONLY).

The five additional income categories below have FINAL locked percentages, but their
calculation bases, qualification/clearance thresholds, recipient-allocation and stacking
rules are NOT yet defined in the business logic. Per the business spec we DO NOT guess
these — no payout is wired until the user supplies the exact definitions.

This registry exists only to (a) lock the rates in one place and (b) let the admin see
each rule's status. It performs no wallet credits.

Status values:
  PENDING_BUSINESS_CLARIFICATION — rate locked, payout NOT active (missing definitions)
"""

ADDITIONAL_INCOME_RULES = [
    {
        "key": "PERSONAL_REPURCHASE",
        "name": "Personal Repurchase Income",
        "rate_percent": 5.0,
        "trigger": "Every paid personal order AFTER the first paid purchase",
        "recipient": "The self-purchasing distributor (DEFINED)",
        "status": "IMPLEMENTED",
        "missing_definitions": [
            "Partial refunds / partial returns are NOT supported by the current order lifecycle (only full-order refund clawback is handled); confirm rules if partials are introduced later",
        ],
    },
    {
        "key": "TEAM_PURCHASE",
        "name": "Team Purchase Income",
        "rate_percent": 2.5,
        "trigger": "Eligible purchases by the distributor's eligible downline",
        "recipient": "Applicable eligible upline distributor (existing unilevel hierarchy, unlimited width/depth)",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "What makes a downline purchase eligible?",
            "What amount forms the 2.5% base, and is GST excluded?",
            "Which downline purchases count for each recipient (depth/scope)?",
            "What qualifications must the recipient satisfy?",
            "Is 2.5% payable to every eligible upline, or only a specifically qualified recipient?",
            "How does this interact/stack with the existing 45% purchase commission matrix and other income categories?",
        ],
    },
    {
        "key": "ROYALTY",
        "name": "Royalty Income",
        "rate_percent": 5.0,
        "trigger": "RD-level clearance",
        "recipient": "RD-qualified distributor",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "Exact RD qualification threshold and the precise meaning of 'RD-level clearance' (no documented, reliable definition exists)",
            "Calculation base for the 5% (company turnover / team turnover / eligible sales amount / a pool / other)",
            "Payout eligibility and recipient rules",
        ],
    },
    {
        "key": "MASTER_CLUB",
        "name": "Master Club Income",
        "rate_percent": 3.0,
        "trigger": "CD-level clearance",
        "recipient": "CD-qualified distributor",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "Exact CD qualification / clearance threshold (no documented, reliable definition exists)",
            "Calculation base for the 3%",
            "Recipient-allocation and stacking rules",
        ],
    },
    {
        "key": "SUPER_CLUB",
        "name": "Super Club Income",
        "rate_percent": 3.0,
        "trigger": "PD-level clearance",
        "recipient": "PD-qualified distributor",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "Exact PD qualification / clearance threshold (no documented, reliable definition exists)",
            "Calculation base for the 3%",
            "Recipient-allocation and stacking rules",
        ],
    },
]

# Agreed payout period for all additional incomes: monthly calculation & payout.
PAYOUT_PERIOD = "monthly"
