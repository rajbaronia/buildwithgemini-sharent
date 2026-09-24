import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, ChatMessage

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_real_time_chat_messaging_workflow():
    # 1. Register Owner ("Oscar") and Renter ("Rita")
    oscar_reg = client.post("/api/register", json={
        "first_name": "Oscar", "last_name": "Owner", "email": "oscar@chat.com",
        "phone": "+1-925-555-5001", "address": "500 Main St, Pleasanton, CA",
        "username": "oscarowner", "password": "Password123"
    }).json()
    oscar_id = oscar_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": oscar_id, "channel": "email", "otp_code": oscar_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": oscar_id, "channel": "phone", "otp_code": oscar_reg["demo_otps"]["phone_code"]})

    rita_reg = client.post("/api/register", json={
        "first_name": "Rita", "last_name": "Renter", "email": "rita@chat.com",
        "phone": "+1-925-555-5002", "address": "600 Ridge Rd, Pleasanton, CA",
        "username": "ritarenter", "password": "Password123"
    }).json()
    rita_id = rita_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": rita_id, "channel": "email", "otp_code": rita_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": rita_id, "channel": "phone", "otp_code": rita_reg["demo_otps"]["phone_code"]})

    # 2. Oscar lists a Drone
    item_res = client.post("/api/items", json={
        "owner_id": oscar_id,
        "title": "4K Aerial Drone with 3 Batteries",
        "category": "Electronics & Photography",
        "description": "Pro aerial drone for landscape photography",
        "condition": "Like New",
        "base_rate_daily": 45.0,
        "security_deposit": 150.0,
        "item_value": 800.0,
        "location_city": "Pleasanton, CA"
    })
    item_id = item_res.json()["id"]

    # 3. Create Rental Agreement
    start_d = date.today() + timedelta(days=2)
    end_d = start_d + timedelta(days=2)
    agr_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": rita_id,
        "start_date": str(start_d),
        "end_date": str(end_d),
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    agr_id = agr_res.json()["id"]

    # 4. Rita sends an initial inquiry about pickup coordination
    msg1_res = client.post("/api/chat/messages", json={
        "agreement_id": agr_id,
        "sender_id": rita_id,
        "message_text": "Hi Oscar! Can I pick up the drone at 9:00 AM on Saturday?",
        "attachment_url": None
    })
    assert msg1_res.status_code == 200
    m1 = msg1_res.json()
    assert m1["sender_name"] == "Rita Renter"
    assert m1["receiver_name"] == "Oscar Owner"
    assert m1["is_read"] is False
    assert "9:00 AM" in m1["message_text"]

    # 5. Oscar checks his chat threads - unread count should be 1
    oscar_threads = client.get(f"/api/chat/threads/{oscar_id}").json()
    assert len(oscar_threads) == 1
    assert oscar_threads[0]["unread_count"] == 1
    assert oscar_threads[0]["other_party_name"] == "Rita Renter"
    assert "9:00 AM" in oscar_threads[0]["last_message"]

    # 6. Oscar reads the messages (mark_as_read=True by default)
    oscar_chat = client.get(f"/api/chat/messages/{agr_id}?user_id={oscar_id}").json()
    assert len(oscar_chat) == 1
    assert oscar_chat[0]["is_read"] is True

    # Check that Oscar's unread count is now 0
    oscar_threads_after = client.get(f"/api/chat/threads/{oscar_id}").json()
    assert oscar_threads_after[0]["unread_count"] == 0

    # 7. Oscar replies to Rita with pickup instructions
    msg2_res = client.post("/api/chat/messages", json={
        "agreement_id": agr_id,
        "sender_id": oscar_id,
        "message_text": "9:00 AM works great! I'll have the batteries fully charged. See you then!",
        "attachment_url": "/static/uploads/pickup_location_map.png"
    })
    assert msg2_res.status_code == 200
    m2 = msg2_res.json()
    assert m2["sender_id"] == oscar_id
    assert m2["attachment_url"] == "/static/uploads/pickup_location_map.png"

    # 8. Rita checks thread: unread count should be 1
    rita_threads = client.get(f"/api/chat/threads/{rita_id}").json()
    assert rita_threads[0]["unread_count"] == 1

    # 9. Verify full conversation history between both parties
    full_history = client.get(f"/api/chat/messages/{agr_id}?user_id={rita_id}").json()
    assert len(full_history) == 2
    assert full_history[0]["sender_name"] == "Rita Renter"
    assert full_history[1]["sender_name"] == "Oscar Owner"
    assert full_history[1]["is_read"] is True  # marked read when fetched by Rita

    # 10. Security: Third party cannot access agreement chat
    eve_reg = client.post("/api/register", json={
        "first_name": "Eve", "last_name": "Eavesdropper", "email": "eve@chat.com",
        "phone": "+1-925-555-5003", "address": "700 Spy Way, Pleasanton, CA",
        "username": "evespy", "password": "Password123"
    }).json()
    eve_id = eve_reg["user_id"]

    unauth_send = client.post("/api/chat/messages", json={
        "agreement_id": agr_id,
        "sender_id": eve_id,
        "message_text": "I should not be able to talk here!"
    })
    assert unauth_send.status_code == 403

    unauth_get = client.get(f"/api/chat/messages/{agr_id}?user_id={eve_id}")
    assert unauth_get.status_code == 403
