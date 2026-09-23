from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List
import os
import uuid
import json

from models import init_db, get_db, User, Item, OTPVerification, ItemAvailability, RentalAgreement
from auth import (
    hash_password,
    verify_password,
    create_and_send_otp,
    verify_otp_code,
    mask_contact,
)
from schemas import (
    UserRegisterRequest,
    OTPVerifyRequest,
    ResendOTPRequest,
    UserLoginRequest,
    LoginInitiateRequest,
    LoginVerifyOTPRequest,
    RoleSwitchRequest,
    ItemCreateRequest,
    ItemResponse,
    UserProfileResponse,
    ItemAvailabilityItem,
    ItemStatusToggleRequest,
    DateBlockToggleRequest,
    CalendarRangeCheckRequest,
    CalendarRangeCheckResponse,
    RentalQuoteResponse,
    RentalAgreementCreateRequest,
    RentalAgreementResponse,
)

app = FastAPI(title="SHARENT Marketplace")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Session role storage: {user_id: "owner" | "renter"}
USER_ACTIVE_ROLES = {}

@app.on_event("startup")
def on_startup():
    init_db()

# ----------------- HTML Template Routes -----------------

@app.get("/", response_class=HTMLResponse)
def index_page(request: Request):
    return templates.TemplateResponse(request=request, name="register.html", context={})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html", context={})

@app.get("/dashboard/{user_id}", response_class=HTMLResponse)
def dashboard_page(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"user": user})

# ----------------- Image Upload API (Module 4) -----------------

@app.post("/api/upload-images")
async def upload_images(files: List[UploadFile] = File(...)):
    uploaded_urls = []
    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in allowed_extensions:
            ext = ".jpg"  # fallback safe extension
        unique_filename = f"{uuid.uuid4().hex}{ext}"
        destination_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        contents = await file.read()
        with open(destination_path, "wb") as f:
            f.write(contents)
            
        uploaded_urls.append(f"/static/uploads/{unique_filename}")
        
    return {"success": True, "image_urls": uploaded_urls}

# ----------------- Authentication Endpoints -----------------

