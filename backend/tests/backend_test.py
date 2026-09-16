"""AUREN backend API tests"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/") or "https://auren-preview-3.preview.emergentagent.com"
ADMIN_EMAIL = "ethanphillipk@gmail.com"
ADMIN_PASSWORD = "AurenAdmin2026"


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="session")
def token(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture(scope="session")
def auth(api, token):
    api.headers.update({"Authorization": f"Bearer {token}"})
    return api


# ---- Auth ----
def test_login_success(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200
    d = r.json()
    assert d["user"]["email"] == ADMIN_EMAIL
    assert d["user"]["role"] == "admin"
    assert isinstance(d["token"], str) and len(d["token"]) > 20


def test_login_invalid(api):
    r = api.post(f"{BASE_URL}/api/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong"})
    assert r.status_code == 401


def test_me(api, token):
    r = api.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == ADMIN_EMAIL


def test_me_unauth(api):
    r = api.get(f"{BASE_URL}/api/auth/me")
    assert r.status_code == 401


# ---- Products ----
def test_products_list(api):
    r = api.get(f"{BASE_URL}/api/products")
    assert r.status_code == 200
    d = r.json()
    assert "items" in d and d["total"] > 0


def test_products_search_notes_vanilla(api):
    r = api.get(f"{BASE_URL}/api/products", params={"search": "Vanilla"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_products_search_brand_chanel(api):
    r = api.get(f"{BASE_URL}/api/products", params={"search": "Chanel"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1


def test_products_featured_filter(api):
    r = api.get(f"{BASE_URL}/api/products", params={"featured": "true"})
    assert r.status_code == 200
    for it in r.json()["items"]:
        assert it["featured"] is True


def test_product_by_slug(api):
    r = api.get(f"{BASE_URL}/api/products")
    slug = r.json()["items"][0]["slug"]
    r2 = api.get(f"{BASE_URL}/api/products/{slug}")
    assert r2.status_code == 200
    assert "_id" not in r2.json()


def test_product_view_increment(api):
    r = api.get(f"{BASE_URL}/api/products")
    pid = r.json()["items"][0]["id"]
    v0 = r.json()["items"][0].get("views", 0)
    api.post(f"{BASE_URL}/api/products/{pid}/view")
    r2 = api.get(f"{BASE_URL}/api/products/{pid}")
    assert r2.json()["views"] >= v0 + 1


def test_product_crud(auth):
    payload = {"name": "TEST_Product", "brand": "TEST_Brand", "price": 100000, "size": "50ml"}
    r = auth.post(f"{BASE_URL}/api/products", json=payload)
    assert r.status_code == 200
    pid = r.json()["id"]
    # Get
    r2 = auth.get(f"{BASE_URL}/api/products/{pid}")
    assert r2.json()["name"] == "TEST_Product"
    # Update
    payload["name"] = "TEST_Product2"
    r3 = auth.put(f"{BASE_URL}/api/products/{pid}", json=payload)
    assert r3.status_code == 200 and r3.json()["name"] == "TEST_Product2"
    # Status patch
    r4 = auth.patch(f"{BASE_URL}/api/products/{pid}/status", json={"status": "Sold"})
    assert r4.status_code == 200
    assert auth.get(f"{BASE_URL}/api/products/{pid}").json()["status"] == "Sold"
    # Delete
    r5 = auth.delete(f"{BASE_URL}/api/products/{pid}")
    assert r5.status_code == 200
    assert auth.get(f"{BASE_URL}/api/products/{pid}").status_code == 404


# ---- Submissions ----
def test_submission_flow(api, auth):
    payload = {
        "seller_name": "TEST_Seller", "phone": "628999TEST01", "instagram": "", "location": "Jakarta",
        "contact_method": "WhatsApp", "perfume_name": "TEST_Perfume", "brand": "TEST_Br",
        "size": "50ml", "condition": "Preloved 80%", "remaining_percentage": 80, "asking_price": 500000,
        "box_available": True, "proof_available": False, "description": "test", "photos": []
    }
    r = api.post(f"{BASE_URL}/api/submissions", json=payload)
    assert r.status_code == 200
    ref = r.json()["ref"]
    sub_id = r.json()["id"]
    assert ref.startswith("AUR-")
    # Track ok
    r2 = api.get(f"{BASE_URL}/api/submissions/track", params={"ref": ref, "phone": "628999TEST01"})
    assert r2.status_code == 200
    # Track wrong
    r3 = api.get(f"{BASE_URL}/api/submissions/track", params={"ref": ref, "phone": "wrong"})
    assert r3.status_code == 404
    # Admin list
    r4 = auth.get(f"{BASE_URL}/api/submissions")
    assert r4.status_code == 200 and any(s["id"] == sub_id for s in r4.json())
    # Update status Accepted
    r5 = auth.patch(f"{BASE_URL}/api/submissions/{sub_id}", json={"status": "Accepted"})
    assert r5.status_code == 200
    # Create product from submission
    r6 = auth.post(f"{BASE_URL}/api/submissions/{sub_id}/create-product")
    assert r6.status_code == 200
    prod_id = r6.json()["id"]
    # Cleanup
    auth.delete(f"{BASE_URL}/api/products/{prod_id}")


# ---- Interests ----
def test_interest_flow(api, auth):
    products = api.get(f"{BASE_URL}/api/products").json()["items"]
    pid = products[0]["id"]
    r = api.post(f"{BASE_URL}/api/interests", json={
        "product_id": pid, "buyer_name": "TEST_Buyer", "buyer_contact": "628TEST", "message": "hi"
    })
    assert r.status_code == 200
    iid = r.json()["id"]
    lst = auth.get(f"{BASE_URL}/api/interests").json()
    assert any(i["id"] == iid for i in lst)
    r2 = auth.patch(f"{BASE_URL}/api/interests/{iid}", json={"status": "Contacted"})
    assert r2.status_code == 200


def test_interest_invalid_product(api):
    r = api.post(f"{BASE_URL}/api/interests", json={
        "product_id": "nonexistent", "buyer_name": "x", "buyer_contact": "y"
    })
    assert r.status_code == 404


# ---- Contacts ----
def test_contact_flow(api, auth):
    r = api.post(f"{BASE_URL}/api/contacts", json={
        "name": "TEST_Contact", "contact": "628TESTCONTACT", "subject": "hi", "message": "hello"
    })
    assert r.status_code == 200
    lst = auth.get(f"{BASE_URL}/api/contacts").json()
    match = [c for c in lst if c["name"] == "TEST_Contact"]
    assert match
    cid = match[0]["id"]
    r2 = auth.patch(f"{BASE_URL}/api/contacts/{cid}", json={"status": "Read"})
    assert r2.status_code == 200


# ---- Admin ----
def test_admin_overview(auth):
    r = auth.get(f"{BASE_URL}/api/admin/overview")
    assert r.status_code == 200
    d = r.json()
    for k in ["total_products", "available_products", "sold_products", "pending_submissions",
              "total_sellers", "new_interests", "new_contacts", "total_views", "total_interested"]:
        assert k in d


def test_admin_notifications(auth):
    r = auth.get(f"{BASE_URL}/api/admin/notifications")
    assert r.status_code == 200
    d = r.json()
    assert "new_submissions" in d and "new_interests" in d and "new_contacts" in d


def test_admin_endpoints_require_auth(api):
    for path in ["/api/submissions", "/api/interests", "/api/contacts", "/api/admin/overview"]:
        r = api.get(f"{BASE_URL}{path}")
        assert r.status_code == 401, path



# ---- Announcement Settings ----
def test_announcement_get_public(api):
    r = api.get(f"{BASE_URL}/api/settings/announcement")
    assert r.status_code == 200
    d = r.json()
    for k in ["enabled", "text", "bg_color", "text_color", "link"]:
        assert k in d


def test_announcement_put_requires_auth(api):
    r = api.put(f"{BASE_URL}/api/settings/announcement", json={
        "enabled": True, "text": "x", "bg_color": "#000", "text_color": "#fff", "link": ""
    })
    assert r.status_code == 401


def test_announcement_put_and_get(auth, api):
    payload = {"enabled": True, "text": "TEST_ANN_MSG", "bg_color": "#111111", "text_color": "#C5A059", "link": "/shop"}
    r = auth.put(f"{BASE_URL}/api/settings/announcement", json=payload)
    assert r.status_code == 200 and r.json().get("ok") is True
    # Verify via public GET
    r2 = api.get(f"{BASE_URL}/api/settings/announcement")
    assert r2.status_code == 200
    d = r2.json()
    assert d["text"] == "TEST_ANN_MSG"
    assert d["bg_color"] == "#111111"
    assert d["link"] == "/shop"
    assert d["enabled"] is True
    # Restore reasonable default (keep enabled)
    auth.put(f"{BASE_URL}/api/settings/announcement", json={
        "enabled": True, "text": "Selamat datang di AUREN", "bg_color": "#121212", "text_color": "#C5A059", "link": ""
    })
