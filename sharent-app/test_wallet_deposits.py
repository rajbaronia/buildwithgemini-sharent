import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, PaymentTransaction, UserWallet, WalletTransaction

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_multi_channel_wallet_deposits_and_transaction_history():
    # Set required_active_items to 0 so new user receives initial bonus
    client.put("/api/admin/promotions/signup-bonus", json={"required_active_items": 0})

    # 1. Register and verify user
    reg = client.post("/api/register", json={
        "first_name": "David", "last_name": "Depositor", "email": "david@deposit.com",
        "phone": "+1-925-555-0999", "address": "456 Finance Way, Dublin, CA",
        "username": "daviddep", "password": "Password123"
    }).json()
    uid = reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": uid, "channel": "email", "otp_code": reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": uid, "channel": "phone", "otp_code": reg["demo_otps"]["phone_code"]})

    # Initial state: $20 promotional bonus, $0 withdrawable cash
    w0 = client.get(f"/api/wallet/{uid}").json()
    assert w0["total_balance"] == 20.0
    assert w0["promotional_credit_balance"] == 20.0
    assert w0["withdrawable_cash_balance"] == 0.0
    assert len(w0["transactions"]) == 1
    assert w0["transactions"][0]["transaction_type"] == "signup_bonus"

    # 2. Test Invalid Deposit Amount (<= 0)
    inv_dep = client.post("/api/wallet/deposit", json={
        "user_id": uid,
        "amount": 0.0,
        "channel": "bank_account"
    })
    assert inv_dep.status_code == 400
    assert "greater than $0.00" in inv_dep.json()["detail"]

    # 3. Test Invalid Channel
    inv_chan = client.post("/api/wallet/deposit", json={
        "user_id": uid,
        "amount": 50.0,
        "channel": "crypto_bitcoin"
    })
    assert inv_chan.status_code == 400
    assert "Unsupported deposit channel" in inv_chan.json()["detail"]

    # 4. Deposit $50.00 via Bank Account (ACH)
    dep_ach = client.post("/api/wallet/deposit", json={
        "user_id": uid,
        "amount": 50.0,
        "channel": "bank_account",
        "channel_details": "Chase Checking (••9876)"
    })
    assert dep_ach.status_code == 200
    ach_data = dep_ach.json()
    assert ach_data["success"] is True
    assert "ACH" in ach_data["deposit_reference"]
    assert ach_data["new_cash_balance"] == 50.0
    assert ach_data["new_total_balance"] == 70.0 # $20 promo + $50 cash

    # 5. Deposit $25.00 via Google Pay
    dep_gpay = client.post("/api/wallet/deposit", json={
        "user_id": uid,
        "amount": 25.0,
        "channel": "google_pay",
        "channel_details": "Google Pay (Visa ••1234)"
    })
    assert dep_gpay.status_code == 200
    gpay_data = dep_gpay.json()
    assert "GPAY" in gpay_data["deposit_reference"]
    assert gpay_data["new_cash_balance"] == 75.0
    assert gpay_data["new_total_balance"] == 95.0 # $20 promo + $75 cash

    # 6. Deposit $15.00 via PayPal
    dep_pp = client.post("/api/wallet/deposit", json={
        "user_id": uid,
        "amount": 15.0,
        "channel": "paypal",
        "channel_details": "david_paypal@deposit.com"
    })
    assert dep_pp.status_code == 200
    pp_data = dep_pp.json()
    assert "PP" in pp_data["deposit_reference"]
    assert pp_data["new_cash_balance"] == 90.0
    assert pp_data["new_total_balance"] == 110.0 # $20 promo + $90 cash

    # 7. Deposit $10.00 via Venmo
    dep_venmo = client.post("/api/wallet/deposit", json={
        "user_id": uid,
        "amount": 10.0,
        "channel": "venmo",
        "channel_details": "@David-Deposits"
    })
    assert dep_venmo.status_code == 200
    venmo_data = dep_venmo.json()
    assert "VENMO" in venmo_data["deposit_reference"]
    assert venmo_data["new_cash_balance"] == 100.0
    assert venmo_data["new_total_balance"] == 120.0 # $20 promo + $100 cash

    # 8. Verify Transaction History & Balance Breakdown
    w_final = client.get(f"/api/wallet/{uid}").json()
    assert w_final["total_balance"] == 120.0
    assert w_final["promotional_credit_balance"] == 20.0
    assert w_final["withdrawable_cash_balance"] == 100.0
    assert len(w_final["transactions"]) == 5 # 1 bonus + 4 deposits

    # Check channels on transactions
    tx_types = [t["transaction_type"] for t in w_final["transactions"]]
    assert tx_types == ["deposit", "deposit", "deposit", "deposit", "signup_bonus"]

    # 9. Verify Withdrawing Deposited Cash back out to Bank Account ($40.00)
    withdraw_res = client.post("/api/wallet/withdraw", json={
        "user_id": uid,
        "amount": 40.0,
        "destination_type": "bank_transfer",
        "destination_account": "Chase Checking (••9876)"
    })
    assert withdraw_res.status_code == 200
    assert withdraw_res.json()["remaining_withdrawable_cash"] == 60.0
    assert withdraw_res.json()["total_credit_balance"] == 80.0

    # 10. Attempting to withdraw remaining $60 cash + $20 promo = $80 -> REJECTED because $20 is promo
    withdraw_promo = client.post("/api/wallet/withdraw", json={
        "user_id": uid,
        "amount": 80.0,
        "destination_type": "paypal",
        "destination_account": "david_paypal@deposit.com"
    })
    assert withdraw_promo.status_code == 400
    assert "Your available withdrawable cash is $60.00" in withdraw_promo.json()["detail"]
