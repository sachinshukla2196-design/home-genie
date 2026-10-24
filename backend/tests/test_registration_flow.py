"""Normal users register and log in immediately (no admin approval); legacy pending requests are activated safely."""
import os, uuid
os.environ.update({"VERCEL": "1", "DB_NAME": "hg_regflow_" + uuid.uuid4().hex[:8], "JWT_SECRET": "regflow-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://example.test"})
import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient
import server
from core import hash_password, new_id, now_iso, create_token

_sync = MongoClient(os.environ["MONGO_URL"])
sdb = _sync[os.environ["DB_NAME"]]   # sync handle: TestClient and Motor use different event loops
PW = "FlowTest@123"


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        yield client
    _sync.drop_database(os.environ["DB_NAME"])


def _register(c, mobile, email="", pw=PW):
    return c.post("/api/auth/register-request", json={"full_name": "T", "mobile": mobile, "email": email, "password": pw,
                                                       "confirm_password": pw, "state": "Delhi", "city": "Delhi", "pincode": "110001"})


def _login(c, ident, pw=PW):
    return c.post("/api/auth/login", json={"email": ident, "password": pw})




def test_register_login_logout_login_again(c):
    r = _register(c, "9811111111", "flow1@x.test")
    assert r.status_code == 200 and "approval" not in r.json()["message"].lower().replace("no admin approval", "")
    u = sdb.users.find_one({"mobile": "9811111111"})
    assert u and u["account_status"] == "active" and u["role"] == "distributor" and u["role"] not in ("super_admin", "admin", "vendor")
    assert u["password_hash"] != PW and not u.get("blocked")
    for ident in ("9811111111", "flow1@x.test", u["distributor_id"]):          # mobile, email, HomeGenie ID
        r = _login(c, ident)
        assert r.status_code == 200 and r.json()["token"]
    tok = _login(c, "9811111111").json()["token"]
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    assert _login(c, "9811111111", "wrong-password").status_code == 401
    assert sdb.users.count_documents({"mobile": "9811111111"}) == 1


def test_duplicates_still_refused_and_no_privilege(c):
    assert _register(c, "9833333333", "dup@x.test").status_code == 200
    assert _register(c, "9833333333").status_code == 400
    assert _register(c, "9844444444", "dup@x.test").status_code == 400
    tok = _login(c, "9833333333").json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/admin/registration-requests", headers=h).status_code == 403
    assert c.get("/api/vendor/products", headers=h).status_code in (401, 403)


def test_legacy_pending_request_logs_in_and_is_activated_once(c):
    rid = new_id()
    sdb.registration_requests.insert_one({"id": rid, "full_name": "Old", "mobile": "9822222222", "email": "old@x.test",
        "password_hash": hash_password(PW), "state": "D", "city": "D", "pincode": "110001", "status": "pending", "created_at": now_iso()})
    assert _login(c, "9822222222", "bad-password").status_code == 401           # wrong password never activates
    assert sdb.users.count_documents({"mobile": "9822222222"}) == 0
    assert _login(c, "9822222222").status_code == 200
    assert _login(c, "old@x.test").status_code == 200
    assert sdb.users.count_documents({"mobile": "9822222222"}) == 1
    assert sdb.registration_requests.find_one({"id": rid})["status"] == "approved"


def test_sweep_activates_all_pending_without_duplicates(c):
    ids = []
    for i, m in enumerate(("9855555551", "9855555552")):
        rid = new_id(); ids.append(rid)
        sdb.registration_requests.insert_one({"id": rid, "full_name": "P", "mobile": m, "email": f"p{i}@x.test",
            "password_hash": hash_password(PW), "state": "D", "city": "D", "pincode": "110001", "status": "pending", "created_at": now_iso()})
    # one of them already has an account (e.g. approved by an admin but the request row was not updated)
    from core import next_distributor_id  # noqa: F401
    sdb.users.insert_one({"id": new_id(), "distributor_id": "HGX1", "mobile": "9855555552", "email": "p1@x.test", "role": "distributor",
                          "password_hash": hash_password(PW), "full_name": "P", "created_at": now_iso()})
    from admin_routes import activate_pending_registrations
    c.portal.call(activate_pending_registrations)   # run on the app's own event loop
    assert sdb.users.count_documents({"mobile": "9855555551"}) == 1
    assert sdb.users.count_documents({"mobile": "9855555552"}) == 1
    assert all(sdb.registration_requests.find_one({"id": i})["status"] == "approved" for i in ids)


def test_admin_approve_still_works_idempotently(c):
    uid = new_id(); tag = uid[:6]
    sdb.users.insert_one({"id": uid, "distributor_id": "ADM" + tag, "role": "super_admin", "email": f"{tag}@x.test", "mobile": "9" + str(int(tag, 16))[:9].ljust(9, "0"),
                          "password_hash": hash_password("x"), "full_name": "A", "created_at": now_iso()})
    adm = {"Authorization": f"Bearer {create_token(uid)}"}
    rid = new_id()
    sdb.registration_requests.insert_one({"id": rid, "full_name": "Q", "mobile": "9866666666", "email": "", "password_hash": hash_password(PW),
                                          "state": "D", "city": "D", "pincode": "110001", "status": "pending", "created_at": now_iso()})
    assert c.post(f"/api/admin/registration-requests/{rid}/approve", headers=adm).status_code == 200
    assert c.post(f"/api/admin/registration-requests/{rid}/approve", headers=adm).status_code == 400
    assert _login(c, "9866666666").status_code == 200
    assert sdb.users.count_documents({"mobile": "9866666666"}) == 1
