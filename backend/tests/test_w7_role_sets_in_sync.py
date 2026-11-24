"""Programme 02 / W7: the frontend's copy of the server's role sets (frontend/src/lib/roles.js) must match the backend constants it
mirrors, so screens never offer an action - or fire a request - that the server refuses, and never hide one it allows.
No database; reads source constants only. Run: `pytest tests/test_w7_role_sets_in_sync.py -n 0`."""
import json
import os
import re

os.environ.setdefault("DB_NAME", "homegenies_w7_roles_test")
os.environ.setdefault("JWT_SECRET", "w7-roles-test-" + "k" * 40)

import activation_routes  # noqa: E402
import admin_order_ops  # noqa: E402
import cod_rules  # noqa: E402
import core  # noqa: E402
import finance_routes  # noqa: E402
import financial_approvals  # noqa: E402
import payment_events  # noqa: E402
import vendor_applications  # noqa: E402

ROLES_JS = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "src", "lib", "roles.js")


def frontend_sets() -> dict:
    src = open(ROLES_JS, encoding="utf-8").read()
    body = src[src.index("ROLE_SETS = {") + len("ROLE_SETS = {"): src.index("};", src.index("ROLE_SETS = {"))]
    return {m.group(1): json.loads(m.group(2)) for m in re.finditer(r"(\w+):\s*(\[[^\]]*\])", body)}


def test_every_frontend_role_set_matches_its_backend_rule():
    fe = frontend_sets()
    backend = {
        "finance": [set(finance_routes.FINANCE_ROLES), set(financial_approvals.FINANCE_ROLES), set(payment_events.FINANCE_ROLES)],
        "exportReports": [set(admin_order_ops.EXPORT_ROLES)],
        "codConfirm": [set(cod_rules.CONFIRM_ROLES)],
        "activationApprover": [set(activation_routes.APPROVER_ROLES)],
        "contentEditor": [set(core.VENDOR_ADMIN_ROLES)],
        "vendorApplications": [set(vendor_applications.VIEW_ROLES)],
        "superAdmin": [{"super_admin"}],
    }
    assert set(fe) == set(backend), (sorted(fe), sorted(backend))
    for name, rules in backend.items():
        for rule in rules:
            assert set(fe[name]) == rule, (name, fe[name], rule)


def test_every_frontend_role_is_a_real_admin_role():
    for name, roles in frontend_sets().items():
        assert set(roles) <= set(core.ADMIN_ROLES), (name, roles)
