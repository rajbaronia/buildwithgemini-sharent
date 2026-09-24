import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, PaymentTransaction, RentalHandoverInspection, UserWallet, WalletTransaction

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_user_a_b_c_exact_promotional_credit_scenario():
    """
    Exact User Scenario:
    - We offer $20 sign up bonus to all new users
    - User A, B, and C sign up with this promotion offer, and receive $20 credit in their account
    - User A lists an electric drill on our rental marketplace for $10/day
    - User B lists a kayak on our rental marketplace for $15/day
    - User C rents the electric drill from user A for 1 day, and pays $10 from his credit balance
    - We charge 10% fee from the listing user, so user A receives net $9 ($10 - 10%) for renting out his electric drill
    - Now user A has $29 credit balance ($20 original bonus + $9 rent earnings), and user C has $10 credit balance ($20 original bonus - $10 rent payment)
    - User A rents kayak from User B for 2 days, and needs to pay $30 for the rental. He pays $29 from his credit balance, and remaining $1 from his PayPal account.
    - We charge 10% fee from the listing user, so user B receives net $27 ($30 - 10%) for renting out his kayak
    - Now user B has $47 credit balance ($20 original bonus credit + $27 rent earnings). However, user B can NOT deposit this $47 into his PayPal account, since all of it came from bonus ($20 from his own bonus, and $27 from others bonus)
    """

    # 1. Register User A, B, C and verify dual OTP
    users = {}
    for name, uname, email in [("User A", "user_a", "usera@test.com"),
                               ("User B", "user_b", "userb@test.com"),
                               ("User C", "user_c", "userc@test.com")]:
        reg = client.post("/api/register", json={
            "first_name": name, "last_name": "Test", "email": email,
            "phone": f"+1-555-000-{len(users)+1:04d}", "address": "123 Main St, Dublin, CA",
            "username": uname, "password": "Password123"
        }).json()
        uid = reg["user_id"]
        client.post("/api/verify-otp", json={"user_id": uid, "channel": "email", "otp_code": reg["demo_otps"]["email_code"]})
        client.post("/api/verify-otp", json={"user_id": uid, "channel": "phone", "otp_code": reg["demo_otps"]["phone_code"]})
        users[name] = uid

    # Verify each user received $20.00 signup promotional credit
    for name, uid in users.items():
        w = client.get(f"/api/wallet/{uid}").json()
        assert w["total_balance"] == 20.0
        assert w["promotional_credit_balance"] == 20.0
        assert w["withdrawable_cash_balance"] == 0.0

    # 2. User A lists an electric drill for $10/day
    drill_res = client.post("/api/items", json={
        "owner_id": users["User A"],
        "title": "Electric Drill",
        "category": "Power Tools",
        "condition": "Good",
        "description": "Standard 18V electric drill",
        "base_rate_daily": 10.0,
        "security_deposit": 0.0,
        "item_value": 80.0,
        "min_rental_days": 1,
        "max_rental_days": 7,
        "deposit_required": False,
        "insurance_required": False,
        "location_city": "Dublin, CA"
    })
    drill_id = drill_res.json()["id"]

    # 3. User B lists a kayak for $15/day
    kayak_res = client.post("/api/items", json={
        "owner_id": users["User B"],
        "title": "Inflatable Kayak",
        "category": "Outdoor Gear",
        "condition": "Excellent",
        "description": "2-person tandem kayak with paddles",
        "base_rate_daily": 15.0,
        "security_deposit": 0.0,
        "item_value": 300.0,
        "min_rental_days": 1,
        "max_rental_days": 7,
        "deposit_required": False,
        "insurance_required": False,
        "location_city": "Dublin, CA"
    })
    kayak_id = kayak_res.json()["id"]

    # 4. User C rents electric drill from User A for 1 day
    today_str = date.today().isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()

    agr_c = client.post("/api/rental-agreements", json={
        "item_id": drill_id,
        "renter_id": users["User C"],
        "start_date": today_str,
        "end_date": tomorrow_str,
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    }).json()

    # User C pays rent using credit balance
    pay_c = client.post("/api/checkout/pay", json={
        "agreement_id": agr_c["id"],
        "renter_id": users["User C"],
        "payment_method": "credit_card",
        "card_number": "4242424242424242",
        "exp_month": "12",
        "exp_year": "28",
        "cvv": "123",
        "billing_zip": "94568",
        "apply_credit": True
    })
    assert pay_c.status_code == 200

    # User C applied credit: covers $10 base rent (+ $1.50 service fee if applicable, or $10)
    # User A receives net $9 ($10 base rent - 10% listing commission)
    wallet_a = client.get(f"/api/wallet/{users['User A']}").json()
    assert wallet_a["total_balance"] == 29.0
    assert wallet_a["promotional_credit_balance"] == 29.0
    assert wallet_a["withdrawable_cash_balance"] == 0.0

    # 5. User A rents kayak from User B for 2 days ($15 * 2 = $30 base rent)
    day2_str = (date.today() + timedelta(days=2)).isoformat()
    agr_a = client.post("/api/rental-agreements", json={
        "item_id": kayak_id,
        "renter_id": users["User A"],
        "start_date": today_str,
        "end_date": day2_str,
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    }).json()

    # User A pays from credit balance ($29 available) + external payment
    pay_a = client.post("/api/checkout/pay", json={
        "agreement_id": agr_a["id"],
        "renter_id": users["User A"],
        "payment_method": "paypal",
        "apply_credit": True
    })
    assert pay_a.status_code == 200

    # User A credit balance is now $0 ($29 - $29 applied)
    wallet_a_after = client.get(f"/api/wallet/{users['User A']}").json()
    assert wallet_a_after["total_balance"] == 0.0
    assert wallet_a_after["promotional_credit_balance"] == 0.0

    # User B receives net $27 ($30 base rent - 10% commission = $27)
    # User B balance is now $47 ($20 bonus + $27 earnings)
    wallet_b = client.get(f"/api/wallet/{users['User B']}").json()
    assert wallet_b["total_balance"] == 47.0
    assert wallet_b["promotional_credit_balance"] == 47.0
    assert wallet_b["withdrawable_cash_balance"] == 0.0

    # 6. User B attempts to withdraw $47 to PayPal -> MUST BE REJECTED
    withdraw_attempt = client.post("/api/wallet/withdraw", json={
        "user_id": users["User B"],
        "amount": 47.0,
        "destination_type": "paypal",
        "destination_account": "userb_paypal@test.com"
    })
    assert withdraw_attempt.status_code == 400
    err_msg = withdraw_attempt.json()["detail"]
    assert "Your available withdrawable cash is $0.00" in err_msg
    assert "cannot be withdrawn to Paypal" in err_msg

    # Confirm User B's balance remains intact ($47)
    wallet_b_final = client.get(f"/api/wallet/{users['User B']}").json()
    assert wallet_b_final["total_balance"] == 47.0
    assert wallet_b_final["withdrawable_cash_balance"] == 0.0
