"""Regression: on Vercel, an unreachable MongoDB must not turn requests into 60 s gateway timeouts.

Runs the app in-process (no live server) in Vercel mode with MONGO_URL pointing at a non-routable
address, which reproduces the production failure (Atlas not reachable from the function):
- CORS preflights are answered immediately with the right headers (no DB wait);
- API requests fail fast with a 503 that still carries CORS headers, instead of hanging.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import os
import time

FRONTEND = "https://home-genie-9zfc.vercel.app"
os.environ.update({
    "VERCEL": "1",
    "MONGO_URL": os.environ.get("TEST_UNREACHABLE_MONGO_URL", "mongodb://10.255.255.1:27017"),
    "DB_NAME": "homegenies_dbdown_test",
    "JWT_SECRET": "dbdown-test-" + "x" * 48,
    "CORS_ORIGINS": FRONTEND,
})

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402

client = TestClient(server.app)
REG = {"full_name": "Test", "mobile": "9555500123", "password": "secret123", "confirm_password": "secret123",
       "state": "UP", "city": "Lucknow", "pincode": "226001"}


def test_preflight_is_immediate_and_allows_frontend():
    t = time.monotonic()
    r = client.options("/api/auth/register-request", headers={
        "Origin": FRONTEND, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,authorization"})
    assert time.monotonic() - t < 2
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == FRONTEND
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "content-type" in r.headers["access-control-allow-headers"].lower()
    assert "authorization" in r.headers["access-control-allow-headers"].lower()


def test_unknown_origin_is_not_allowed():
    r = client.options("/api/auth/register-request", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_db_unreachable_fails_fast_with_503_and_cors():
    t = time.monotonic()
    r = client.post("/api/auth/register-request", json=REG, headers={"Origin": FRONTEND})
    assert time.monotonic() - t < 15  # well under Vercel's 60 s limit
    assert r.status_code == 503
    assert r.headers["access-control-allow-origin"] == FRONTEND
    assert "temporarily unavailable" in r.json()["detail"]
    assert "mongodb" not in r.text.lower()  # no connection details leaked


def test_missing_env_gives_503_naming_variables_not_import_crash():
    """With no configuration the app must still import and answer 503 listing the missing variable NAMES."""
    import subprocess, sys, os, json
    code = ("import json;from fastapi.testclient import TestClient;import server;"
            "r=TestClient(server.app).get('/api/');print(json.dumps([r.status_code,r.json()]))")
    env = {k: v for k, v in os.environ.items() if k not in ("MONGO_URL", "DB_NAME", "JWT_SECRET", "CORS_ORIGINS", "CORS_ALLOWED_ORIGINS")}
    env["VERCEL"] = "1"
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-c", code], cwd=here, env=env, capture_output=True, text=True, timeout=60)
    status, body = json.loads(out.stdout.strip().splitlines()[-1])
    assert status == 503
    assert body["missing_env"] == ["CORS_ORIGINS", "DB_NAME", "JWT_SECRET", "MONGO_URL"]
