import pytest
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, SessionLocal, User, OTPVerification

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_full_registration_and_otp_workflow():
    payload = {
        "first_name": "Jane",
        "last_name": "Smith",
        "email": "jane.smith@example.com",
        "phone": "+1-925-555-0144",
        "address": "4000 Executive Pkwy, San Ramon, CA 94583",
        "username": "janesmith",
        "password": "SecurePassword123!"
    }

    # 1. Register User
    res = client.post("/api/register", json=payload)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "user_id" in data
    user_id = data["user_id"]
    email_code = data["demo_otps"]["email_code"]
    phone_code = data["demo_otps"]["phone_code"]

    # 2. Login should be blocked prior to verification
    login_res = client.post("/api/login", json={"username": "janesmith", "password": "SecurePassword123!"})
    assert login_res.status_code == 403
    assert "Account is not fully verified" in login_res.json()["detail"]

    # 3. Invalid OTP should fail
    bad_res = client.post("/api/verify-otp", json={
        "user_id": user_id,
        "channel": "email",
        "otp_code": "000000"
    })
    assert bad_res.status_code == 400

    # 4. Verify Email OTP
    email_res = client.post("/api/verify-otp", json={
        "user_id": user_id,
        "channel": "email",
        "otp_code": email_code
    })
    assert email_res.status_code == 200
    assert email_res.json()["is_email_verified"] is True
    assert email_res.json()["is_fully_verified"] is False

    # 5. Verify Phone OTP
    phone_res = client.post("/api/verify-otp", json={
        "user_id": user_id,
        "channel": "phone",
        "otp_code": phone_code
    })
    assert phone_res.status_code == 200
    assert phone_res.json()["is_phone_verified"] is True
    assert phone_res.json()["is_fully_verified"] is True

    # 6. Now login succeeds
    final_login = client.post("/api/login", json={"username": "janesmith", "password": "SecurePassword123!"})
    assert final_login.status_code == 200
    assert final_login.json()["user"]["username"] == "janesmith"

def test_duplicate_registration_prevented():
    payload = {
        "first_name": "Bob",
        "last_name": "Builder",
        "email": "bob@example.com",
        "phone": "+1-555-0100",
        "address": "123 Tool Lane, San Ramon, CA",
        "username": "bobthebuilder",
        "password": "Password123"
    }
    res1 = client.post("/api/register", json=payload)
    assert res1.status_code == 200

    # Try registering again with duplicate username
    res2 = client.post("/api/register", json=payload)
    assert res2.status_code == 400
    assert "Username is already taken" in res2.json()["detail"]
