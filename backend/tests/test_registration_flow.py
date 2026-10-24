"""registration -> pending (blocked, clear message) -> admin approve -> login; reject keeps the user blocked."""
import os, uuid
os.environ.update({"VERCEL": "1", "DB_NAME": "hg_regflow_" + uuid.uuid4().hex[:8], "JWT_SECRET": "regflow-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://example.test"})
from fastapi.testclient import TestClient
from pymongo import MongoClient
import server
from core import create_token, now_iso, hash_password, new_id

_sync = MongoClient(os.environ["MONGO_URL"])
sdb = _sync[os.environ["DB_NAME"]]   # sync handle: TestClient and Motor use different event loops


import pytest


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:   # one event loop for the whole module
        yield client
    _sync.drop_database(os.environ["DB_NAME"])


def _admin():
    uid = new_id()
    tag = uid[:8]
    sdb.users.insert_one({"id": uid, "distributor_id": "ADM" + tag, "role": "super_admin", "email": f"{tag}@x.test", "mobile": "9" + str(int(tag, 16))[:9].ljust(9, "0"),
                             "password_hash": hash_password("x"), "full_name": "A", "created_at": now_iso()})
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _register(c, mobile, pw="FlowTest@123"):
    return c.post("/api/auth/register-request", json={"full_name": "T", "mobile": mobile, "password": pw, "confirm_password": pw,
                                                       "state": "Delhi", "city": "Delhi", "pincode": "110001"})


def _login(c, mobile, pw="FlowTest@123"):
    return c.post("/api/auth/login", json={"email": mobile, "password": pw})


def test_pending_then_approve_then_login(c):
    adm = _admin()
    assert _register(c, "9811111111").status_code == 200
    r = _login(c, "9811111111")
    assert r.status_code == 403 and "waiting for admin approval" in r.json()["detail"]
    assert _login(c, "9811111111", "wrong-password").status_code == 401          # no probing of pending requests
    assert _register(c, "9811111111").status_code == 400                           # no duplicate pending request
    reqs = c.get("/api/admin/registration-requests", headers=adm).json()
    rid = next(x["id"] for x in reqs if x["mobile"] == "9811111111" and x["status"] == "pending")
    assert c.post(f"/api/admin/registration-requests/{rid}/approve", headers=adm).status_code == 200
    assert c.post(f"/api/admin/registration-requests/{rid}/approve", headers=adm).status_code == 400   # not twice
    assert _login(c, "9811111111").status_code == 200
    assert sdb.users.count_documents({"mobile": "9811111111"}) == 1
    assert _register(c, "9811111111").status_code == 400                           # account exists now


def test_reject_keeps_user_blocked_with_clear_message(c):
    adm = _admin()
    assert _register(c, "9822222222").status_code == 200
    rid = next(x["id"] for x in c.get("/api/admin/registration-requests", headers=adm).json() if x["mobile"] == "9822222222")
    assert c.post(f"/api/admin/registration-requests/{rid}/reject", headers=adm, json={"reason": "incomplete"}).status_code == 200
    r = _login(c, "9822222222")
    assert r.status_code == 403 and "not approved" in r.json()["detail"]
    assert _login(c, "9822222222", "bad-password").status_code == 401
    assert sdb.users.count_documents({"mobile": "9822222222"}) == 0


def test_requests_are_admin_only(c):
    assert c.get("/api/admin/registration-requests").status_code == 401
