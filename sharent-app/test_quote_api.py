import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_quote_breakdown_api():
    # 1. Register Owner
    reg_o = client.post("/api/register", json={
        "first_name": "Alice", "last_name": "Walker", "email": "alice@quote.com",
        "phone": "+1-925-555-0101", "address": "100 Plaza, San Ramon, CA",
        "username": "alicew", "password": "Password123"
    }).json()
    owner_id = reg_o["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": reg_o["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": reg_o["demo_otps"]["phone_code"]})

    # 2. Create Item: $20/day, $100 deposit, insurance required=True
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Stihl Gas String Trimmer",
        "category": "Lawn & Garden",
        "condition": "Good",
        "description": "Powerful 2-cycle trimmer for yard work.",
        "base_rate_daily": 20.0,
        "security_deposit": 100.0,
        "item_value": 300.0,
        "min_rental_days": 2,
        "max_rental_days": 10,
        "deposit_required": True,
        "insurance_required": True,
        "location_city": "San Ramon, CA"
    })
    item_id = item_res.json()["id"]

    start_d = date.today().isoformat()
    end_d = (date.today() + timedelta(days=3)).isoformat()  # 3 days

    res = client.post(f"/api/items/{item_id}/quote", json={
        "start_date": start_d,
        "end_date": end_d
    })
    assert res.status_code == 200
    data = res.json()
    assert data["total_days"] == 3
    assert data["daily_rate"] == 20.0
    assert data["base_rent"] == 60.0
    assert data["service_fee_fixed"] == 1.00
    assert data["service_fee_pct"] == 3.00  # 5% of $60
    assert data["service_fee_total"] == 4.00
    assert data["insurance_fee"] == 4.80  # 8% of $60
    assert data["security_deposit"] == 100.0
    # Total = 60 + 4 + 4.80 + 100 = 168.80
    assert data["total_due_now"] == 168.80
