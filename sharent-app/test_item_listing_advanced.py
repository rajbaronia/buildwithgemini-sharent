import pytest
import io
from fastapi.testclient import TestClient
from main import app
from models import Base, engine, SessionLocal, User, Item

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield

def test_item_listing_with_photos_durations_and_links():
    # 1. Register and verify an Owner user
    reg = client.post("/api/register", json={
        "first_name": "Marcus",
        "last_name": "Vance",
        "email": "marcus@sharent.com",
        "phone": "+1-925-555-0333",
        "address": "5000 Executive Pkwy, San Ramon, CA",
        "username": "marcusv",
        "password": "Password123"
    }).json()
    user_id = reg["user_id"]
    client.post("/api/verify-otp", json={"user_id": user_id, "channel": "email", "otp_code": reg["demo_otps"]["email_code"]})
    client.post("/api/verify-otp", json={"user_id": user_id, "channel": "phone", "otp_code": reg["demo_otps"]["phone_code"]})

    # 2. Test Multi-Image Upload API
    fake_img1 = ("drill_front.jpg", io.BytesIO(b"fake image bytes 1"), "image/jpeg")
    fake_img2 = ("drill_case.png", io.BytesIO(b"fake image bytes 2"), "image/png")
    upload_res = client.post("/api/upload-images", files=[("files", fake_img1), ("files", fake_img2)])
    assert upload_res.status_code == 200
    upload_data = upload_res.json()
    assert upload_data["success"] is True
    assert len(upload_data["image_urls"]) == 2
    img_urls = upload_data["image_urls"]

    # 3. Test Invalid Duration Validation (min > max) -> Expect 422
    bad_duration_payload = {
        "owner_id": user_id,
        "title": "Invalid Duration Drill",
        "category": "Power Tools",
        "description": "Drill with invalid duration settings",
        "condition": "Good",
        "base_rate_daily": 20.0,
        "security_deposit": 100.0,
        "item_value": 200.0,
        "min_rental_days": 10,
        "max_rental_days": 3,  # Invalid: min > max
        "images": img_urls
    }
    bad_res = client.post("/api/items", json=bad_duration_payload)
    assert bad_res.status_code == 422

    # 4. Test Valid Item Listing with Duration Constraints and External Links
    valid_payload = {
        "owner_id": user_id,
        "title": "DeWalt 20V Cordless Hammer Drill Kit (DCD996)",
        "category": "Power Tools",
        "description": "Heavy-duty 3-speed all-metal transmission hammer drill with two 5.0Ah batteries.",
        "condition": "Like New",
        "base_rate_daily": 18.0,
        "base_rate_hourly": 5.0,
        "security_deposit": 150.0,
        "item_value": 279.0,
        "min_rental_days": 2,
        "max_rental_days": 14,
        "deposit_required": True,
        "insurance_required": True,
        "images": img_urls,
        "manual_url": "https://www.dewalt.com/manuals/DCD996-instructions.pdf",
        "brochure_url": "https://www.dewalt.com/products/dcd996",
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "location_city": "San Ramon, CA"
    }
    create_res = client.post("/api/items", json=valid_payload)
    assert create_res.status_code == 200
    item = create_res.json()
    assert item["title"] == "DeWalt 20V Cordless Hammer Drill Kit (DCD996)"
    assert item["min_rental_days"] == 2
    assert item["max_rental_days"] == 14
    assert item["insurance_required"] is True
    assert len(item["images"]) == 2
    assert item["manual_url"] == "https://www.dewalt.com/manuals/DCD996-instructions.pdf"
    assert item["video_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    item_id = item["id"]

    # 5. Test Item Detail Retrieval API
    detail_res = client.get(f"/api/items/{item_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["id"] == item_id
    assert detail["owner_name"] == "Marcus Vance"
    assert len(detail["images"]) == 2
    assert detail["manual_url"] is not None
