"""Rule 6 — Additional Income rules (LOCKED RATES ONLY).

The five additional income categories below have FINAL locked percentages, but their
calculation bases, qualification/clearance thresholds, payout periods and recipient
allocation rules are NOT yet defined in the business logic. Per the business spec we
DO NOT guess these — no payout is wired until the user supplies the exact definitions.

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
        "trigger": "Eligible future personal repurchases",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "What qualifies as a 'repurchase' vs a first/activation purchase",
            "Eligible base (include/exclude GST, discounts, cancelled/refunded orders)",
            "Qualification conditions for the earner",
        ],
    },
    {
        "key": "TEAM_PURCHASE",
        "name": "Team Purchase Income",
        "rate_percent": 2.5,
        "trigger": "Eligible team purchase value",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "Eligible team purchase base and whether it excludes GST",
            "Team scope / depth counted (and relation to the existing 45% matrix)",
            "Qualification conditions and distribution method",
        ],
    },
    {
        "key": "ROYALTY",
        "name": "Royalty Income",
        "rate_percent": 5.0,
        "trigger": "RD-level clearance",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "Exact RD-level clearance condition (personal BV vs team qualification)",
            "Calculation base for the royalty",
            "Payout period and eligible recipient rules",
        ],
    },
    {
        "key": "MASTER_CLUB",
        "name": "Master Club Income",
        "rate_percent": 3.0,
        "trigger": "CD-level clearance",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "Exact CD-level clearance condition",
            "Calculation base",
            "Payout period and recipient allocation rules",
        ],
    },
    {
        "key": "SUPER_CLUB",
        "name": "Super Club Income",
        "rate_percent": 3.0,
        "trigger": "PD-level clearance",
        "status": "PENDING_BUSINESS_CLARIFICATION",
        "missing_definitions": [
            "Exact PD-level clearance condition",
            "Calculation base",
            "Payout period and recipient allocation rules",
        ],
    },
]
