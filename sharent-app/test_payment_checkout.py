import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, PaymentTransaction, ItemAvailability

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_payment_processing_and_escrow_deposit_hold():
    # 1. Register and verify Owner
    reg_o = client.post("/api/register", json={
        "first_name": "Alice", "last_name": "Walker", "email": "alice@pay.com",
        "phone": "+1-925-555-0301", "address": "100 Pay St, San Ramon, CA",
        "username": "alicew_pay", "password": "Password123"
    }).json()
    owner_id = reg_o["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": reg_o["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": reg_o["demo_otps"]["phone_code"]})

    # 2. Register and verify Renter
    reg_r = client.post("/api/register", json={
        "first_name": "Bob", "last_name": "Builder", "email": "bob@pay.com",
        "phone": "+1-925-555-0302", "address": "200 Pay St, San Ramon, CA",
        "username": "bobb_pay", "password": "Password123"
    }).json()
    renter_id = reg_r["user_id"]
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "email", "otp_code": reg_r["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "phone", "otp_code": reg_r["demo_otps"]["phone_code"]})

    # 3. Create Item
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Makita Sub-Compact Cordless Drill Driver",
        "category": "Power Tools",
        "condition": "Excellent",
        "description": "Compact and powerful 18V drill with charger.",
        "base_rate_daily": 15.0,
        "security_deposit": 100.0,
        "item_value": 200.0,
        "min_rental_days": 1,
        "max_rental_days": 10,
        "deposit_required": True,
        "insurance_required": True,
        "location_city": "San Ramon, CA"
    })
    item_id = item_res.json()["id"]

    start_d = date.today().isoformat()
    end_d = (date.today() + timedelta(days=2)).isoformat()

    # 4. Create Rental Agreement
    agr_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": renter_id,
        "start_date": start_d,
        "end_date": end_d,
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    agreement_id = agr_res.json()["id"]

    # 5. Test Invalid Card Format (rejection)
    fail_card = client.post("/api/checkout/pay", json={
        "agreement_id": agreement_id,
        "renter_id": renter_id,
        "payment_method": "credit_card",
        "card_number": "1234",
        "exp_month": "12",
        "exp_year": "28",
        "cvv": "123",
        "billing_zip": "94583"
    })
    assert fail_card.status_code == 400
    assert "Invalid card number" in fail_card.json()["detail"]

    # 6. Test Simulated Card Decline (ends in 0000)
    decline_res = client.post("/api/checkout/pay", json={
        "agreement_id": agreement_id,
        "renter_id": renter_id,
        "payment_method": "credit_card",
        "card_number": "4242424242420000",
        "exp_month": "12",
        "exp_year": "28",
        "cvv": "123",
        "billing_zip": "94583"
    })
    assert decline_res.status_code == 402
    assert "Card was declined" in decline_res.json()["detail"]

    # 7. Successful Payment Authorization & Escrow Deposit Hold
    pay_res = client.post("/api/checkout/pay", json={
        "agreement_id": agreement_id,
        "renter_id": renter_id,
        "payment_method": "credit_card",
        "card_number": "4242424242424242",
        "exp_month": "12",
        "exp_year": "28",
        "cvv": "424",
        "billing_zip": "94583"
    })
    assert pay_res.status_code == 200
    pdata = pay_res.json()
    assert pdata["transaction_code"].startswith("TXN-")
    assert pdata["card_last4"] == "4242"
    assert pdata["escrow_deposit_held"] == 100.0
    assert pdata["amount_charged"] > 0
    assert len(pdata["handover_pin"]) == 4
    assert pdata["handover_pin"].isdigit()

    # 8. Verify Calendar Availability is now locked as 'booked'
    cal_check = client.post(f"/api/items/{item_id}/availability/check-range", json={
        "start_date": start_d,
        "end_date": end_d
    })
    assert cal_check.json()["is_available"] is False
    assert "unavailable" in cal_check.json()["reason"].lower()

    # 9. Verify Duplicate Payment Attempt is Blocked
    dup_res = client.post("/api/checkout/pay", json={
        "agreement_id": agreement_id,
        "renter_id": renter_id,
        "payment_method": "credit_card",
        "card_number": "4242424242424242",
        "exp_month": "12",
        "exp_year": "28",
        "cvv": "424",
        "billing_zip": "94583"
    })
    assert dup_res.status_code == 400
    assert "already been processed" in dup_res.json()["detail"]
