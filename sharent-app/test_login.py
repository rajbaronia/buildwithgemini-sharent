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

def test_login_workflow_with_2fa():
    # 1. Register and verify a user
    reg_payload = {
        "first_name": "Michael",
        "last_name": "Scott",
        "email": "mscott@dundermifflin.com",
        "phone": "+1-925-555-0199",
        "address": "1725 Slough Avenue, Scranton, PA",
        "username": "michaelscott",
        "password": "WorldBestBoss1!"
    }
    reg_res = client.post("/api/register", json=reg_payload)
    assert reg_res.status_code == 200
    user_id = reg_res.json()["user_id"]
    email_reg_otp = reg_res.json()["demo_otps"]["email_code"]
    phone_reg_otp = reg_res.json()["demo_otps"]["phone_code"]

    # Try login before verification -> Must fail
    unverified_res = client.post("/api/login/initiate", json={
        "username": "michaelscott",
        "password": "WorldBestBoss1!",
        "preferred_channel": "email"
    })
    assert unverified_res.status_code == 403
    assert "Registration incomplete" in unverified_res.json()["detail"]

    # Verify both channels to activate account
    client.post("/api/verify-otp", json={"user_id": user_id, "channel": "email", "otp_code": email_reg_otp})
    client.post("/api/verify-otp", json={"user_id": user_id, "channel": "phone", "otp_code": phone_reg_otp})

    # Test invalid password rejection
    bad_pwd_res = client.post("/api/login/initiate", json={
        "username": "michaelscott",
        "password": "WrongPassword!",
        "preferred_channel": "email"
    })
    assert bad_pwd_res.status_code == 401
    assert "Invalid username or password" in bad_pwd_res.json()["detail"]

    # 2. Test Login with Email OTP
    login_email_init = client.post("/api/login/initiate", json={
        "username": "michaelscott",
        "password": "WorldBestBoss1!",
        "preferred_channel": "email"
    })
    assert login_email_init.status_code == 200
    login_data = login_email_init.json()
    assert login_data["channel"] == "email"
    login_otp = login_data["demo_otp"]

    # Test invalid OTP submission
    bad_otp_res = client.post("/api/login/verify-otp", json={
        "user_id": user_id,
        "channel": "email",
        "otp_code": "999999"
    })
    assert bad_otp_res.status_code == 400
    assert "Invalid or expired login OTP" in bad_otp_res.json()["detail"]

    # Verify valid Email login OTP
    verify_res = client.post("/api/login/verify-otp", json={
        "user_id": user_id,
        "channel": "email",
        "otp_code": login_otp
    })
    assert verify_res.status_code == 200
    assert verify_res.json()["user"]["username"] == "michaelscott"

    # 3. Test Login with Phone (SMS) OTP
    login_phone_init = client.post("/api/login/initiate", json={
        "username": "michaelscott",
        "password": "WorldBestBoss1!",
        "preferred_channel": "phone"
    })
    assert login_phone_init.status_code == 200
    phone_data = login_phone_init.json()
    assert phone_data["channel"] == "phone"
    phone_login_otp = phone_data["demo_otp"]

    verify_phone_res = client.post("/api/login/verify-otp", json={
        "user_id": user_id,
        "channel": "phone",
        "otp_code": phone_login_otp
    })
    assert verify_phone_res.status_code == 200
    assert verify_phone_res.json()["user"]["first_name"] == "Michael"
