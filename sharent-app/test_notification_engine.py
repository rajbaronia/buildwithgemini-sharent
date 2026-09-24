import pytest
from datetime import date, timedelta
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, User, Item, RentalAgreement, NotificationEvent

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_push_sms_email_notification_engine_workflow():
    # 1. Register Owner ("Ned") and Renter ("Nancy")
    ned_reg = client.post("/api/register", json={
        "first_name": "Ned", "last_name": "Notifier", "email": "ned@notify.com",
        "phone": "+1-925-555-6001", "address": "123 Alert St, San Ramon, CA",
        "username": "nednotify", "password": "Password123"
    }).json()
    ned_id = ned_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": ned_id, "channel": "email", "otp_code": ned_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": ned_id, "channel": "phone", "otp_code": ned_reg["demo_otps"]["phone_code"]})

    nancy_reg = client.post("/api/register", json={
        "first_name": "Nancy", "last_name": "NotifyRenter", "email": "nancy@notify.com",
        "phone": "+1-925-555-6002", "address": "456 Signal Rd, San Ramon, CA",
        "username": "nancynotify", "password": "Password123"
    }).json()
    nancy_id = nancy_reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": nancy_id, "channel": "email", "otp_code": nancy_reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": nancy_id, "channel": "phone", "otp_code": nancy_reg["demo_otps"]["phone_code"]})

    # 2. Ned lists a Mountain Bike
    item_res = client.post("/api/items", json={
        "owner_id": ned_id,
        "title": "Trek Dual Sport Mountain Bike",
        "category": "Outdoor & Sports",
        "description": "Trail and street ready mountain bike",
        "condition": "Excellent",
        "base_rate_daily": 30.0,
        "security_deposit": 100.0,
        "item_value": 750.0,
        "location_city": "San Ramon, CA"
    })
    item_id = item_res.json()["id"]

    # 3. Nancy requests rental agreement -> Automatically fires milestone notification to Ned
    start_d = date.today() + timedelta(days=1)
    end_d = start_d + timedelta(days=3)
    agr_res = client.post("/api/rental-agreements", json={
        "item_id": item_id,
        "renter_id": nancy_id,
        "start_date": str(start_d),
        "end_date": str(end_d),
        "accepted_terms": True,
        "accepted_deposit_policy": True,
        "accepted_safety_rules": True
    })
    assert agr_res.status_code == 200

    # 4. Check Ned's notification feed: should have push and email alerts for booking request
    ned_notifs = client.get(f"/api/notifications/{ned_id}").json()
    assert ned_notifs["total_notifications"] >= 2
    assert ned_notifs["unread_count"] >= 2
    channels_received = [n["channel"] for n in ned_notifs["notifications"]]
    assert "push" in channels_received
    assert "email" in channels_received
    first_notif = ned_notifs["notifications"][0]
    assert first_notif["event_type"] == "booking_request"
    assert "Nancy" in first_notif["message"]

    # 5. Test manual dispatch across all 3 channels (SMS, Push, Email) for return reminder and payment receipts
    sms_test = client.post("/api/notifications/dispatch-test", json={
        "user_id": nancy_id,
        "channel": "sms",
        "event_type": "return_reminder",
        "title": "Rental Return Reminder",
        "message": "Your rental of Trek Dual Sport Mountain Bike is due back tomorrow by 5:00 PM.",
        "metadata_json": {"due_time": "17:00"}
    })
    assert sms_test.status_code == 200
    sms_data = sms_test.json()
    assert sms_data["channel"] == "sms"
    assert sms_data["destination"] == "+1-925-555-6002"
    assert sms_data["status"] == "delivered"

    # 6. Check Nancy's notifications
    nancy_notifs = client.get(f"/api/notifications/{nancy_id}").json()
    assert nancy_notifs["unread_count"] == 1
    target_notif_id = nancy_notifs["notifications"][0]["id"]

    # 7. Mark specific notification as read
    read_res = client.put(f"/api/notifications/{target_notif_id}/read")
    assert read_res.status_code == 200

    nancy_notifs_after = client.get(f"/api/notifications/{nancy_id}").json()
    assert nancy_notifs_after["unread_count"] == 0

    # 8. Mark all user notifications as read for Ned
    read_all_res = client.put(f"/api/notifications/read-all/{ned_id}")
    assert read_all_res.status_code == 200
    ned_after = client.get(f"/api/notifications/{ned_id}").json()
    assert ned_after["unread_count"] == 0
