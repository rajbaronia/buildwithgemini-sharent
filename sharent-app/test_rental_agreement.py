import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_rental_agreement_terms_and_conditions_lifecycle():
    # 1. Register Owner
    reg_o = client.post("/api/register", json={
        "first_name": "Alice", "last_name": "Walker", "email": "alice@agree.com",
        "phone": "+1-925-555-0201", "address": "100 Plaza, San Ramon, CA",
        "username": "alicew_agr", "password": "Password123"
    }).json()
    owner_id = reg_o["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": reg_o["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": reg_o["demo_otps"]["phone_code"]})

    # 2. Register Renter
    reg_r = client.post("/api/register", json={
        "first_name": "Bob", "last_name": "Builder", "email": "bob@agree.com",
        "phone": "+1-925-555-0202", "address": "200 Plaza, San Ramon, CA",
        "username": "bobb_agr", "password": "Password123"
    }).json()
    renter_id = reg_r["user_id"]
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "email", "otp_code": reg_r["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "phone", "otp_code": reg_r["demo_otps"]["phone_code"]})

    # 3. Create Item
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Bosch Professional Rotary Hammer Drill",
        "category": "Power Tools",
        "condition": "Like New",
        "description": "Heavy duty SDS-plus rotary hammer drill with chisel kit.",
        "base_rate_daily": 22.0,
        "security_deposit": 120.0,
        "item_value": 350.0,
        "min_rental_days": 1,
        "max_rental_days": 7,
        "deposit_required": True,
        "insurance_required": True,
        "location_city": "San Ramon, CA"
    })
    item_id = item_res.json()["id"]

    start_d = date.today().isoformat()
    end_d = (date.today() + timedelta(days=2)).isoformat()  # 2 days

    # 4. Attempt to agree WITHOUT acknowledging all mandatory checkboxes -> Must return HTTP 400
    fail_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": renter_id,
        "start_date": start_d,
        "end_date": end_d,
        "accepted_terms": True,
        "accepted_deposit_policy": False,  # Missing acknowledgment
        "accepted_safety_rules": True
    })
    assert fail_res.status_code == 400
    assert "You must acknowledge and accept all rental agreement terms" in fail_res.json()["detail"]

    # 5. Successful agreement with all acknowledgments
    ok_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": renter_id,
        "start_date": start_d,
        "end_date": end_d,
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    assert ok_res.status_code == 200
    agr_data = ok_res.json()
    assert agr_data["item_id"] == item_id
    assert agr_data["agreement_code"].startswith("SHR-AGR-")
    assert agr_data["renter_name"] == "Bob Builder"
    assert agr_data["owner_name"] == "Alice Walker"
    assert agr_data["total_days"] == 2
    assert agr_data["daily_rate"] == 22.0
    assert agr_data["base_rent"] == 44.0
    assert agr_data["security_deposit"] == 120.0
    assert agr_data["status"] == "pending_payment"
    assert "agreed_at" in agr_data
