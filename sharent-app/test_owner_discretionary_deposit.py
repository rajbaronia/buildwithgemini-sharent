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


def test_owner_manual_deposit_adjustment_and_waiver():
    # 1. Register Owner (Olivia)
    olivia_res = client.post("/api/register", json={
        "first_name": "Olivia",
        "last_name": "Owner",
        "email": "olivia.owner@sharent.com",
        "phone": "+19255551001",
        "address": "500 Bollinger Canyon Rd, San Ramon, CA",
        "username": "oliviaowner",
        "password": "Password123!"
    })
    assert olivia_res.status_code == 200
    olivia_id = olivia_res.json()["user_id"]
    client.post(f"/api/verify-otp-direct/{olivia_id}")

    # 2. Register Renter (Ryan - Brand new user, no reviews)
    ryan_res = client.post("/api/register", json={
        "first_name": "Ryan",
        "last_name": "Renter",
        "email": "ryan.renter@sharent.com",
        "phone": "+19255551002",
        "address": "600 Norris Canyon Rd, San Ramon, CA",
        "username": "ryanrenter",
        "password": "Password123!"
    })
    assert ryan_res.status_code == 200
    ryan_id = ryan_res.json()["user_id"]
    client.post(f"/api/verify-otp-direct/{ryan_id}")

    # 3. Olivia lists a Commercial Generator with $200 security deposit
    item_res = client.post("/api/items", json={
        "owner_id": olivia_id,
        "title": "Honda Inverter Generator",
        "category": "Power Tools",
        "description": "Quiet Honda 3000W generator.",
        "condition": "Excellent",
        "base_rate_daily": 40.0,
        "security_deposit": 200.0,
        "item_value": 1200.0,
        "min_rental_days": 1,
        "max_rental_days": 5
    })
    assert item_res.status_code == 200
    item_id = item_res.json()["id"]

    start_date = (date.today() + timedelta(days=3)).isoformat()
    end_date = (date.today() + timedelta(days=5)).isoformat()

    # 4. Ryan creates agreement with initial automated evaluation (requires standard $200 deposit)
    agr_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": ryan_id,
        "start_date": start_date,
        "end_date": end_date,
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    assert agr_res.status_code == 200
    agr_data = agr_res.json()
    agr_id = agr_data["id"]
    assert agr_data["security_deposit"] == 200.0
    assert agr_data["status"] == "pending_payment"

    # 5. Non-owner cannot adjust deposit (403 Forbidden)
    fraud_res = client.post(f"/api/rental-agreements/{agr_id}/adjust-deposit", json={
        "owner_id": ryan_id,
        "action": "waive",
        "notes": "I want zero deposit"
    })
    assert fraud_res.status_code == 403

    # 6. Owner Olivia reduces deposit to custom amount ($50.00) on case-by-case basis
    reduce_res = client.post(f"/api/rental-agreements/{agr_id}/adjust-deposit", json={
        "owner_id": olivia_id,
        "action": "custom",
        "new_deposit": 50.0,
        "notes": "Neighbor discount agreed upon via chat."
    })
    assert reduce_res.status_code == 200
    red_data = reduce_res.json()
    assert red_data["security_deposit"] == 50.0
    assert red_data["deposit_adjusted_by_owner"] is True
    assert red_data["deposit_discount_pct"] == 75.0  # 200 -> 50 = 75% off
    assert "Neighbor discount agreed upon" in red_data["owner_adjustment_notes"]

    # 7. Owner Olivia decides to completely WAIVE the deposit ($0.00)
    waive_res = client.post(f"/api/rental-agreements/{agr_id}/adjust-deposit", json={
        "owner_id": olivia_id,
        "action": "waive",
        "notes": "Verified company ID - deposit 100% waived."
    })
    assert waive_res.status_code == 200
    waive_data = waive_res.json()
    assert waive_data["security_deposit"] == 0.0
    assert waive_data["deposit_discount_pct"] == 100.0
    assert waive_data["deposit_adjusted_by_owner"] is True
    assert "100% Waived by Owner" in waive_data["deposit_evaluation_reason"]

    # 8. Check that user rentals view reflects this manual waiver
    rentals_res = client.get(f"/api/rentals/user/{ryan_id}?role=renter")
    assert rentals_res.status_code == 200
    ryan_rentals = rentals_res.json()
    target_r = next(r for r in ryan_rentals if r["agreement_id"] == agr_id)
    assert target_r["security_deposit"] == 0.0
    assert target_r["deposit_adjusted_by_owner"] is True
    assert "100% Waived by Owner" in target_r["deposit_evaluation_reason"]
