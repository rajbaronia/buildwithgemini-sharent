import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, PaymentTransaction, RentalHandoverInspection, RentalReview

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_airbnb_style_granular_rating_lifecycle():
    # 1. Register Owner
    reg_o = client.post("/api/register", json={
        "first_name": "Alice", "last_name": "Walker", "email": "alice@airbnb.com",
        "phone": "+1-925-555-0801", "address": "100 Airbnb St, San Ramon, CA",
        "username": "alicew_ab", "password": "Password123"
    }).json()
    owner_id = reg_o["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": reg_o["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": reg_o["demo_otps"]["phone_code"]})

    # 2. Register Renter
    reg_r = client.post("/api/register", json={
        "first_name": "Bob", "last_name": "Builder", "email": "bob@airbnb.com",
        "phone": "+1-925-555-0802", "address": "200 Airbnb St, San Ramon, CA",
        "username": "bobb_ab", "password": "Password123"
    }).json()
    renter_id = reg_r["user_id"]
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "email", "otp_code": reg_r["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "phone", "otp_code": reg_r["demo_otps"]["phone_code"]})

    # 3. Create Item
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "DeWalt 20V Cordless Hammer Drill Kit",
        "category": "Power Tools",
        "condition": "Excellent",
        "description": "High performance hammer drill with 2 batteries.",
        "base_rate_daily": 25.0,
        "security_deposit": 80.0,
        "item_value": 250.0,
        "min_rental_days": 1,
        "max_rental_days": 5,
        "deposit_required": True,
        "insurance_required": True,
        "location_city": "San Ramon, CA"
    })
    item_id = item_res.json()["id"]

    start_d = date.today().isoformat()
    end_d = (date.today() + timedelta(days=2)).isoformat()

    # 4. Create Agreement & Checkout
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
    pin = pay_res.json()["handover_pin"]

    # 5. Handover & Return Inspection to Complete
    client.post("/api/rentals/verify-handover", json={
        "agreement_id": agr_id,
        "owner_id": owner_id,
        "entered_pin": pin
    })
    client.post("/api/rentals/return-inspection", json={
        "agreement_id": agr_id,
        "owner_id": owner_id,
        "condition_on_return": "like_new",
        "all_accessories_returned": True,
        "cleaned_properly": True
    })

    # 6. Renter rates Item (5 criteria) and Owner (5 criteria)
    # Item: Accuracy=5, Condition=5, Ease=4, Instructions=5, Value=4
    # Owner: Response=5, Communication=5, Friendliness=5, Pickup=5, Return=5
    # Total sum = 48 / 10 = 4.8
    renter_rev = client.post("/api/reviews", json={
        "agreement_id": agr_id,
        "reviewer_id": renter_id,
        "comment": "Tool was in mint condition and performed flawlessly. Alice was super friendly and punctual!",
        "tags": ["Clean & Like New", "Smooth Handover", "Great Communication"],
        # Item criteria
        "item_accuracy": 5,
        "item_condition": 5,
        "item_ease_of_use": 4,
        "item_instructions": 5,
        "item_value": 4,
        # Owner criteria
        "owner_response_time": 5,
        "owner_communication": 5,
        "owner_friendliness": 5,
        "owner_pickup_ease": 5,
        "owner_return_ease": 5
    })
    assert renter_rev.status_code == 200
    rdata = renter_rev.json()
    assert rdata["rating"] == 4.8
    assert rdata["item_accuracy"] == 5
    assert rdata["item_condition"] == 5
    assert rdata["item_ease_of_use"] == 4
    assert rdata["owner_friendliness"] == 5

    # 7. Owner rates Renter on 5 Renter criteria
    # Renter: Communication=5, Responsible=5, Friendliness=5, Care=5, Return Condition=5
    # Average = 5.0
    owner_rev = client.post("/api/reviews", json={
        "agreement_id": agr_id,
        "reviewer_id": owner_id,
        "comment": "Bob treated the drill with utmost care and returned it on time with full batteries.",
        "tags": ["Punctual", "Treated Item with Care"],
        # Renter criteria
        "renter_communication": 5,
        "renter_responsibility": 5,
        "renter_friendliness": 5,
        "renter_care_of_item": 5,
        "renter_return_condition": 5
    })
    assert owner_rev.status_code == 200
    odata = owner_rev.json()
    assert odata["rating"] == 5.0
    assert odata["renter_care_of_item"] == 5
    assert odata["renter_responsibility"] == 5

    # 8. Check Item Review Summary with Airbnb-style Criteria Breakdown
    item_rev_summary = client.get(f"/api/items/{item_id}/reviews")
    assert item_rev_summary.status_code == 200
    sdata = item_rev_summary.json()
    assert sdata["total_reviews"] == 1
    assert sdata["average_rating"] == 4.8
    assert sdata["criteria_breakdown"]["accuracy"] == 5.0
    assert sdata["criteria_breakdown"]["condition"] == 5.0
    assert sdata["criteria_breakdown"]["ease_of_use"] == 4.0
    assert sdata["criteria_breakdown"]["instructions"] == 5.0
    assert sdata["criteria_breakdown"]["value"] == 4.0
