"""Programme 01 / B-008: vendor contact state validation accepts the representations the application already holds
(canonical names, two-letter codes on older records) and still rejects anything else.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL. Run alone: `pytest tests/test_programme01_vendor_state.py -n 0`.
"""
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_vendor_state_test", "JWT_SECRET": "p01-vendor-state-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
from vendor_onboarding import normalise_indian_state, state_name, INDIAN_STATES  # noqa: E402

CONTACT = {"business_name": "Ignored", "contact_person": "Owner", "phone": "9876500010", "address": "12 Market Road",
           "city": "Jaipur", "state": "RJ", "pincode": "302001", "categories": ["Sarees"], "submit": False}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _vendor(c, vid):
    return c.portal.call(lambda: db.vendors.find_one({"id": vid}, {"_id": 0}))


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()

            async def user(mobile, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Vendor-Pass-123"), "role": "vendor", "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, code, status, state):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": code, "business_name": code, "status": status,
                     "state": state, "city": "Jaipur", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v

            S["a_u"] = await user("9100008101", "P1A")
            S["a"] = await vendor(S["a_u"], "VS000001", "approved", "RJ")          # legacy code on the stored record
            S["b_u"] = await user("9100008102", "P1B")
            S["b"] = await vendor(S["b_u"], "VS000002", "active", "Karnataka")
            S["d_u"] = await user("9100008103", "P1D")
            S["d"] = await vendor(S["d_u"], "VS000003", "draft", "")
            S["untouched_u"] = await user("9100008104", "P1U")
            S["untouched"] = await vendor(S["untouched_u"], "VS000004", "approved", "MH")
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


# ---------------------------------------------------------------- pure normaliser
@pytest.mark.parametrize("raw,expected", [("RJ", "RJ"), ("rj", "RJ"), (" KA ", "KA"), ("TS", "TS"), ("TG", "TG"), ("OD", "OD"),
                                          ("Rajasthan", "Rajasthan"), ("rajasthan", "Rajasthan"), ("tamil  nadu", "Tamil Nadu"),
                                          ("Dadra and Nagar Haveli and Daman and Diu", "Dadra and Nagar Haveli and Daman and Diu")])
def test_valid_codes_and_names_are_accepted(raw, expected):
    assert normalise_indian_state(raw) == expected


@pytest.mark.parametrize("raw", ["ZZ", "XX", "R", "RJX", "Atlantis", "Rajasthan<script>", "Bombay", "", "   ", None])
def test_invalid_codes_and_names_are_rejected(raw):
    assert normalise_indian_state(raw) is None


def test_every_code_maps_to_a_listed_state():
    from vendor_onboarding import STATE_CODES
    assert set(STATE_CODES.values()) <= set(INDIAN_STATES)
    assert set(INDIAN_STATES) <= set(STATE_CODES.values())          # every state / UT has at least one code
    assert state_name("rj") == "Rajasthan" and state_name("Kerala") == "Kerala" and state_name("ZZ") is None


# ---------------------------------------------------------------- API: contact-only (approved / active) vendors
def test_vendor_with_stored_code_can_save_contact_changes(c):
    r = c.put("/api/vendor/me", headers=_hdr(S["a_u"]["id"]), json={**CONTACT, "city": "Jaipur City"})
    assert r.status_code == 200, r.text
    v = _vendor(c, S["a"]["id"])
    assert v["state"] == "RJ" and v["city"] == "Jaipur City" and v["business_name"] == "VS000001"   # legal name untouched


@pytest.mark.parametrize("state,stored", [("MH", "MH"), ("dl", "DL"), ("Maharashtra", "Maharashtra"), ("west bengal", "West Bengal")])
def test_other_valid_codes_and_names_save(c, state, stored):
    r = c.put("/api/vendor/me", headers=_hdr(S["b_u"]["id"]), json={**CONTACT, "state": state})
    assert r.status_code == 200, r.text
    assert _vendor(c, S["b"]["id"])["state"] == stored


@pytest.mark.parametrize("state", ["ZZ", "Atlantis", "Rajasthan<b>", "Bombay"])
def test_invalid_state_is_rejected_and_nothing_is_written(c, state):
    before = _vendor(c, S["b"]["id"])
    r = c.put("/api/vendor/me", headers=_hdr(S["b_u"]["id"]), json={**CONTACT, "state": state, "city": "Should Not Save"})
    assert r.status_code == 400 and "state" in r.json()["detail"].lower()
    assert _vendor(c, S["b"]["id"]) == before


def test_blank_state_cannot_erase_a_stored_state(c):
    before = _vendor(c, S["a"]["id"])
    r = c.put("/api/vendor/me", headers=_hdr(S["a_u"]["id"]), json={**CONTACT, "state": "  "})
    assert r.status_code == 400
    assert _vendor(c, S["a"]["id"])["state"] == before["state"]


def test_a_vendor_only_changes_its_own_record(c):
    other_before = _vendor(c, S["untouched"]["id"])
    r = c.put("/api/vendor/me", headers=_hdr(S["a_u"]["id"]), json={**CONTACT, "city": "Mine Only", "id": S["untouched"]["id"],
                                                                     "user_id": S["untouched_u"]["id"]})
    assert r.status_code == 200
    assert _vendor(c, S["untouched"]["id"]) == other_before
    assert _vendor(c, S["a"]["id"])["city"] == "Mine Only"


def test_existing_records_are_not_rewritten(c):
    # The vendor that never saved keeps exactly its legacy code: validation changes nothing on stored data.
    assert _vendor(c, S["untouched"]["id"])["state"] == "MH"


# ---------------------------------------------------------------- API: draft (full profile) save
def test_draft_may_leave_state_blank_but_not_free_text(c):
    h = _hdr(S["d_u"]["id"])
    assert c.put("/api/vendor/me", headers=h, json={**CONTACT, "state": ""}).status_code == 200
    r = c.put("/api/vendor/me", headers=h, json={**CONTACT, "state": "Atlantis"})
    assert r.status_code == 400
    assert c.put("/api/vendor/me", headers=h, json={**CONTACT, "state": "gujarat"}).status_code == 200
    assert _vendor(c, S["d"]["id"])["state"] == "Gujarat"
