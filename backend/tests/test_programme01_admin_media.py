"""Programme 01 / B-009: platform content admins (super admin, admin) can upload images - direct (server-signed, platform folder)
or through the server (content-sniffed, size-limited, server-chosen path) - while support / accounts admins, customers and
vendors cannot; vendor uploads stay vendor-only and folder-bound; merchandising accepts only validated uploads.

The object store is replaced by an in-memory stand-in (no external service is called). Integration, THROWAWAY MongoDB.
Run alone: `pytest tests/test_programme01_admin_media.py -n 0`.
"""
import os

import pytest
import requests

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_media_test", "JWT_SECRET": "p01-media-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import storage  # noqa: E402
import governance_routes  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402
from p01_harness import World, seed_world, hdr  # noqa: E402

S = {}
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
CLOUD = {"CLOUDINARY_CLOUD_NAME": "hgtest", "CLOUDINARY_API_KEY": "k123", "CLOUDINARY_API_SECRET": "unit-test-secret-value",
         "CLOUDINARY_UPLOAD_PRESET": ""}


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "AM")
        client.portal.call(seed)
        yield World(client, S, "AMSELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


@pytest.fixture
def store(monkeypatch):
    """In-memory object store: records every write; a test can make it fail."""
    objs = {}
    state = {"fail": False}

    def put(path, data, ctype):
        if state["fail"]:
            resp = requests.Response()
            resp.status_code = 500
            raise requests.HTTPError(response=resp)
        assert path not in objs, "an upload must never overwrite"
        objs[path] = (data, ctype)
        return {"path": path, "size": len(data)}
    monkeypatch.setattr(storage, "_put", put)
    monkeypatch.setattr(storage, "_get", lambda path: objs[path])
    return objs, state


@pytest.fixture
def cloud(monkeypatch):
    for k, v in CLOUD.items():
        monkeypatch.setenv(k, v)


def _upload(w, who, data, name="banner.png", ctype="image/png", kind="merchandising"):
    return w.c.post(f"/api/admin/uploads/image?kind={kind}", headers=hdr(S[who]["id"]), files={"file": (name, data, ctype)})


# ================================================================ direct (signed) upload
def test_content_admins_sign_platform_uploads_and_the_secret_never_leaves(w, cloud):
    for who in ("adm", "sup"):
        r = w.c.post("/api/admin/uploads/sign", headers=hdr(S[who]["id"]), json={"kind": "merchandising", "folder": "homegenies/vendors/x"})
        assert r.status_code == 200, r.text
        p = r.json()["params"]
        assert p["folder"] == "homegenies/platform/merchandising" and p["overwrite"] == "false" and p["allowed_formats"] == "jpg,png,webp"
        assert "unit-test-secret-value" not in r.text and len(p["public_id"]) == 32
    assert w.c.post("/api/admin/uploads/sign", headers=hdr(S["adm"]["id"]), json={"kind": "product"}).json()["params"]["folder"] == \
        "homegenies/platform/products"
    assert w.c.post("/api/admin/uploads/sign", headers=hdr(S["adm"]["id"]), json={"kind": "document"}).status_code == 400
    assert w.audits("admin_upload_signed")


@pytest.mark.parametrize("who,code", [("support", 403), ("fin", 403), ("cust", 403), ("uva", 403)])
def test_other_roles_cannot_sign_platform_uploads(w, cloud, who, code):
    assert w.c.post("/api/admin/uploads/sign", headers=hdr(S[who]["id"]), json={"kind": "product"}).status_code == code


def test_without_direct_upload_configured_the_admin_is_told_to_use_the_server_upload(w):
    r = w.c.post("/api/admin/uploads/sign", headers=hdr(S["adm"]["id"]), json={"kind": "product"})
    assert r.status_code == 200 and r.json() == {"configured": False}
    assert w.c.post("/api/admin/uploads/sign", headers=hdr(S["support"]["id"]), json={"kind": "product"}).status_code == 403


def test_vendor_signing_is_unchanged_vendor_only_and_bound_to_its_own_folder(w, cloud):
    r = w.c.post("/api/vendor/uploads/sign", headers=hdr(S["uva"]["id"]), json={"kind": "product"})
    assert r.status_code == 200 and r.json()["params"]["folder"] == f"homegenies/vendors/{S['va']['id']}/products"
    assert w.c.post("/api/vendor/uploads/sign", headers=hdr(S["adm"]["id"]), json={"kind": "product"}).status_code == 403


def test_a_vendor_cannot_attach_another_vendors_upload_but_may_use_a_platform_one(w, cloud):
    mine = f"https://res.cloudinary.com/hgtest/image/upload/v1/homegenies/vendors/{S['va']['id']}/products/a.jpg"
    theirs = f"https://res.cloudinary.com/hgtest/image/upload/v1/homegenies/vendors/{S['vb']['id']}/products/b.jpg"
    platform = "https://res.cloudinary.com/hgtest/image/upload/v1/homegenies/platform/products/c.jpg"
    governance_routes.validate_image_ownership([mine, platform], S["va"]["id"])
    with pytest.raises(ValueError):
        governance_routes.validate_image_ownership([theirs], S["va"]["id"])


# ================================================================ server-side upload
def test_server_upload_stores_a_real_image_under_a_server_chosen_path(w, store):
    objs, _ = store
    r = _upload(w, "adm", PNG, name="../../etc/passwd.png")
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    path = url.split("/api/files/", 1)[1]
    assert path.startswith("home-genies/merchandising/") and ".." not in path and path in objs
    rec = w.run(lambda: db.files.find_one({"storage_path": path}, {"_id": 0}))
    assert rec["content_type"] == "image/png" and rec["original_filename"] == "passwd.png" and rec["owner_id"] == S["adm"]["id"]
    assert w.c.get(f"/api/files/{path}").status_code == 200
    assert w.audits("admin_image_uploaded")


def test_the_same_file_uploaded_twice_is_two_files_and_nothing_is_overwritten(w, store):
    a, b = _upload(w, "sup", JPG, name="x.jpg", ctype="image/jpeg"), _upload(w, "sup", JPG, name="x.jpg", ctype="image/jpeg")
    assert a.status_code == b.status_code == 200 and a.json()["url"] != b.json()["url"]


@pytest.mark.parametrize("data,name,ctype", [
    (b"just some text", "notes.txt", "text/plain"),                          # not an image type
    (b"MZ\x90\x00 executable bytes", "photo.png", "image/png"),              # spoofed extension and type
    (b"<svg onload=alert(1)>", "logo.png", "image/png"),                     # script disguised as an image
    (b"", "empty.png", "image/png"),
])
def test_invalid_or_disguised_files_are_refused(w, store, data, name, ctype):
    objs, _ = store
    n = len(objs)
    assert _upload(w, "adm", data, name=name, ctype=ctype).status_code == 400
    assert len(objs) == n


def test_oversized_images_are_refused(w, store):
    assert _upload(w, "adm", PNG + b"\x00" * (5 * 1024 * 1024)).status_code == 400


def test_a_storage_failure_reports_an_error_and_records_nothing(w, store):
    _, state = store
    state["fail"] = True
    before = w.run(lambda: db.files.count_documents({}))
    assert _upload(w, "adm", PNG).status_code == 502
    assert w.run(lambda: db.files.count_documents({})) == before


@pytest.mark.parametrize("who", ["support", "fin", "cust", "uva"])
def test_only_content_admins_may_upload_through_the_server(w, store, who):
    assert _upload(w, who, PNG).status_code == 403
    assert w.c.post("/api/admin/uploads/product-image", headers=hdr(S[who]["id"]), files={"file": ("p.png", PNG, "image/png")}).status_code == 403


def test_the_existing_product_image_upload_still_works_for_content_admins(w, store):
    r = w.c.post("/api/admin/uploads/product-image", headers=hdr(S["adm"]["id"]), files={"file": ("p.png", PNG, "image/png")})
    assert r.status_code == 200 and "/api/files/home-genies/products/" in r.json()["url"]


# ================================================================ merchandising accepts validated uploads only
def _banner(w, image, who="adm", sid=None):
    body = {"kind": "banner", "title": "Diwali", "image_desktop": image, "alt": "Diwali sarees", "link": "/app/products?category=Sarees"}
    if sid:
        return w.c.put(f"/api/admin/merch/sections/{sid}", headers=hdr(S[who]["id"]), json=body)
    return w.c.post("/api/admin/merch/sections", headers=hdr(S[who]["id"]), json=body)


def test_merchandising_accepts_a_server_upload_a_platform_cloud_image_and_bundled_assets(w, store, cloud):
    url = _upload(w, "adm", PNG).json()["url"]
    assert _banner(w, url).status_code == 200
    assert _banner(w, "/" + url.split("/", 3)[3]).status_code == 200                         # the same file as a site path
    assert _banner(w, "https://res.cloudinary.com/hgtest/image/upload/v1/homegenies/platform/merchandising/x.jpg").status_code == 200
    assert _banner(w, "/brand/pillar-sarees.jpg").status_code == 200


@pytest.mark.parametrize("image", [
    "https://images.example.com/banner.jpg",                                                 # an arbitrary website
    "https://res.cloudinary.com/othercloud/image/upload/v1/homegenies/platform/merchandising/x.jpg",
    "https://res.cloudinary.com/hgtest/image/upload/v1/homegenies/vendors/v1/products/x.jpg",  # a vendor's folder
    "/api/files/home-genies/merchandising/never-uploaded.png",                                 # not on record
    "/api/files/../../secret.png",
])
def test_merchandising_refuses_links_that_are_not_validated_uploads(w, cloud, image):
    r = _banner(w, image)
    assert r.status_code in (400, 422), (image, r.text)


def test_a_deleted_upload_can_no_longer_be_used(w, store):
    url = _upload(w, "adm", PNG).json()["url"]
    path = url.split("/api/files/", 1)[1]
    w.run(lambda: db.files.update_one({"storage_path": path}, {"$set": {"is_deleted": True}}))
    assert _banner(w, url).status_code == 400


def test_existing_sections_with_old_links_still_display_and_must_be_re_uploaded_to_edit(w):
    sid = new_id()
    w.run(lambda: db.merch_sections.insert_one({"id": sid, "kind": "banner", "title": "Old", "image_desktop": "https://old.example.com/b.jpg",
                                                "alt": "Old banner", "status": "draft", "position": 99, "product_ids": [],
                                                "created_at": now_iso(), "updated_at": now_iso(), "history": []}))
    listed = w.c.get("/api/admin/merch/sections", headers=hdr(S["adm"]["id"]))
    assert listed.status_code == 200 and any(x["id"] == sid and x["image_desktop"] == "https://old.example.com/b.jpg"
                                             for x in listed.json()["sections"])
    assert _banner(w, "https://old.example.com/b.jpg", sid=sid).status_code == 400
    assert w.run(lambda: db.merch_sections.find_one({"id": sid}, {"_id": 0, "image_desktop": 1}))["image_desktop"] == "https://old.example.com/b.jpg"
