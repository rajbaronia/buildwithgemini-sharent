import pytest
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_owner_activation_and_deactivation_lifecycle():
    # 1. Register Owner
    owner_reg = client.post("/api/register", json={
        "first_name": "Tom",
        "last_name": "Hanks",
        "email": "tom@sharent.com",
        "phone": "+1-925-555-0777",
        "address": "1 Castaway Way, San Ramon, CA",
        "username": "tomhanks",
        "password": "Password123"
    }).json()
    owner_id = owner_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": owner_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": owner_reg["demo_otps"]["phone_code"]})

    # 2. Register Renter
    renter_reg = client.post("/api/register", json={
        "first_name": "Wilson",
        "last_name": "Ball",
        "email": "wilson@sharent.com",
        "phone": "+1-925-555-0888",
        "address": "2 Island Blvd, San Ramon, CA",
        "username": "wilsonball",
        "password": "Password123"
    }).json()
    renter_id = renter_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "email", "otp_code": renter_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "phone", "otp_code": renter_reg["demo_otps"]["phone_code"]})

    # 3. Owner lists an item (initially is_available=True)
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Bose S1 Pro Portable Bluetooth PA Speaker",
        "category": "Electronics",
        "description": "High output portable party speaker with rechargeable battery.",
        "condition": "Like New",
        "base_rate_daily": 25.0,
        "security_deposit": 200.0,
        "item_value": 649.0,
        "min_rental_days": 1,
        "max_rental_days": 7,
        "deposit_required": True,
        "insurance_required": True,
        "location_city": "San Ramon, CA"
    })
    assert item_res.status_code == 200
    item_id = item_res.json()["id"]

    # 4. Verify item is visible in Renter's marketplace
    market_res1 = client.get(f"/api/items/marketplace/{renter_id}").json()
    assert len(market_res1) == 1
    assert market_res1[0]["id"] == item_id

    # 5. Owner Deactivates the item (hides it from renters)
    deactivate_res = client.post(f"/api/items/{item_id}/toggle-status", json={
        "owner_id": owner_id,
        "is_available": False
    })
    assert deactivate_res.status_code == 200
    assert deactivate_res.json()["is_available"] is False

    # 6. Verify item is HIDDEN from Renter's marketplace
    market_res2 = client.get(f"/api/items/marketplace/{renter_id}").json()
    assert len(market_res2) == 0

    # 7. Verify item is STILL in Owner's Inventory
    owner_inv = client.get(f"/api/items/my-listings/{owner_id}").json()
    assert len(owner_inv) == 1
    assert owner_inv[0]["id"] == item_id
    assert owner_inv[0]["is_available"] is False

    # 8. Unauthorized user cannot toggle status
    unauth_res = client.post(f"/api/items/{item_id}/toggle-status", json={
        "owner_id": renter_id,  # Renter trying to toggle owner's item
        "is_available": True
    })
    assert unauth_res.status_code == 403

    # 9. Owner Reactivates the item
    activate_res = client.post(f"/api/items/{item_id}/toggle-status", json={
        "owner_id": owner_id,
        "is_available": True
    })
    assert activate_res.status_code == 200
    assert activate_res.json()["is_available"] is True

    # 10. Verify item is VISIBLE again in Renter's marketplace
    market_res3 = client.get(f"/api/items/marketplace/{renter_id}").json()
    assert len(market_res3) == 1
    assert market_res3[0]["id"] == item_id
