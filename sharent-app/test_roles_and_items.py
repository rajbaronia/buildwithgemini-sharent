import pytest
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, SessionLocal, User, Item

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_dual_roles_and_marketplace_separation():
    # 1. Create two verified users: Owner User (Alice) and Renter User (Bob)
    u1 = client.post("/api/register", json={
        "first_name": "Alice",
        "last_name": "Owner",
        "email": "alice@owner.com",
        "phone": "+1-925-555-0101",
        "address": "100 Market St, San Ramon, CA",
        "username": "alice_owner",
        "password": "Password123"
    }).json()
    u1_id = u1["user_id"]
    client.post("/api/verify-otp", json={"user_id": u1_id, "channel": "email", "otp_code": u1["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": u1_id, "channel": "phone", "otp_code": u1["demo_otps"]["phone_code"]})

    u2 = client.post("/api/register", json={
        "first_name": "Bob",
        "last_name": "Renter",
        "email": "bob@renter.com",
        "phone": "+1-925-555-0102",
        "address": "200 Crow Canyon, San Ramon, CA",
        "username": "bob_renter",
        "password": "Password123"
    }).json()
    u2_id = u2["user_id"]
    client.post("/api/verify-otp", json={"user_id": u2_id, "channel": "email", "otp_code": u2["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": u2_id, "channel": "phone", "otp_code": u2["demo_otps"]["phone_code"]})

    # 2. Test Dynamic Role Switching for Alice within her session
    role_check_1 = client.get(f"/api/session/current-role/{u1_id}").json()
    assert role_check_1["current_role"] == "owner"

    switch_to_renter = client.post("/api/session/switch-role", json={"user_id": u1_id, "role": "renter"}).json()
    assert switch_to_renter["active_role"] == "renter"

    switch_back_to_owner = client.post("/api/session/switch-role", json={"user_id": u1_id, "role": "owner"}).json()
    assert switch_back_to_owner["active_role"] == "owner"

    # 3. As Owner, Alice lists an item on the marketplace
    item_payload = {
        "owner_id": u1_id,
        "title": "DeWalt 20V Cordless Hammer Drill",
        "category": "Power Tools",
        "description": "High performance brushless hammer drill with 2 batteries and charger.",
        "condition": "Like New",
        "base_rate_daily": 15.0,
        "base_rate_hourly": 4.0,
        "security_deposit": 120.0,
        "item_value": 180.0,
        "insurance_required": True,
        "location_city": "San Ramon, CA"
    }
    item_res = client.post("/api/items", json=item_payload)
    assert item_res.status_code == 200
    item_data = item_res.json()
    assert item_data["title"] == "DeWalt 20V Cordless Hammer Drill"
    assert item_data["owner_id"] == u1_id

    # 4. Check Owner's own listings: Alice sees her own item
    my_listings = client.get(f"/api/items/my-listings/{u1_id}").json()
    assert len(my_listings) == 1
    assert my_listings[0]["title"] == "DeWalt 20V Cordless Hammer Drill"

    # 5. Check Marketplace catalog:
    # Alice (as Renter) browsing marketplace should NOT see her own item (cannot rent from self)
    alice_marketplace = client.get(f"/api/items/marketplace/{u1_id}").json()
    assert len(alice_marketplace) == 0

    # Bob (as Renter) browsing marketplace DOES see Alice's item
    bob_marketplace = client.get(f"/api/items/marketplace/{u2_id}").json()
    assert len(bob_marketplace) == 1
    assert bob_marketplace[0]["title"] == "DeWalt 20V Cordless Hammer Drill"
    assert bob_marketplace[0]["owner_name"] == "Alice Owner"
