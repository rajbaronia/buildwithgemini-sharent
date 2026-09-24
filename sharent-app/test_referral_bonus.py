import pytest
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, UserWallet, WalletTransaction, PromotionalProgramConfig, UserBonusTracker, UserReferral

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_multi_channel_social_referral_workflow():
    # 1. Verify default referral promotion variables
    cfg_res = client.get("/api/admin/promotions/signup-bonus")
    assert cfg_res.status_code == 200
    cfg = cfg_res.json()
    assert cfg["referrer_bonus_amount"] == 15.0
    assert cfg["invitee_bonus_amount"] == 20.0
    assert cfg["required_active_items"] == 10
    assert cfg["required_active_days"] == 90

    # 2. Register Existing User (Referrer - "Alice")
    alice_reg = client.post("/api/register", json={
        "first_name": "Alice", "last_name": "Ambassador", "email": "alice@refer.com",
        "phone": "+1-925-555-1111", "address": "100 Community Rd, San Ramon, CA",
        "username": "aliceambassador", "password": "Password123"
    }).json()
    alice_id = alice_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": alice_id, "channel": "email", "otp_code": alice_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": alice_id, "channel": "phone", "otp_code": alice_reg["demo_otps"]["phone_code"]})

    # Alice fetches her referral code and social share links
    ref_res = client.get(f"/api/referrals/my-code/{alice_id}")
    assert ref_res.status_code == 200
    ref_data = ref_res.json()
    alice_code = ref_data["referral_code"]
    assert alice_code.startswith("REF-ALIC-")
    assert "whatsapp" in ref_data["share_links"]
    assert "email" in ref_data["share_links"]
    assert "facebook" in ref_data["share_links"]
    assert "twitter" in ref_data["share_links"]
    assert alice_code in ref_data["share_links"]["whatsapp"]
    assert ref_data["referrer_bonus_amount"] == 15.0
    assert ref_data["invitee_bonus_amount"] == 20.0
    assert ref_data["completed_referrals"] == 0
    assert ref_data["pending_referrals"] == 0

    # Alice's initial wallet should be 0.0 promo credits
    w_alice_init = client.get(f"/api/wallet/{alice_id}").json()
    assert w_alice_init["promotional_credit_balance"] == 0.0

    # 3. Invitee ("Bob") receives referral code and registers
    bob_reg = client.post("/api/register", json={
        "first_name": "Bob", "last_name": "Builder", "email": "bob@refer.com",
        "phone": "+1-925-555-2222", "address": "200 Community Rd, San Ramon, CA",
        "username": "bobbuilder", "password": "Password123",
        "referral_code": alice_code  # Uses Alice's referral code
    }).json()
    bob_id = bob_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": bob_id, "channel": "email", "otp_code": bob_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": bob_id, "channel": "phone", "otp_code": bob_reg["demo_otps"]["phone_code"]})

    # Check Alice's referral dashboard: 1 pending referral!
    alice_dashboard1 = client.get(f"/api/referrals/my-code/{alice_id}").json()
    assert alice_dashboard1["total_referrals_sent"] == 1
    assert alice_dashboard1["pending_referrals"] == 1
    assert alice_dashboard1["completed_referrals"] == 0
    assert alice_dashboard1["total_referral_earnings"] == 0.0
    assert len(alice_dashboard1["referrals"]) == 1
    assert alice_dashboard1["referrals"][0]["status"] == "pending"
    assert alice_dashboard1["referrals"][0]["invitee_name"] == "Bob Builder"

    # Alice's wallet should still have 0 bonus because Bob hasn't completed 10 listings yet
    w_alice_mid = client.get(f"/api/wallet/{alice_id}").json()
    assert w_alice_mid["promotional_credit_balance"] == 0.0

    # 4. Bob lists 9 active items (threshold not yet met)
    for i in range(1, 10):
        client.post("/api/items", json={
            "owner_id": bob_id,
            "title": f"Bob Construction Tool #{i}",
            "category": "Construction",
            "description": f"Heavy duty construction gear #{i}",
            "condition": "Excellent",
            "base_rate_daily": 30.0,
            "security_deposit": 100.0,
            "item_value": 300.0,
            "location_city": "San Ramon, CA",
            "active_duration_days": 90
        })

    # Still pending
    alice_dashboard2 = client.get(f"/api/referrals/my-code/{alice_id}").json()
    assert alice_dashboard2["pending_referrals"] == 1
    assert alice_dashboard2["completed_referrals"] == 0

    # 5. Bob lists 10th active item -> UNLOCKS DUAL BONUS!
    client.post("/api/items", json={
        "owner_id": bob_id,
        "title": "Bob Qualifying 10th Tool",
        "category": "Construction",
        "description": "Milestone completing construction gear",
        "condition": "Like New",
        "base_rate_daily": 35.0,
        "security_deposit": 120.0,
        "item_value": 350.0,
        "location_city": "San Ramon, CA",
        "active_duration_days": 90
    })

    # Verify Invitee (Bob) received Sign-Up Bonus of $20.00!
    w_bob = client.get(f"/api/wallet/{bob_id}").json()
    assert w_bob["promotional_credit_balance"] == 20.0
    assert w_bob["total_balance"] == 20.0

    # Verify Referrer (Alice) automatically received Referral Bonus of $15.00!
    w_alice_final = client.get(f"/api/wallet/{alice_id}").json()
    assert w_alice_final["promotional_credit_balance"] == 15.0
    assert w_alice_final["total_balance"] == 15.0
    assert any(tx["transaction_type"] == "referral_bonus" for tx in w_alice_final["transactions"])

    # Verify Alice's referral status is updated to completed
    alice_dashboard3 = client.get(f"/api/referrals/my-code/{alice_id}").json()
    assert alice_dashboard3["pending_referrals"] == 0
    assert alice_dashboard3["completed_referrals"] == 1
    assert alice_dashboard3["total_referral_earnings"] == 15.0
    assert alice_dashboard3["referrals"][0]["status"] == "completed"

    # 6. Test Admin Dynamic Tuning: Change Referrer Bonus to $25.00 and Invitee Bonus to $30.00
    admin_upd = client.put("/api/admin/promotions/signup-bonus", json={
        "referrer_bonus_amount": 25.0,
        "invitee_bonus_amount": 30.0,
        "bonus_amount": 30.0,
        "required_active_items": 2
    })
    assert admin_upd.status_code == 200
    assert admin_upd.json()["referrer_bonus_amount"] == 25.0
    assert admin_upd.json()["invitee_bonus_amount"] == 30.0

    # Register new invitee ("Charlie") using Alice's code
    charlie_reg = client.post("/api/register", json={
        "first_name": "Charlie", "last_name": "Craft", "email": "charlie@refer.com",
        "phone": "+1-925-555-3333", "address": "300 Community Rd, San Ramon, CA",
        "username": "charliecraft", "password": "Password123",
        "referral_code": alice_code
    }).json()
    charlie_id = charlie_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": charlie_id, "channel": "email", "otp_code": charlie_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": charlie_id, "channel": "phone", "otp_code": charlie_reg["demo_otps"]["phone_code"]})

    # Charlie lists 2 items (meeting updated threshold)
    for k in range(1, 3):
        client.post("/api/items", json={
            "owner_id": charlie_id,
            "title": f"Charlie Item #{k}",
            "category": "Crafts",
            "description": f"Crafting machine #{k}",
            "condition": "New",
            "base_rate_daily": 20.0,
            "security_deposit": 50.0,
            "item_value": 150.0,
            "location_city": "San Ramon, CA",
            "active_duration_days": 90
        })

    # Charlie gets updated $30.00 invitee bonus
    w_charlie = client.get(f"/api/wallet/{charlie_id}").json()
    assert w_charlie["promotional_credit_balance"] == 30.0

    # Alice gets updated $25.00 referral bonus (previous 15.0 + 25.0 = 40.0)!
    w_alice_v2 = client.get(f"/api/wallet/{alice_id}").json()
    assert w_alice_v2["promotional_credit_balance"] == 40.0
