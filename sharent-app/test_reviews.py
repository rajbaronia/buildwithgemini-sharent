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

def test_mutual_rating_and_review_lifecycle():
    # 1. Register Owner
    reg_o = client.post("/api/register", json={
        "first_name": "Alice", "last_name": "Walker", "email": "alice@rev.com",
        "phone": "+1-925-555-0501", "address": "100 Rev St, San Ramon, CA",
        "username": "alicew_rev", "password": "Password123"
    }).json()
    owner_id = reg_o["user_id"]
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "email", "otp_code": reg_o["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owner_id, "channel": "phone", "otp_code": reg_o["demo_otps"]["phone_code"]})

    # 2. Register Renter
    reg_r = client.post("/api/register", json={
        "first_name": "Bob", "last_name": "Builder", "email": "bob@rev.com",
        "phone": "+1-925-555-0502", "address": "200 Rev St, San Ramon, CA",
        "username": "bobb_rev", "password": "Password123"
    }).json()
    renter_id = reg_r["user_id"]
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "email", "otp_code": reg_r["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": renter_id, "channel": "phone", "otp_code": reg_r["demo_otps"]["phone_code"]})

    # 3. Create Item
    item_res = client.post("/api/items", json={
        "owner_id": owner_id,
        "title": "Bissell Big Green Carpet Cleaner",
        "category": "Home Appliances",
        "condition": "Excellent",
        "description": "Professional grade carpet deep cleaner.",
        "base_rate_daily": 30.0,
        "security_deposit": 100.0,
        "item_value": 400.0,
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

    # 5. Attempt review before rental completed -> 400 Bad Request
    early_rev = client.post("/api/reviews", json={
        "agreement_id": agr_id,
        "reviewer_id": renter_id,
        "rating": 5,
        "comment": "Awesome tool!",
        "tags": ["Clean & Like New"]
    })
    assert early_rev.status_code == 400
    assert "completed and returned" in early_rev.json()["detail"]

    # 6. Handover & Return Inspection
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

    # 7. Renter submits Review for Item & Owner
    renter_rev = client.post("/api/reviews", json={
        "agreement_id": agr_id,
        "reviewer_id": renter_id,
        "rating": 5,
        "comment": "Carpet cleaner made our rugs look brand new. Alice was super accommodating!",
        "tags": ["Clean & Like New", "Smooth Handover", "Great Communication"]
    })
    assert renter_rev.status_code == 200
    rdata = renter_rev.json()
    assert rdata["rating"] == 5
    assert rdata["role"] == "renter_to_owner"
    assert "Clean & Like New" in rdata["tags"]

    # 8. Duplicate Review Prevention
    dup_rev = client.post("/api/reviews", json={
        "agreement_id": agr_id,
        "reviewer_id": renter_id,
        "rating": 4,
        "comment": "Trying to review twice"
    })
    assert dup_rev.status_code == 400
    assert "already submitted a review" in dup_rev.json()["detail"]

    # 9. Owner submits Review for Renter
    owner_rev = client.post("/api/reviews", json={
        "agreement_id": agr_id,
        "reviewer_id": owner_id,
        "rating": 5,
        "comment": "Bob returned the cleaner spotless and on time. Would happily rent to him anytime!",
        "tags": ["Punctual", "Treated Item with Care"]
    })
    assert owner_rev.status_code == 200
    odata = owner_rev.json()
    assert odata["role"] == "owner_to_renter"

    # 10. Verify Item Review Summary endpoint returns 5.0 and review list
    item_rev_summary = client.get(f"/api/items/{item_id}/reviews")
    assert item_rev_summary.status_code == 200
    sdata = item_rev_summary.json()
    assert sdata["total_reviews"] == 1
    assert sdata["average_rating"] == 5.0
    assert len(sdata["reviews"]) == 1
    assert sdata["reviews"][0]["comment"] == "Carpet cleaner made our rugs look brand new. Alice was super accommodating!"
