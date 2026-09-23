import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, PaymentTransaction, RentalHandoverInspection

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_handover_pin_verification_and_return_inspection_lifecycle():
    # 1. Register Owner
    reg_o = client.post("/api/register", json={
        "first_name": "Alice", "last_name": "Walker", "email": "alice@insp.com",
        "phone": "+1-925-555-0401", "address": "100 Insp Rd, San Ramon, CA",
        "username": "alicew_insp", "password": "Password123"
    }).json()
    owner_id = reg_o["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": reg_o["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": reg_o["demo_otps"]["phone_code"]})

    # 2. Register Renter
    reg_r = client.post("/api/register", json={
        "first_name": "Bob", "last_name": "Builder", "email": "bob@insp.com",
        "phone": "+1-925-555-0402", "address": "200 Insp Rd, San Ramon, CA",
        "username": "bobb_insp", "password": "Password123"
    }).json()
    renter_id = reg_r["user_id"]
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "email", "otp_code": reg_r["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "phone", "otp_code": reg_r["demo_otps"]["phone_code"]})

    # 3. Create Item
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Stihl Gas Powered Hedge Trimmer",
        "category": "Lawn & Garden",
        "condition": "Like New",
        "description": "Professional 24-inch dual-action hedge trimmer.",
        "base_rate_daily": 25.0,
        "security_deposit": 150.0,
        "item_value": 350.0,
        "min_rental_days": 1,
        "max_rental_days": 7,
        "deposit_required": True,
        "insurance_required": True,
        "location_city": "San Ramon, CA"
    })
    item_id = item_res.json()["id"]

    start_d = date.today().isoformat()
    end_d = (date.today() + timedelta(days=2)).isoformat()

    # 4. Create Agreement & Complete Payment
    agr_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": renter_id,
        "start_date": start_d,
        "end_date": end_d,
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    agr_id = agr_res.json()["id"]

    pay_res = client.post("/api/checkout/pay", json={
        "agreement_id": agr_id,
        "renter_id": renter_id,
        "payment_method": "credit_card",
        "card_number": "4242424242424242",
        "exp_month": "12",
        "exp_year": "28",
        "cvv": "424",
        "billing_zip": "94583"
    })
    handover_pin = pay_res.json()["handover_pin"]

    # 5. Non-owner tries to verify handover -> 403 Forbidden
    unauth = client.post("/api/rentals/verify-handover", json={
        "agreement_id": agr_id,
        "owner_id": renter_id, # not the owner!
        "entered_pin": handover_pin
    })
    assert unauth.status_code == 403

    # 6. Incorrect PIN -> 400 Bad Request
    wrong_pin = client.post("/api/rentals/verify-handover", json={
        "agreement_id": agr_id,
        "owner_id": owner_id,
        "entered_pin": "0000"
    })
    assert wrong_pin.status_code == 400
    assert "Invalid Handover PIN" in wrong_pin.json()["detail"]

    # 7. Correct PIN Handover Verification -> Transitions agreement status to 'active'
    ok_handover = client.post("/api/rentals/verify-handover", json={
        "agreement_id": agr_id,
        "owner_id": owner_id,
        "entered_pin": handover_pin,
        "pickup_notes": "Fuel tank full, blades lubricated, renter instructed on start switch."
    })
    assert ok_handover.status_code == 200
    assert ok_handover.json()["status"] == "active"

    # 8. Return Inspection -> Verifies condition & releases 100% escrow deposit
    insp_res = client.post("/api/rentals/return-inspection", json={
        "agreement_id": agr_id,
        "owner_id": owner_id,
        "condition_on_return": "like_new",
        "all_accessories_returned": True,
        "cleaned_properly": True,
        "inspection_notes": "Returned clean, full tank of 50:1 mix, zero damage."
    })
    assert insp_res.status_code == 200
    idata = insp_res.json()
    assert idata["status"] == "completed"
    assert idata["deposit_refund_status"] == "released"
    assert idata["deposit_refunded_amount"] == 150.0

    # 9. Verify User Rentals endpoint reflects completed status & refund
    user_rentals = client.get(f"/api/rentals/user/{renter_id}?role=renter")
    assert user_rentals.status_code == 200
    assert len(user_rentals.json()) == 1
    assert user_rentals.json()[0]["status"] == "completed"
    assert user_rentals.json()[0]["deposit_refund_status"] == "released"