@app.post("/api/register")
def register_user(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username.strip()).first():
        raise HTTPException(status_code=400, detail="Username is already taken.")
    if db.query(User).filter(User.email == payload.email.strip()).first():
        raise HTTPException(status_code=400, detail="Email is already registered.")
    if db.query(User).filter(User.phone == payload.phone.strip()).first():
        raise HTTPException(status_code=400, detail="Phone number is already registered.")

    new_user = User(
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        email=payload.email.strip(),
        phone=payload.phone.strip(),
        address=payload.address.strip(),
        username=payload.username.strip(),
        hashed_password=hash_password(payload.password),
        is_email_verified=False,
        is_phone_verified=False,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    email_otp = create_and_send_otp(db, new_user, "email")
    phone_otp = create_and_send_otp(db, new_user, "phone")

    return {
        "message": "User registered successfully. Please verify your email and phone number.",
        "user_id": new_user.id,
        "username": new_user.username,
        "email": new_user.email,
        "phone": new_user.phone,
        "demo_otps": {
            "email_code": email_otp["code"],
            "phone_code": phone_otp["code"],
        },
    }

@app.post("/api/verify-otp")
def verify_otp(payload: OTPVerifyRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    is_valid = verify_otp_code(db, user.id, payload.channel, payload.otp_code)
    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Invalid or expired OTP for {payload.channel}.")

    if payload.channel == "email":
        user.is_email_verified = True
    elif payload.channel == "phone":
        user.is_phone_verified = True

    db.commit()
    db.refresh(user)

    return {
        "success": True,
        "message": f"{payload.channel.capitalize()} successfully verified.",
        "is_email_verified": user.is_email_verified,
        "is_phone_verified": user.is_phone_verified,
        "is_fully_verified": user.is_fully_verified,
    }

@app.post("/api/resend-otp")
def resend_otp(payload: ResendOTPRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    dest = user.email if payload.channel == "email" else user.phone
    otp_record = create_and_send_otp(db, user, payload.channel)

    return {
        "success": True,
        "message": f"Fresh security OTP dispatched to {mask_contact(dest, payload.channel)}.",
        "channel": payload.channel,
        "demo_otp": otp_record["code"],
    }

@app.post("/api/login/initiate")
def login_initiate(payload: LoginInitiateRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if not user.is_fully_verified:
        raise HTTPException(
            status_code=403,
            detail="Registration incomplete. Both email and phone number must be verified.",
        )

    channel = payload.preferred_channel
    dest = user.email if channel == "email" else user.phone
    otp_record = create_and_send_otp(db, user, channel)

    return {
        "message": f"Login OTP sent to your registered {channel}.",
        "user_id": user.id,
        "channel": channel,
        "masked_destination": mask_contact(dest, channel),
        "demo_otp": otp_record["code"],
    }

@app.post("/api/login/verify-otp")
def login_verify_otp(payload: LoginVerifyOTPRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    is_valid = verify_otp_code(db, user.id, payload.channel, payload.otp_code)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid or expired login OTP.")

    return {
        "message": "Authentication successful! Welcome to SHARENT.",
        "user": UserProfileResponse.model_validate(user),
    }

@app.post("/api/login")
def login_user(payload: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username.strip()).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if not user.is_fully_verified:
        raise HTTPException(
            status_code=403,
            detail="Account is not fully verified. Both email and phone must be verified.",
        )

    return {
        "message": "Login successful.",
        "user": UserProfileResponse.model_validate(user),
    }

# ----------------- Role Management & Items (Modules 3 & 4) -----------------

@app.get("/api/session/current-role/{user_id}")
def get_user_role(user_id: int):
    return {"user_id": user_id, "current_role": USER_ACTIVE_ROLES.get(user_id, "owner")}

@app.post("/api/session/switch-role")
def switch_user_role(payload: RoleSwitchRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    USER_ACTIVE_ROLES[payload.user_id] = payload.role
    return {"success": True, "user_id": payload.user_id, "active_role": payload.role}

@app.post("/api/items", response_model=ItemResponse)
def create_item(payload: ItemCreateRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.owner_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Owner not found.")
    if not user.is_fully_verified:
        raise HTTPException(status_code=403, detail="Owner must be fully verified to list items.")

    item = Item(
        owner_id=payload.owner_id,
        title=payload.title.strip(),
        category=payload.category,
        description=payload.description.strip(),
        condition=payload.condition,
        base_rate_daily=payload.base_rate_daily,
        base_rate_hourly=payload.base_rate_hourly,
        security_deposit=payload.security_deposit,
        item_value=payload.item_value,
        min_rental_days=payload.min_rental_days,
        max_rental_days=payload.max_rental_days,
        deposit_required=payload.deposit_required,
        insurance_required=payload.insurance_required,
        images_json=json.dumps(payload.images),
        manual_url=payload.manual_url.strip() if payload.manual_url else None,
        brochure_url=payload.brochure_url.strip() if payload.brochure_url else None,
        video_url=payload.video_url.strip() if payload.video_url else None,
        location_city=payload.location_city.strip(),
        is_available=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    resp = ItemResponse.model_validate(item)
    resp.owner_name = f"{user.first_name} {user.last_name}"
    resp.images = item.images
    return resp

@app.get("/api/items/{item_id}", response_model=ItemResponse)
def get_item_detail(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    user = db.query(User).filter(User.id == item.owner_id).first()
    resp = ItemResponse.model_validate(item)
    resp.owner_name = f"{user.first_name} {user.last_name}" if user else "Community Member"
    resp.images = item.images
    return resp

@app.get("/api/items/my-listings/{owner_id}")
def get_my_listings(owner_id: int, db: Session = Depends(get_db)):
    items = db.query(Item).filter(Item.owner_id == owner_id).order_by(Item.id.desc()).all()
    user = db.query(User).filter(User.id == owner_id).first()
    owner_name = f"{user.first_name} {user.last_name}" if user else ""
    results = []
    for item in items:
        r = ItemResponse.model_validate(item)
        r.owner_name = owner_name
        r.images = item.images
        results.append(r)
    return results

@app.get("/api/items/marketplace/{renter_id}")
def get_marketplace_items(renter_id: int, db: Session = Depends(get_db)):
    items = db.query(Item).filter(
        Item.owner_id != renter_id,
        Item.is_available == True
    ).order_by(Item.id.desc()).all()

    results = []
    for item in items:
        r = ItemResponse.model_validate(item)
        owner = db.query(User).filter(User.id == item.owner_id).first()
        r.owner_name = f"{owner.first_name} {owner.last_name}" if owner else "Community Member"
        r.images = item.images
        results.append(r)
    return results


# ----------------- Airbnb-style Calendar Endpoints -----------------

@app.get("/api/items/{item_id}/availability")
def get_item_availability(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    records = db.query(ItemAvailability).filter(ItemAvailability.item_id == item_id).all()
    # Return formatted list of blocked/booked dates
    return [
        {
            "date": r.date.isoformat(),
            "status": r.status,
            "reason": r.reason
        }
        for r in records
    ]

@app.post("/api/items/{item_id}/availability/toggle")
def toggle_date_availability(item_id: int, payload: DateBlockToggleRequest, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item.owner_id != payload.owner_id:
        raise HTTPException(status_code=403, detail="Only the owner can modify calendar availability.")

    existing = db.query(ItemAvailability).filter(
        ItemAvailability.item_id == item_id,
        ItemAvailability.date == payload.date
    ).first()

    if payload.status == "available":
        # Unblock date
        if existing:
            db.delete(existing)
            db.commit()
            return {"success": True, "date": payload.date.isoformat(), "status": "available"}
        return {"success": True, "date": payload.date.isoformat(), "status": "available"}
    else:
        # Block date
        if existing:
            existing.status = "blocked"
            existing.reason = payload.reason
        else:
            new_record = ItemAvailability(
                item_id=item_id,
                date=payload.date,
                status="blocked",
                reason=payload.reason
            )
            db.add(new_record)
        db.commit()
        return {"success": True, "date": payload.date.isoformat(), "status": "blocked", "reason": payload.reason}

@app.post("/api/items/{item_id}/availability/check-range", response_model=CalendarRangeCheckResponse)
def check_calendar_range(item_id: int, payload: CalendarRangeCheckRequest, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    if payload.end_date <= payload.start_date:
        return CalendarRangeCheckResponse(
            is_available=False,
            total_days=0,
            reason="End date must be after start date.",
            daily_rate=item.base_rate_daily,
            total_rent=0.0,
            min_days=item.min_rental_days,
            max_days=item.max_rental_days
        )

    # Calculate days
    total_days = (payload.end_date - payload.start_date).days

    if total_days < item.min_rental_days:
        return CalendarRangeCheckResponse(
            is_available=False,
            total_days=total_days,
            reason=f"Duration ({total_days} days) is less than minimum required ({item.min_rental_days} days).",
            daily_rate=item.base_rate_daily,
            total_rent=total_days * item.base_rate_daily,
            min_days=item.min_rental_days,
            max_days=item.max_rental_days
        )

    if total_days > item.max_rental_days:
        return CalendarRangeCheckResponse(
            is_available=False,
            total_days=total_days,
            reason=f"Duration ({total_days} days) exceeds maximum allowed ({item.max_rental_days} days).",
            daily_rate=item.base_rate_daily,
            total_rent=total_days * item.base_rate_daily,
            min_days=item.min_rental_days,
            max_days=item.max_rental_days
        )

    # Check for overlapping blocked or booked dates
    conflict = db.query(ItemAvailability).filter(
        ItemAvailability.item_id == item_id,
        ItemAvailability.date >= payload.start_date,
        ItemAvailability.date < payload.end_date
    ).first()

    if conflict:
        return CalendarRangeCheckResponse(
            is_available=False,
            total_days=total_days,
            reason=f"Selected dates overlap with an unavailable day ({conflict.date.isoformat()}: {conflict.reason or 'Blocked'}).",
            daily_rate=item.base_rate_daily,
            total_rent=total_days * item.base_rate_daily,
            min_days=item.min_rental_days,
            max_days=item.max_rental_days
        )

    return CalendarRangeCheckResponse(
        is_available=True,
        total_days=total_days,
        reason="Dates are completely available!",
        daily_rate=item.base_rate_daily,
        total_rent=total_days * item.base_rate_daily,
        min_days=item.min_rental_days,
        max_days=item.max_rental_days
    )


@app.post("/api/verify-otp-direct/{user_id}")
def verify_user_direct(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_email_verified = True
    user.is_phone_verified = True
    db.commit()
    db.refresh(user)
    return {"success": True, "message": "User is now fully verified.", "is_fully_verified": True}


@app.post("/api/items/{item_id}/toggle-status")
def toggle_item_status(item_id: int, payload: ItemStatusToggleRequest, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    if item.owner_id != payload.owner_id:
        raise HTTPException(status_code=403, detail="Only the item owner can change listing status.")

    item.is_available = payload.is_available
    db.commit()
    db.refresh(item)
    return {
        "success": True,
        "item_id": item.id,
        "is_available": item.is_available,
        "status": "Active & Visible on Marketplace" if item.is_available else "Deactivated & Hidden from Renters"
    }


@app.post("/api/items/{item_id}/quote", response_model=RentalQuoteResponse)
def get_rental_quote(item_id: int, payload: CalendarRangeCheckRequest, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")

    if payload.end_date <= payload.start_date:
        raise HTTPException(status_code=400, detail="End date must be after start date.")

    total_days = (payload.end_date - payload.start_date).days
    if total_days < item.min_rental_days:
        raise HTTPException(status_code=400, detail=f"Minimum rental duration is {item.min_rental_days} days.")
    if total_days > item.max_rental_days:
        raise HTTPException(status_code=400, detail=f"Maximum rental duration is {item.max_rental_days} days.")

    # Base rent calculation
    base_rent = round(total_days * item.base_rate_daily, 2)

    # Renter Service Fee: 5% of base rent + .00 fixed transaction fee
    service_fee_fixed = 1.00
    service_fee_pct = round(base_rent * 0.05, 2)
    service_fee_total = round(service_fee_fixed + service_fee_pct, 2)

    # Equipment Insurance Protection: 8% of base rent if required (min .00)
    insurance_fee = round(max(3.00, base_rent * 0.08), 2) if item.insurance_required else 0.0

    # Refundable Security Deposit
    security_deposit = round(item.security_deposit, 2)

    # Total Amount Due Now
    total_due_now = round(base_rent + service_fee_total + insurance_fee + security_deposit, 2)

    return RentalQuoteResponse(
        item_id=item.id,
        item_title=item.title,
        owner_name=f"{item.owner.first_name} {item.owner.last_name}" if item.owner else "Verified Owner",
        start_date=payload.start_date,
        end_date=payload.end_date,
        total_days=total_days,
        daily_rate=item.base_rate_daily,
        base_rent=base_rent,
        security_deposit=security_deposit,
        insurance_fee=insurance_fee,
        insurance_required=item.insurance_required,
        service_fee_fixed=service_fee_fixed,
        service_fee_pct=service_fee_pct,
        service_fee_total=service_fee_total,
        total_due_now=total_due_now,
        refundable_deposit_portion=security_deposit
    )


@app.post("/api/rental-agreements", response_model=RentalAgreementResponse)
def create_rental_agreement(payload: RentalAgreementCreateRequest, db: Session = Depends(get_db)):
    # 1. Enforce mandatory acknowledgments
    if not (payload.accepted_terms and payload.accepted_deposit_policy and payload.accepted_safety_rules):
        raise HTTPException(
            status_code=400,
            detail="You must acknowledge and accept all rental agreement terms, deposit conditions, and safety rules to proceed."
        )

    # 2. Verify Item exists & is available
    item = db.query(Item).filter(Item.id == payload.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found.")
    if not item.is_available:
        raise HTTPException(status_code=400, detail="This listing is currently deactivated.")
    if item.owner_id == payload.renter_id:
        raise HTTPException(status_code=400, detail="Owners cannot rent their own items.")

    # 3. Verify Renter exists
    renter = db.query(User).filter(User.id == payload.renter_id).first()
    if not renter:
        raise HTTPException(status_code=404, detail="Renter account not found.")

    # 4. Verify Date Logic & Duration limits
    if payload.end_date <= payload.start_date:
        raise HTTPException(status_code=400, detail="Return date must be after start date.")

    total_days = (payload.end_date - payload.start_date).days
    if total_days < item.min_rental_days:
        raise HTTPException(status_code=400, detail=f"Minimum rental duration is {item.min_rental_days} days.")
    if total_days > item.max_rental_days:
        raise HTTPException(status_code=400, detail=f"Maximum rental duration is {item.max_rental_days} days.")

    # 5. Check date calendar conflicts
    blocked = db.query(ItemAvailability).filter(
        ItemAvailability.item_id == item.id,
        ItemAvailability.date >= payload.start_date,
        ItemAvailability.date < payload.end_date,
        ItemAvailability.status.in_(["blocked", "booked"])
    ).first()
    if blocked:
        raise HTTPException(status_code=400, detail=f"Selected date {blocked.date} is unavailable ({blocked.reason or blocked.status}).")

    # 6. Calculate fee itemization
    base_rent = round(total_days * item.base_rate_daily, 2)
    service_fee = round(1.00 + (base_rent * 0.05), 2)
    insurance_fee = round(max(3.00, base_rent * 0.08), 2) if item.insurance_required else 0.0
    security_deposit = round(item.security_deposit, 2)
    total_amount = round(base_rent + service_fee + insurance_fee + security_deposit, 2)

    # 7. Create & Persist Agreement
    agreement = RentalAgreement(
        item_id=item.id,
        renter_id=renter.id,
        owner_id=item.owner_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        total_days=total_days,
        daily_rate=item.base_rate_daily,
        base_rent=base_rent,
        security_deposit=security_deposit,
        service_fee=service_fee,
        insurance_fee=insurance_fee,
        total_amount=total_amount,
        terms_version="v1.0",
        agreed_at=datetime.utcnow(),
        status="pending_payment"
    )
    db.add(agreement)
    db.commit()
    db.refresh(agreement)

    owner = item.owner
    owner_name = f"{owner.first_name} {owner.last_name}" if owner else "Verified Owner"
    renter_name = f"{renter.first_name} {renter.last_name}"

    return RentalAgreementResponse(
        id=agreement.id,
        agreement_code=f"SHR-AGR-{agreement.id:05d}",
        item_id=item.id,
        item_title=item.title,
        owner_name=owner_name,
        renter_name=renter_name,
        start_date=agreement.start_date,
        end_date=agreement.end_date,
        total_days=agreement.total_days,
        daily_rate=agreement.daily_rate,
        base_rent=agreement.base_rent,
        security_deposit=agreement.security_deposit,
        service_fee=agreement.service_fee,
        insurance_fee=agreement.insurance_fee,
        total_amount=agreement.total_amount,
        terms_version=agreement.terms_version,
        agreed_at=agreement.agreed_at,
        status=agreement.status
    )
