import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, UserWallet, WalletTransaction, PromotionalProgramConfig, UserBonusTracker

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_conditional_signup_bonus_lifecycle_and_admin_config():
    # 1. Verify default dynamic platform promotional configuration
    cfg_res = client.get("/api/admin/promotions/signup-bonus")
    assert cfg_res.status_code == 200
    cfg = cfg_res.json()
    assert cfg["bonus_amount"] == 20.0
    assert cfg["required_active_items"] == 10
    assert cfg["required_active_days"] == 90
    assert cfg["is_active"] is True

    # 2. Register new User (Owner)
    reg = client.post("/api/register", json={
        "first_name": "Samantha", "last_name": "Supplier", "email": "samantha@bonus.com",
        "phone": "+1-925-555-0991", "address": "789 Inventory Blvd, San Ramon, CA",
        "username": "samanthasup", "password": "Password123"
    }).json()
    uid = reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": uid, "channel": "email", "otp_code": reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": uid, "channel": "phone", "otp_code": reg["demo_otps"]["phone_code"]})

    # 3. Check Initial Wallet: Bonus must NOT be credited yet ($0 promotional balance)
    w0 = client.get(f"/api/wallet/{uid}").json()
    assert w0["total_balance"] == 0.0
    assert w0["promotional_credit_balance"] == 0.0
    assert w0["withdrawable_cash_balance"] == 0.0

    # Check Bonus Progress Tracker: 0 / 10 items listed
    prog0 = client.get(f"/api/promotions/bonus-progress/{uid}").json()
    assert prog0["bonus_awarded"] is False
    assert prog0["qualifying_items_count"] == 0
    assert prog0["items_remaining"] == 10
    assert prog0["progress_percentage"] == 0.0

    # 4. List 9 active items with 90-day active commitment
    for i in range(1, 10):
        item_res = client.post("/api/items", json={
            "owner_id": uid,
            "title": f"Tool Item #{i}",
            "category": "Tools",
            "description": f"Durable heavy duty workshop tool #{i}",
            "condition": "Good",
            "base_rate_daily": 15.0,
            "security_deposit": 50.0,
            "item_value": 150.0,
            "location_city": "San Ramon, CA",
            "active_duration_days": 90
        })
        assert item_res.status_code == 200

    # Wallet should STILL be $0.00 since 10 are required
    w9 = client.get(f"/api/wallet/{uid}").json()
    assert w9["promotional_credit_balance"] == 0.0
    prog9 = client.get(f"/api/promotions/bonus-progress/{uid}").json()
    assert prog9["bonus_awarded"] is False
    assert prog9["qualifying_items_count"] == 9
    assert prog9["items_remaining"] == 1
    assert prog9["progress_percentage"] == 90.0

    # 5. List 10th item, but with only 30 days active duration (LESS than 90 days requirement)
    item10_short = client.post("/api/items", json={
        "owner_id": uid,
        "title": "Short Duration Item #10",
        "category": "Tools",
        "description": "Short duration tool only committed for 30 days",
        "condition": "Good",
        "base_rate_daily": 15.0,
        "security_deposit": 50.0,
        "item_value": 150.0,
        "location_city": "San Ramon, CA",
        "active_duration_days": 30  # Doesn't meet 90 days!
    })
    assert item10_short.status_code == 200

    # Wallet should STILL be $0.00 because item does not satisfy 90-day requirement
    w_short = client.get(f"/api/wallet/{uid}").json()
    assert w_short["promotional_credit_balance"] == 0.0
    prog_short = client.get(f"/api/promotions/bonus-progress/{uid}").json()
    assert prog_short["bonus_awarded"] is False
    assert prog_short["qualifying_items_count"] == 9

    # 6. List a valid 10th item with 90 days active duration -> QUALIFIES & UNLOCKS BONUS!
    item10_valid = client.post("/api/items", json={
        "owner_id": uid,
        "title": "Qualifying 10th Tool Item",
        "category": "Power Tools",
        "description": "Professional tool committed for 90 days",
        "condition": "Like New",
        "base_rate_daily": 20.0,
        "security_deposit": 60.0,
        "item_value": 200.0,
        "location_city": "San Ramon, CA",
        "active_duration_days": 90
    })
    assert item10_valid.status_code == 200

    # Verify Bonus is now UNLOCKED & CREDITED to user's wallet!
    w10 = client.get(f"/api/wallet/{uid}").json()
    assert w10["promotional_credit_balance"] == 20.0
    assert w10["total_balance"] == 20.0
    assert len(w10["transactions"]) == 1
    assert w10["transactions"][0]["transaction_type"] == "signup_bonus"
    assert "Unlocked Welcome Sign-Up Bonus" in w10["transactions"][0]["description"]

    # Verify Bonus Progress status reports awarded
    prog10 = client.get(f"/api/promotions/bonus-progress/{uid}").json()
    assert prog10["bonus_awarded"] is True
    assert prog10["items_remaining"] == 0
    assert prog10["progress_percentage"] == 100.0
    assert "Congratulations" in prog10["status_message"]

    # 7. Test Admin Dynamic Variable Updates: Change requirements to 3 items and $35.00 bonus
    upd_res = client.put("/api/admin/promotions/signup-bonus", json={
        "bonus_amount": 35.0,
        "required_active_items": 3,
        "required_active_days": 60
    })
    assert upd_res.status_code == 200
    upd_cfg = upd_res.json()
    assert upd_cfg["bonus_amount"] == 35.0
    assert upd_cfg["required_active_items"] == 3
    assert upd_cfg["required_active_days"] == 60

    # 8. Register another User and verify they qualify under the new updated variables (3 items -> $35.00)
    reg2 = client.post("/api/register", json={
        "first_name": "Edward", "last_name": "Equip", "email": "edward@bonus.com",
        "phone": "+1-925-555-0992", "address": "123 Inventory Rd, San Ramon, CA",
        "username": "edwardequip", "password": "Password123"
    }).json()
    uid2 = reg2["user_id"]
    client.post("/api/verify-otp", json={"user_id": uid2, "channel": "email", "otp_code": reg2["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": uid2, "channel": "phone", "otp_code": reg2["demo_otps"]["phone_code"]})

    # List 3 qualifying items
    for j in range(1, 4):
        client.post("/api/items", json={
            "owner_id": uid2,
            "title": f"Edward Gear #{j}",
            "category": "Camping",
            "description": f"Camp gear item #{j}",
            "condition": "Excellent",
            "base_rate_daily": 20.0,
            "security_deposit": 50.0,
            "item_value": 100.0,
            "location_city": "San Ramon, CA",
            "active_duration_days": 60
        })

    # Verify User 2 received the updated $35.00 bonus!
    w_u2 = client.get(f"/api/wallet/{uid2}").json()
    assert w_u2["promotional_credit_balance"] == 35.0
    assert w_u2["total_balance"] == 35.0
