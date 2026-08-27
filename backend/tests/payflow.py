"""Helper script for the Stripe TEST payment regression (run manually, not via pytest).

Usage:
  python payflow.py setup        -> registers A (+ B via A's referral), creates orders,
                                    prints/stores checkout URLs in /tmp/payflow.json
  python payflow.py pay A|B      -> polls payment status until paid (after Playwright pays)
  python payflow.py verify       -> asserts A GREEN, commission = 100, single ledger entry
"""
import json
import os
import secrets
import sys
import time

import requests
from dotenv import dotenv_values

fe = dotenv_values("/app/frontend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL")).rstrip("/")
API = f"{BASE}/api"
STATE = "/tmp/payflow.json"


def rnd():
    return secrets.randbelow(900000) + 100000


def register(sponsor=""):
    email = f"payflow_{rnd()}@qa-anjali.example.com"
    mobile = "9" + f"{secrets.randbelow(1000000000):09d}"
    r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=30)
    r.raise_for_status()
    otp = r.json()["dev_otp"]
    r = requests.post(f"{API}/auth/register", json={
        "full_name": "TEST Payflow", "email": email, "mobile": mobile,
        "password": "Test@1234", "confirm_password": "Test@1234", "otp": otp,
        "sponsor_id": sponsor, "accept_terms": True}, timeout=30)
    r.raise_for_status()
    d = r.json()
    print(f"registered {d['user']['distributor_id']} status={d['user']['status']} sponsor={sponsor or '-'}")
    assert d["user"]["status"] == "red"
    return {"email": email, "mobile": mobile, "token": d["token"],
            "did": d["user"]["distributor_id"], "id": d["user"]["id"]}


def checkout(acc):
    h = {"Authorization": f"Bearer {acc['token']}"}
    prods = requests.get(f"{API}/products", timeout=30).json()
    starter = next(p for p in prods if p["sku"] == "ANJ-STARTER")
    order = requests.post(f"{API}/orders", json={
        "items": [{"product_id": starter["id"], "quantity": 1}],
        "address": {"full_name": "TEST Payflow", "mobile": acc["mobile"], "line1": "1 St",
                    "city": "Pune", "state": "MH", "pincode": "411001"}},
        headers=h, timeout=30).json()
    r = requests.post(f"{API}/payments/checkout",
                      json={"order_id": order["id"], "origin_url": BASE}, headers=h, timeout=60)
    r.raise_for_status()
    d = r.json()
    acc["order_id"] = order["id"]
    acc["session_id"] = d["session_id"]
    acc["checkout_url"] = d["checkout_url"]
    print(f"checkout for {acc['did']}: {d['checkout_url']}")
    return acc


def wallet(acc):
    h = {"Authorization": f"Bearer {acc['token']}"}
    return requests.get(f"{API}/wallet", headers=h, timeout=30).json()


def me(acc):
    h = {"Authorization": f"Bearer {acc['token']}"}
    return requests.get(f"{API}/auth/me", headers=h, timeout=30).json()


def setup():
    a = checkout(register())
    b = register(sponsor=a["did"])
    w = wallet(a)
    print(f"A wallet before any payment: available={w['available_balance']} earned={w['total_earned']}")
    assert w["available_balance"] == 0 and w["total_earned"] == 0, "A should have 0 commission pre-activation"
    json.dump({"a": a, "b": b}, open(STATE, "w"), indent=1)
    print("STATE saved. A checkout_url above.")


def poll(who):
    s = json.load(open(STATE))
    acc = s[who]
    for _ in range(12):
        r = requests.get(f"{API}/payments/status/{acc['session_id']}", timeout=30).json()
        print("status:", r)
        if r["payment_status"] == "paid":
            break
        time.sleep(3)
    u = me(acc)
    print(f"{acc['did']} status={u['status']}")
    json.dump(s, open(STATE, "w"), indent=1)


def checkout_b():
    s = json.load(open(STATE))
    # A must be green before B's referral commission can be credited
    print("A status:", me(s["a"])["status"])
    w = wallet(s["a"])
    print(f"A wallet after own activation: available={w['available_balance']} earned={w['total_earned']}")
    assert w["total_earned"] == 0, "A must have 0 commission before B pays"
    s["b"] = checkout(s["b"])
    json.dump(s, open(STATE, "w"), indent=1)


def verify():
    s = json.load(open(STATE))
    a, b = s["a"], s["b"]
    assert me(a)["status"] == "green", "A not GREEN"
    assert me(b)["status"] == "green", "B not GREEN"
    w = wallet(a)
    print("A wallet:", {k: w[k] for k in ("available_balance", "pending_balance", "total_earned")})
    assert w["total_earned"] == 100.0, f"expected 100 commission, got {w['total_earned']}"
    assert w["available_balance"] == 100.0, w["available_balance"]
    # repeat status poll must not duplicate the credit (idempotency)
    for _ in range(3):
        requests.get(f"{API}/payments/status/{b['session_id']}", timeout=30)
    w2 = wallet(a)
    assert w2["total_earned"] == 100.0, f"duplicate credit! {w2['total_earned']}"
    h = {"Authorization": f"Bearer {a['token']}"}
    txs = requests.get(f"{API}/wallet/transactions", headers=h, timeout=30).json()
    items = txs if isinstance(txs, list) else txs.get("items", txs.get("transactions", []))
    comm = [t for t in items if t.get("type") == "REFERRAL_COMMISSION"]
    print("commission ledger entries:", len(comm), comm)
    assert len(comm) == 1, "commission ledger not single-entry"
    ref = requests.get(f"{API}/referral", headers=h, timeout=30).json()
    print("referral:", json.dumps(ref)[:400])
    print("PAYMENT+COMMISSION REGRESSION PASSED")


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"setup": setup, "verify": verify, "checkout_b": checkout_b}.get(cmd, lambda: poll(sys.argv[2]))()
