import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, SessionLocal, User, Item, ItemAvailability

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_airbnb_calendar_workflow():
    # 1. Register Owner
    reg = client.post("/api/register", json={
        "first_name": "Sarah",
        "last_name": "Connor",
        "email": "sarah@resistance.com",
        "phone": "+1-925-555-0444",
        "address": "1000 Camino Ramon, San Ramon, CA",
        "username": "sarahc",
        "password": "Password123"
    }).json()
    owner_id = reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": reg["demo_otps"]["phone_code"]})

    # 2. List Item with Min 2 days and Max 7 days
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Generac 3300 PSI Pressure Washer",
        "category": "Lawn & Garden",
        "description": "Commercial grade gas pressure washer for heavy cleaning.",
        "condition": "Like New",
        "base_rate_daily": 30.0,
        "security_deposit": 200.0,
        "item_value": 450.0,
        "min_rental_days": 2,
        "max_rental_days": 7,
        "deposit_required": True,
        "insurance_required": False,
        "location_city": "San Ramon, CA"
    })
    assert item_res.status_code == 200
    item_id = item_res.json()["id"]

    # 3. Check initial availability: should be empty (all dates open)
    avail_res = client.get(f"/api/items/{item_id}/availability")
    assert avail_res.status_code == 200
    assert len(avail_res.json()) == 0

    # 4. Owner blocks a specific date (e.g. tomorrow) for maintenance
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    block_res = client.post(f"/api/items/{item_id}/availability/toggle", json={
        "owner_id": owner_id,
        "date": tomorrow,
        "status": "blocked",
        "reason": "Scheduled Maintenance & Oil Change"
    })
    assert block_res.status_code == 200
    assert block_res.json()["status"] == "blocked"

    # Verify date appears in availability API
    avail_res2 = client.get(f"/api/items/{item_id}/availability")
    assert len(avail_res2.json()) == 1
    assert avail_res2.json()[0]["date"] == tomorrow
    assert avail_res2.json()[0]["reason"] == "Scheduled Maintenance & Oil Change"

    # 5. Renter Range Check:
    # A) Range that overlaps with the blocked tomorrow date -> Unavailable
    start_d = date.today().isoformat()
    end_d = (date.today() + timedelta(days=3)).isoformat()
    check_overlap = client.post(f"/api/items/{item_id}/availability/check-range", json={
        "start_date": start_d,
        "end_date": end_d
    }).json()
    assert check_overlap["is_available"] is False
    assert "overlap" in check_overlap["reason"].lower()

    # B) Range that violates min duration (1 day vs min 2 days) -> Rejected
    check_short = client.post(f"/api/items/{item_id}/availability/check-range", json={
        "start_date": (date.today() + timedelta(days=5)).isoformat(),
        "end_date": (date.today() + timedelta(days=6)).isoformat()
    }).json()
    assert check_short["is_available"] is False
    assert "minimum required" in check_short["reason"]

    # C) Valid clear range (3 days) -> Accepted with calculated cost
    clear_start = (date.today() + timedelta(days=5)).isoformat()
    clear_end = (date.today() + timedelta(days=8)).isoformat()
    check_valid = client.post(f"/api/items/{item_id}/availability/check-range", json={
        "start_date": clear_start,
        "end_date": clear_end
    }).json()
    assert check_valid["is_available"] is True
    assert check_valid["total_days"] == 3
    assert check_valid["total_rent"] == 90.0

    # 6. Owner unblocks tomorrow
    unblock_res = client.post(f"/api/items/{item_id}/availability/toggle", json={
        "owner_id": owner_id,
        "date": tomorrow,
        "status": "available"
    })
    assert unblock_res.status_code == 200
    assert unblock_res.json()["status"] == "available"
    assert len(client.get(f"/api/items/{item_id}/availability").json()) == 0
