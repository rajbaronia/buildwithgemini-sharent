import pytest
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, SessionLocal, User, Item, UserWallet, UserBonusTracker

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def test_item_location_default_and_vicinity_search():
    # 1. Register Owner in San Ramon, CA
    owner_reg = client.post("/api/register", json={
        "first_name": "Oliver",
        "last_name": "Owner",
        "email": "oliver.owner@sharent-test.com",
        "phone": "+19255551111",
        "address": "100 Crow Canyon Rd, San Ramon, CA 94583",
        "username": "oliverowner",
        "password": "Password123!"
    })
    assert owner_reg.status_code == 200
    owner_id = owner_reg.json()["user_id"]

    # Verify Owner Dual OTP
    v_res = client.post(f"/api/verify-otp-direct/{owner_id}")
    assert v_res.status_code == 200

    # 2. Register Renter in San Ramon, CA
    renter_reg = client.post("/api/register", json={
        "first_name": "Rachel",
        "last_name": "Renter",
        "email": "rachel.renter@sharent-test.com",
        "phone": "+19255552222",
        "address": "200 Norris Canyon Rd, San Ramon, CA 94583",
        "username": "rachelrenter",
        "password": "Password123!"
    })
    assert renter_reg.status_code == 200
    renter_id = renter_reg.json()["user_id"]

    # 3. Create Item 1: Without explicit location_address (Must default to Owner's address)
    item1_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "DeWalt Cordless Drill",
        "category": "Power Tools",
        "description": "Powerful 20V drill in great condition.",
        "condition": "Good",
        "base_rate_daily": 15.0,
        "security_deposit": 50.0,
        "item_value": 150.0,
        "min_rental_days": 1,
        "max_rental_days": 7
    })
    assert item1_res.status_code == 200
    item1_data = item1_res.json()
    assert item1_data["location_address"] == "100 Crow Canyon Rd, San Ramon, CA 94583"
    assert item1_data["latitude"] is not None
    assert item1_data["longitude"] is not None

    # 4. Create Item 2: Explicit custom location in Dublin, CA (~5.8 miles away)
    item2_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Honda Lawn Mower",
        "category": "Lawn & Garden",
        "description": "Self-propelled mower stored at Dublin workshop.",
        "condition": "Good",
        "base_rate_daily": 25.0,
        "security_deposit": 100.0,
        "item_value": 400.0,
        "min_rental_days": 1,
        "max_rental_days": 5,
        "location_address": "7890 Dublin Blvd, Dublin, CA 94568"
    })
    assert item2_res.status_code == 200
    item2_data = item2_res.json()
    assert item2_data["location_address"] == "7890 Dublin Blvd, Dublin, CA 94568"

    # 5. Create Item 3: Far location in San Francisco, CA (~24 miles away)
    item3_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "High-End Video Drone",
        "category": "Electronics",
        "description": "4K camera drone located at downtown SF studio.",
        "condition": "Like New",
        "base_rate_daily": 60.0,
        "security_deposit": 300.0,
        "item_value": 1200.0,
        "min_rental_days": 2,
        "max_rental_days": 10,
        "location_address": "500 Market St, San Francisco, CA 94102"
    })
    assert item3_res.status_code == 200
    item3_data = item3_res.json()
    assert "San Francisco" in item3_data["location_address"]

    # 6. Renter Queries Marketplace with Radius Filter: 10 miles
    # Should include Item 1 (San Ramon ~0 mi) and Item 2 (Dublin ~5.8 mi), but exclude Item 3 (SF ~24 mi)
    mkt_10 = client.get(f"/api/items/marketplace/{renter_id}?radius_miles=10.0")
    assert mkt_10.status_code == 200
    items_10 = mkt_10.json()
    assert len(items_10) == 2
    titles_10 = [it["title"] for it in items_10]
    assert "DeWalt Cordless Drill" in titles_10
    assert "Honda Lawn Mower" in titles_10
    assert "High-End Video Drone" not in titles_10
    # Check that distance_miles is computed and sorted ascending
    assert items_10[0]["distance_miles"] <= items_10[1]["distance_miles"]

    # 7. Renter Queries Marketplace with Radius Filter: 50 miles
    # Should return all 3 items, sorted closest to farthest
    mkt_50 = client.get(f"/api/items/marketplace/{renter_id}?radius_miles=50.0")
    assert mkt_50.status_code == 200
    items_50 = mkt_50.json()
    assert len(items_50) == 3
    assert items_50[0]["distance_miles"] <= items_50[1]["distance_miles"] <= items_50[2]["distance_miles"]
    assert items_50[2]["title"] == "High-End Video Drone"
    assert items_50[2]["distance_miles"] > 20.0

    # 8. Renter Queries with a custom near_address (e.g. San Francisco) with radius 15 miles
    # Near SF: Drone is ~0 miles, while San Ramon/Dublin are > 20 miles away
    mkt_sf = client.get(f"/api/items/marketplace/{renter_id}?near_address=San%20Francisco,%20CA&radius_miles=15.0")
    assert mkt_sf.status_code == 200
    items_sf = mkt_sf.json()
    assert len(items_sf) == 1
    assert items_sf[0]["title"] == "High-End Video Drone"
    assert items_sf[0]["distance_miles"] < 1.0
