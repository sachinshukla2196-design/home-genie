"""Probe: confirm password lockout has no expiry window (login_attempts.count never resets)."""
import time
import requests
import payflow as p
from test_otp_auth import _mongo

API = p.API
acc = p.register()
acc["password"] = "Test@1234"
cli, db = _mongo()
# Ingress presents multiple proxy IPs, so seed the counter for every observed proxy IP.
ips = {d["identifier"].split(":")[0] for d in db.login_attempts.find({}, {"identifier": 1})}
print("proxy IPs seen:", ips)
for ip in ips:
    db.login_attempts.update_one({"identifier": f"{ip}:{acc['email']}"},
                                 {"$set": {"count": 5, "last": "2020-01-01T00:00:00+00:00"}}, upsert=True)
r = requests.post(f"{API}/auth/login", json={"email": acc["email"], "password": acc["password"]}, timeout=30)
print("correct password with stale (2020) lockout record:", r.status_code, r.text[:150])
otp = requests.post(f"{API}/auth/login-otp/send", json={"mobile": acc["mobile"]}, timeout=30).json().get("dev_otp")
v = requests.post(f"{API}/auth/login-otp/verify", json={"mobile": acc["mobile"], "otp": otp}, timeout=30)
print("OTP login while password-locked:", v.status_code)
db.login_attempts.delete_many({"identifier": {"$regex": acc["email"]}})
cli.close()
