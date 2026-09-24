import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, SessionLocal, User, Item, RentalAgreement, RentalReview, PaymentTransaction, RentalHandoverInspection

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def test_owner_discretionary_security_deposit_lifecycle():
    # 1. Register Owner (Alice)
    alice_res = client.post("/api/register", json={
        "first_name": "Alice",
        "last_name": "Owner",
        "email": "alice.owner@sharent.com",
        "phone": "+19255550001",
        "address": "100 Market St, San Ramon, CA",
        "username": "aliceowner",
        "password": "Password123!"
    })
    assert alice_res.status_code == 200
    alice_id = alice_res.json()["user_id"]
    client.post(f"/api/verify-otp-direct/{alice_id}")

    # 2. Register Renter 1 (Bob - Newly Registered, No Reviews, No History)
    bob_res = client.post("/api/register", json={
        "first_name": "Bob",
        "last_name": "NewUser",
        "email": "bob.new@sharent.com",
        "phone": "+19255550002",
        "address": "200 Alcosta Blvd, San Ramon, CA",
        "username": "bobnew",
        "password": "Password123!"
    })
    assert bob_res.status_code == 200
    bob_id = bob_res.json()["user_id"]
    client.post(f"/api/verify-otp-direct/{bob_id}")

    # 3. Register Renter 2 (Charlie - Highly Rated Community Renter)
    charlie_res = client.post("/api/register", json={
        "first_name": "Charlie",
        "last_name": "RatedUser",
        "email": "charlie.rated@sharent.com",
        "phone": "+19255550003",
        "address": "300 Bollinger Canyon Rd, San Ramon, CA",
        "username": "charlierated",
        "password": "Password123!"
    })
    assert charlie_res.status_code == 200
    charlie_id = charlie_res.json()["user_id"]
    client.post(f"/api/verify-otp-direct/{charlie_id}")

    # 4. Register Owner 2 (Dave - who previously reviewed Charlie)
    dave_res = client.post("/api/register", json={
        "first_name": "Dave",
        "last_name": "OtherOwner",
        "email": "dave.owner@sharent.com",
        "phone": "+19255550004",
        "address": "400 Crow Canyon Rd, San Ramon, CA",
        "username": "daveowner",
        "password": "Password123!"
    })
    assert dave_res.status_code == 200
    dave_id = dave_res.json()["user_id"]
    client.post(f"/api/verify-otp-direct/{dave_id}")

    # 5. Alice lists an Item with $100 Security Deposit
    item_res = client.post("/api/items", json={
        "owner_id": alice_id,
        "title": "Stihl Gas Chainsaw",
        "category": "Power Tools",
        "description": "Professional 18-inch chainsaw.",
        "condition": "Like New",
        "base_rate_daily": 30.0,
        "security_deposit": 100.0,
        "item_value": 450.0,
        "min_rental_days": 1,
        "max_rental_days": 7
    })
    assert item_res.status_code == 200
    item_id = item_res.json()["id"]

    start_date = (date.today() + timedelta(days=2)).isoformat()
    end_date = (date.today() + timedelta(days=4)).isoformat()  # 2 days

    # -------------------------------------------------------------
    # CASE 1: Newly registered user (Bob) with no reviews or history
    # Expectation: 100% full deposit ($100.00)
    # -------------------------------------------------------------
    quote_bob = client.post(f"/api/items/{item_id}/quote", json={
        "start_date": start_date,
        "end_date": end_date,
        "renter_id": bob_id
    })
    assert quote_bob.status_code == 200
    q_bob_data = quote_bob.json()
    assert q_bob_data["security_deposit"] == 100.0
    assert q_bob_data["deposit_tier_status"] == "standard_full"
    assert q_bob_data["deposit_discount_pct"] == 0.0
    assert "Standard full deposit required" in q_bob_data["deposit_evaluation_reason"]

    # -------------------------------------------------------------
    # CASE 2: Highly rated community renter (Charlie) with >= 4.5 star reviews
    # Create a past review for Charlie from Dave (5.0 rating)
    # Expectation: 50% deposit discount ($50.00 instead of $100.00)
    # -------------------------------------------------------------
    db = SessionLocal()
    dummy_agr = RentalAgreement(
        item_id=item_id,
        renter_id=charlie_id,
        owner_id=dave_id,
        start_date=date.today() - timedelta(days=10),
        end_date=date.today() - timedelta(days=8),
        total_days=2,
        daily_rate=25.0,
        base_rent=50.0,
        security_deposit=80.0,
        service_fee=3.5,
        insurance_fee=0.0,
        total_amount=133.5,
        status="completed"
    )
    db.add(dummy_agr)
    db.commit()
    db.refresh(dummy_agr)

    charlie_review = RentalReview(
        agreement_id=dummy_agr.id,
        reviewer_id=dave_id,
        reviewee_id=charlie_id,
        role="owner_to_renter",
        rating=5.0,
        comment="Charlie returned the equipment in immaculate shape. Great communication!",
        renter_communication=5,
        renter_responsibility=5,
        renter_friendliness=5,
        renter_care_of_item=5,
        renter_return_condition=5
    )
    db.add(charlie_review)
    db.commit()
    db.close()

    quote_charlie = client.post(f"/api/items/{item_id}/quote", json={
        "start_date": start_date,
        "end_date": end_date,
        "renter_id": charlie_id
    })
    assert quote_charlie.status_code == 200
    q_charlie_data = quote_charlie.json()
    assert q_charlie_data["original_security_deposit"] == 100.0
    assert q_charlie_data["security_deposit"] == 50.0
    assert q_charlie_data["deposit_tier_status"] == "reduced_half"
    assert q_charlie_data["deposit_discount_pct"] == 50.0
    assert "50% Deposit Reduction Applied" in q_charlie_data["deposit_evaluation_reason"]

    # -------------------------------------------------------------
    # CASE 3: Repeat trusted renter with this specific Owner (Alice)
    # Charlie completes a rental with Alice without dispute
    # Expectation: 100% waiver ($0.00 deposit) for next transaction with Alice
    # -------------------------------------------------------------
    db = SessionLocal()
    alice_charlie_agr = RentalAgreement(
        item_id=item_id,
        renter_id=charlie_id,
        owner_id=alice_id,
        start_date=date.today() - timedelta(days=6),
        end_date=date.today() - timedelta(days=4),
        total_days=2,
        daily_rate=30.0,
        base_rent=60.0,
        security_deposit=50.0,
        service_fee=4.0,
        insurance_fee=0.0,
        total_amount=114.0,
        status="completed"
    )
    db.add(alice_charlie_agr)
    db.commit()
    db.close()

    # Now Charlie requests another quote from Alice
    future_start = (date.today() + timedelta(days=10)).isoformat()
    future_end = (date.today() + timedelta(days=12)).isoformat()

    quote_repeat = client.post(f"/api/items/{item_id}/quote", json={
        "start_date": future_start,
        "end_date": future_end,
        "renter_id": charlie_id
    })
    assert quote_repeat.status_code == 200
    q_repeat_data = quote_repeat.json()
    assert q_repeat_data["original_security_deposit"] == 100.0
    assert q_repeat_data["security_deposit"] == 0.0
    assert q_repeat_data["deposit_tier_status"] == "waived"
    assert q_repeat_data["deposit_discount_pct"] == 100.0
    assert "Security Deposit 100% Waived!" in q_repeat_data["deposit_evaluation_reason"]

    # -------------------------------------------------------------
    # Agreement Execution Test:
    # Ensure agreement records and persists the waived security deposit
    # -------------------------------------------------------------
    agr_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": charlie_id,
        "start_date": future_start,
        "end_date": future_end,
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    assert agr_res.status_code == 200
    agr_data = agr_res.json()
    assert agr_data["security_deposit"] == 0.0
    assert agr_data["original_security_deposit"] == 100.0
    assert agr_data["deposit_discount_pct"] == 100.0
    assert "100% Waived" in agr_data["deposit_evaluation_reason"]
