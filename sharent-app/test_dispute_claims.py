import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, PaymentTransaction, DisputeClaim, UserWallet, WalletTransaction

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_dispute_and_damage_claim_full_lifecycle():
    # 1. Register Owner ("Owen") and Renter ("Rachel")
    owen_reg = client.post("/api/register", json={
        "first_name": "Owen", "last_name": "Owner", "email": "owen@dispute.com",
        "phone": "+1-925-555-4001", "address": "101 Tool Lane, Dublin, CA",
        "username": "owenowner", "password": "Password123"
    }).json()
    owen_id = owen_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": owen_id, "channel": "email", "otp_code": owen_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": owen_id, "channel": "phone", "otp_code": owen_reg["demo_otps"]["phone_code"]})

    rachel_reg = client.post("/api/register", json={
        "first_name": "Rachel", "last_name": "Renter", "email": "rachel@dispute.com",
        "phone": "+1-925-555-4002", "address": "202 Renter Blvd, Dublin, CA",
        "username": "rachelrenter", "password": "Password123"
    }).json()
    rachel_id = rachel_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": rachel_id, "channel": "email", "otp_code": rachel_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": rachel_id, "channel": "phone", "otp_code": rachel_reg["demo_otps"]["phone_code"]})

    # 2. Owen lists an expensive Pressure Washer with $100 security deposit
    item_res = client.post("/api/items", json={
        "owner_id": owen_id,
        "title": "Commercial Gas Pressure Washer",
        "category": "Power Equipment",
        "description": "3200 PSI commercial grade pressure washer",
        "condition": "Excellent",
        "base_rate_daily": 50.0,
        "security_deposit": 100.0,
        "item_value": 600.0,
        "location_city": "Dublin, CA"
    })
    assert item_res.status_code == 200
    item_id = item_res.json()["id"]

    # 3. Create Rental Agreement and process payment checkout
    start_d = date.today() + timedelta(days=1)
    end_d = start_d + timedelta(days=2)
    agr_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": rachel_id,
        "start_date": str(start_d),
        "end_date": str(end_d),
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    assert agr_res.status_code == 200
    agr_id = agr_res.json()["id"]

    # Checkout payment with deposit escrow hold
    checkout_res = client.post("/api/checkout/pay", json={
        "agreement_id": agr_id,
        "renter_id": rachel_id,
        "payment_method": "credit_card",
        "card_number": "4242424242424242",
        "exp_month": "12",
        "exp_year": "28",
        "cvv": "424",
        "billing_zip": "94568"
    })
    assert checkout_res.status_code == 200
    assert checkout_res.json()["escrow_deposit_held"] == 100.0
    assert checkout_res.json()["payment_status"] == "Confirmed & Escrow Held"

    # 4. Item returned with damage: Owen files a Dispute Claim
    claim_payload = {
        "agreement_id": agr_id,
        "claimant_id": owen_id,
        "claim_type": "damage",
        "requested_amount": 75.0,
        "claimant_description": "The high-pressure hose was cracked and wand trigger nozzle broken upon return.",
        "photos": ["/static/uploads/damaged_hose.jpg", "/static/uploads/broken_wand.jpg"]
    }
    claim_res = client.post("/api/disputes", json=claim_payload)
    assert claim_res.status_code == 200
    claim_data = claim_res.json()
    assert claim_data["status"] == "open"
    assert claim_data["claimant_name"] == "Owen Owner"
    assert claim_data["respondent_name"] == "Rachel Renter"
    assert claim_data["requested_amount"] == 75.0
    assert len(claim_data["photos"]) == 2
    claim_id = claim_data["id"]

    # Verify dispute is retrievable by agreement
    agr_disputes = client.get(f"/api/disputes/agreement/{agr_id}").json()
    assert len(agr_disputes) == 1
    assert agr_disputes[0]["id"] == claim_id

    # 5. Respondent (Rachel) submits a response
    resp_res = client.post(f"/api/disputes/{claim_id}/respond", json={
        "respondent_id": rachel_id,
        "respondent_response": "The wand already had existing hairline cracks at pickup. However, I agree the hose wore down.",
        "photos": ["/static/uploads/pickup_wand_proof.jpg"]
    })
    assert resp_res.status_code == 200
    assert resp_res.json()["status"] == "under_review"
    assert "hairline cracks" in resp_res.json()["respondent_response"]
    assert len(resp_res.json()["respondent_photos"]) == 1

    # 6. Admin lists all disputes
    admin_list = client.get("/api/admin/disputes?status=under_review").json()
    assert len(admin_list) >= 1
    assert any(c["id"] == claim_id for c in admin_list)

    # 7. Admin resolves the dispute with Partial Settlement ($50 to Owner, $50 refund to Renter)
    resolve_res = client.post(f"/api/admin/disputes/{claim_id}/resolve", json={
        "decision": "approve_partial",
        "approved_amount_to_owner": 50.0,
        "admin_notes": "Wear on hose is renter responsibility; wand pre-existing crack discounted. Awarding $50 damage settlement to owner, refunding $50 deposit balance to renter."
    })
    assert resolve_res.status_code == 200
    res_data = resolve_res.json()
    assert res_data["status"] == "resolved_split"
    assert res_data["settled_amount_to_owner"] == 50.0
    assert res_data["settled_amount_refunded_to_renter"] == 50.0
    assert res_data["resolved_at"] is not None

    # 8. Verify Financial Disbursals in Wallets
    # Owner's wallet: received $50 withdrawable cash dispute payout
    owen_w = client.get(f"/api/wallet/{owen_id}").json()
    assert owen_w["withdrawable_cash_balance"] == 140.0  # 0 rental earnings (00 - 10% platform fee) + 0 dispute settlement
    assert any(tx["transaction_type"] == "dispute_payout" and tx["amount"] == 50.0 for tx in owen_w["transactions"])

    # Renter's wallet: received remaining $50 withdrawable cash deposit refund
    rachel_w = client.get(f"/api/wallet/{rachel_id}").json()
    assert rachel_w["withdrawable_cash_balance"] == 50.0
    assert any(tx["transaction_type"] == "deposit_refund" and tx["amount"] == 50.0 for tx in rachel_w["transactions"])
