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
        "definition": "Monthly on the 1st: each distributor at EXACT rank earns rate% of OWN team's previous-month paid turnover (subtotal excl GST, all downline levels). Auto via cron + admin preview/distribute.",
    },
    {
        "key": "TEAM_PURCHASE",
        "name": "Team Purchase Income",
        "rate_percent": 2.5,
        "trigger": "Product purchases by the direct (level-1) downline team",
        "recipient": "The direct sponsor (must be GREEN/active)",
        "status": "IMPLEMENTED",
        "definition": "Monthly on the 1st: each distributor at EXACT rank earns rate% of OWN team's previous-month paid turnover (subtotal excl GST, all downline levels). Auto via cron + admin preview/distribute.",
    },
    {
        "key": "ROYALTY",
        "name": "Royalty Income",
        "rate_percent": 5.0,
        "trigger": "RD-level clearance",
        "recipient": "RD-qualified distributor",
        "status": "IMPLEMENTED",
        "definition": "Monthly on the 1st: each distributor at EXACT rank earns rate% of OWN team's previous-month paid turnover (subtotal excl GST, all downline levels). Auto via cron + admin preview/distribute.",
    },
    {
        "key": "MASTER_CLUB",
        "name": "Master Club Income",
        "rate_percent": 3.0,
        "trigger": "CD-level clearance",
        "recipient": "CD-qualified distributor",
        "status": "IMPLEMENTED",
        "definition": "Monthly on the 1st: each distributor at EXACT rank earns rate% of OWN team's previous-month paid turnover (subtotal excl GST, all downline levels). Auto via cron + admin preview/distribute.",
    },
    {
        "key": "SUPER_CLUB",
        "name": "Super Club Income",
        "rate_percent": 3.0,
        "trigger": "PD-level clearance",
        "recipient": "PD-qualified distributor",
        "status": "IMPLEMENTED",
        "definition": "Monthly on the 1st: each distributor at EXACT rank earns rate% of OWN team's previous-month paid turnover (subtotal excl GST, all downline levels). Auto via cron + admin preview/distribute.",
    },
]

# Agreed payout period for all additional incomes: monthly calculation & payout.
PAYOUT_PERIOD = "monthly"
