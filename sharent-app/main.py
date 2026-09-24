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

from models import init_db, get_db, User, Item, OTPVerification, ItemAvailability, RentalAgreement, PaymentTransaction, RentalHandoverInspection, RentalReview
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
    CheckoutPaymentRequest,
    CheckoutPaymentResponse,
    HandoverVerificationRequest,
    ReturnInspectionRequest,
    RentalSummaryItem,
    CreateReviewRequest,
    ReviewResponse,
    ItemReviewSummaryResponse,
    ItemCriteriaBreakdown,
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


import random

@app.post("/api/checkout/pay", response_model=CheckoutPaymentResponse)
def process_checkout_payment(payload: CheckoutPaymentRequest, db: Session = Depends(get_db)):
    # 1. Fetch Rental Agreement
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == payload.agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")
    if agreement.renter_id != payload.renter_id:
        raise HTTPException(status_code=403, detail="Unauthorized: Agreement belongs to another renter.")
    if agreement.status == "confirmed":
        raise HTTPException(status_code=400, detail="Payment for this rental agreement has already been processed.")

    # 2. Validate Payment Details (Card Simulation)
    clean_card = payload.card_number.replace(" ", "").replace("-", "")
    if len(clean_card) < 13 or not clean_card.isdigit():
        raise HTTPException(status_code=400, detail="Invalid card number. Please provide a valid 13-19 digit card number.")
    if len(payload.cvv) not in (3, 4) or not payload.cvv.isdigit():
        raise HTTPException(status_code=400, detail="Invalid CVV security code.")
    if not payload.billing_zip.strip():
        raise HTTPException(status_code=400, detail="Billing ZIP code is required.")

    # Simulated decline rule: Card ending in 0000 simulates decline
    if clean_card.endswith("0000"):
        raise HTTPException(status_code=402, detail="Card was declined by issuing bank (insufficient funds / fraud trigger).")

    card_last4 = clean_card[-4:]
    amount_charged = round(agreement.base_rent + agreement.service_fee + agreement.insurance_fee, 2)
    escrow_deposit_held = round(agreement.security_deposit, 2)
    total_paid = agreement.total_amount

    # 3. Generate secure Transaction Reference and 4-digit Handover Verification PIN
    txn_code = f"TXN-{random.randint(10000000, 99999999)}"
    handover_pin = f"{random.randint(1000, 9999)}"

    # 4. Record Payment Transaction
    transaction = PaymentTransaction(
        agreement_id=agreement.id,
        renter_id=agreement.renter_id,
        transaction_code=txn_code,
        payment_method=payload.payment_method,
        card_last4=card_last4,
        amount_charged=amount_charged,
        escrow_deposit_held=escrow_deposit_held,
        total_paid=total_paid,
        payment_status="escrow_held",
        handover_pin=handover_pin,
        created_at=datetime.utcnow()
    )
    db.add(transaction)

    # 5. Lock Dates on Item Availability Calendar
    # Block out all days of the rental as 'booked'
    cur_date = agreement.start_date
    while cur_date < agreement.end_date:
        existing_avail = db.query(ItemAvailability).filter(
            ItemAvailability.item_id == agreement.item_id,
            ItemAvailability.date == cur_date
        ).first()

        if existing_avail:
            existing_avail.status = "booked"
            existing_avail.reason = f"Rented (Agr #{agreement.id})"
        else:
            db.add(ItemAvailability(
                item_id=agreement.item_id,
                date=cur_date,
                status="booked",
                reason=f"Rented (Agr #{agreement.id})"
            ))
        cur_date += timedelta(days=1)

    # 6. Update Agreement status
    agreement.status = "confirmed"
    db.commit()
    db.refresh(transaction)

    item = agreement.item
    owner = item.owner if item else None
    renter = agreement.renter
    owner_name = f"{owner.first_name} {owner.last_name}" if owner else "Verified Owner"
    renter_name = f"{renter.first_name} {renter.last_name}" if renter else "Verified Renter"

    return CheckoutPaymentResponse(
        id=transaction.id,
        transaction_code=transaction.transaction_code,
        agreement_code=f"SHR-AGR-{agreement.id:05d}",
        item_title=item.title if item else "Rental Item",
        owner_name=owner_name,
        renter_name=renter_name,
        start_date=agreement.start_date,
        end_date=agreement.end_date,
        total_days=agreement.total_days,
        amount_charged=transaction.amount_charged,
        escrow_deposit_held=transaction.escrow_deposit_held,
        total_paid=transaction.total_paid,
        card_last4=transaction.card_last4,
        payment_status="Confirmed & Escrow Held",
        handover_pin=transaction.handover_pin,
        created_at=transaction.created_at
    )


@app.post("/api/rentals/verify-handover")
def verify_item_handover(payload: HandoverVerificationRequest, db: Session = Depends(get_db)):
    # 1. Fetch Agreement
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == payload.agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")

    # 2. Check Owner authorization
    if agreement.owner_id != payload.owner_id:
        raise HTTPException(status_code=403, detail="Unauthorized: Only the item owner can verify handover.")

    if agreement.status != "confirmed":
        raise HTTPException(status_code=400, detail=f"Cannot verify handover for agreement with status '{agreement.status}'. Must be 'confirmed'.")

    # 3. Fetch Transaction & Verify PIN
    txn = db.query(PaymentTransaction).filter(PaymentTransaction.agreement_id == agreement.id).first()
    if not txn:
        raise HTTPException(status_code=400, detail="No payment transaction found for this agreement.")

    if payload.entered_pin.strip() != txn.handover_pin.strip():
        raise HTTPException(status_code=400, detail="Invalid Handover PIN. Please check the 4-digit code provided by the renter.")

    # 4. Record Handover
    inspection = db.query(RentalHandoverInspection).filter(RentalHandoverInspection.agreement_id == agreement.id).first()
    if not inspection:
        inspection = RentalHandoverInspection(agreement_id=agreement.id)
        db.add(inspection)

    inspection.pickup_verified_at = datetime.utcnow()
    inspection.pickup_notes = payload.pickup_notes
    agreement.status = "active"  # Rental is now actively underway
    db.commit()

    return {
        "message": "Handover verified successfully! Item is officially in the renter's possession.",
        "agreement_code": f"SHR-AGR-{agreement.id:05d}",
        "status": "active",
        "pickup_verified_at": inspection.pickup_verified_at
    }


@app.post("/api/rentals/return-inspection")
def complete_return_inspection(payload: ReturnInspectionRequest, db: Session = Depends(get_db)):
    # 1. Fetch Agreement
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == payload.agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")

    if agreement.owner_id != payload.owner_id:
        raise HTTPException(status_code=403, detail="Unauthorized: Only the item owner can complete the return inspection.")

    if agreement.status != "active":
        raise HTTPException(status_code=400, detail=f"Cannot inspect return for agreement in status '{agreement.status}'. Must be 'active'.")

    # 2. Fetch Handover Record & Payment Transaction
    inspection = db.query(RentalHandoverInspection).filter(RentalHandoverInspection.agreement_id == agreement.id).first()
    if not inspection:
        inspection = RentalHandoverInspection(agreement_id=agreement.id)
        db.add(inspection)

    txn = db.query(PaymentTransaction).filter(PaymentTransaction.agreement_id == agreement.id).first()

    # 3. Record Return Inspection Details
    inspection.return_verified_at = datetime.utcnow()
    inspection.condition_on_return = payload.condition_on_return
    inspection.all_accessories_returned = payload.all_accessories_returned
    inspection.cleaned_properly = payload.cleaned_properly
    inspection.inspection_notes = payload.inspection_notes

    # 4. Trigger Escrow Deposit Refund (100% refund when good / like_new)
    if payload.condition_on_return in ["like_new", "good"] and payload.all_accessories_returned:
        refund_amount = agreement.security_deposit
        inspection.deposit_refund_status = "released"
        inspection.deposit_refunded_amount = refund_amount
        if txn:
            txn.payment_status = "deposit_refunded"
    else:
        # Partial deduction or held for dispute mediation
        refund_amount = round(max(0.0, agreement.security_deposit * 0.5), 2)
        inspection.deposit_refund_status = "held_dispute"
        inspection.deposit_refunded_amount = refund_amount

    # 5. Mark Agreement Completed
    agreement.status = "completed"
    db.commit()

    return {
        "message": "Return inspection completed! Security deposit escrow has been released to the renter.",
        "agreement_code": f"SHR-AGR-{agreement.id:05d}",
        "status": "completed",
        "deposit_refund_status": inspection.deposit_refund_status,
        "deposit_refunded_amount": inspection.deposit_refunded_amount,
        "return_verified_at": inspection.return_verified_at
    }


@app.get("/api/rentals/user/{user_id}")
def get_user_rentals(user_id: int, role: str = "renter", db: Session = Depends(get_db)):
    if role == "owner":
        agreements = db.query(RentalAgreement).filter(RentalAgreement.owner_id == user_id).order_by(RentalAgreement.id.desc()).all()
    else:
        agreements = db.query(RentalAgreement).filter(RentalAgreement.renter_id == user_id).order_by(RentalAgreement.id.desc()).all()

    results = []
    for agr in agreements:
        txn = db.query(PaymentTransaction).filter(PaymentTransaction.agreement_id == agr.id).first()
        insp = db.query(RentalHandoverInspection).filter(RentalHandoverInspection.agreement_id == agr.id).first()
        item = agr.item
        owner = item.owner if item else None
        renter = agr.renter

        results.append({
            "agreement_id": agr.id,
            "agreement_code": f"SHR-AGR-{agr.id:05d}",
            "item_id": agr.item_id,
            "item_title": item.title if item else "Item",
            "renter_id": agr.renter_id,
            "renter_name": f"{renter.first_name} {renter.last_name}" if renter else "Renter",
            "owner_id": agr.owner_id,
            "owner_name": f"{owner.first_name} {owner.last_name}" if owner else "Owner",
            "start_date": agr.start_date,
            "end_date": agr.end_date,
            "total_days": agr.total_days,
            "total_amount": agr.total_amount,
            "security_deposit": agr.security_deposit,
            "status": agr.status,
            "handover_pin": txn.handover_pin if txn else None,
            "deposit_refund_status": insp.deposit_refund_status if insp else None,
            "deposit_refunded_amount": insp.deposit_refunded_amount if insp else None,
            "has_reviewed": db.query(RentalReview).filter(RentalReview.agreement_id == agr.id, RentalReview.reviewer_id == user_id).first() is not None
        })

    return results


@app.post("/api/reviews", response_model=ReviewResponse)
def submit_rental_review(payload: CreateReviewRequest, db: Session = Depends(get_db)):
    # 1. Fetch Agreement
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == payload.agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")
    if agreement.status != "completed":
        raise HTTPException(status_code=400, detail="Reviews can only be submitted after the rental has been completed and returned.")

    # 2. Determine Role and Target Reviewee
    if payload.reviewer_id == agreement.renter_id:
        role = "renter_to_owner"
        reviewee_id = agreement.owner_id
    elif payload.reviewer_id == agreement.owner_id:
        role = "owner_to_renter"
        reviewee_id = agreement.renter_id
    else:
        raise HTTPException(status_code=403, detail="Unauthorized: Only the renter or owner of this agreement can submit a review.")

    # 3. Check for Duplicate Review
    existing = db.query(RentalReview).filter(
        RentalReview.agreement_id == agreement.id,
        RentalReview.reviewer_id == payload.reviewer_id
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You have already submitted a review for this rental.")

    if not payload.comment.strip():
        raise HTTPException(status_code=400, detail="Please provide a comment sharing your feedback.")

    # 4. Compute overall rating from specific criteria
    if role == "renter_to_owner":
        item_scores = [
            payload.item_accuracy or 5,
            payload.item_condition or 5,
            payload.item_ease_of_use or 5,
            payload.item_instructions or 5,
            payload.item_value or 5
        ]
        owner_scores = [
            payload.owner_response_time or 5,
            payload.owner_communication or 5,
            payload.owner_friendliness or 5,
            payload.owner_pickup_ease or 5,
            payload.owner_return_ease or 5
        ]
        for s in item_scores + owner_scores:
            if not (1 <= s <= 5):
                raise HTTPException(status_code=400, detail="All rating criteria scores must be between 1 and 5 stars.")
        
        overall = round(sum(item_scores + owner_scores) / len(item_scores + owner_scores), 1)

        review = RentalReview(
            agreement_id=agreement.id,
            reviewer_id=payload.reviewer_id,
            reviewee_id=reviewee_id,
            item_id=agreement.item_id,
            role=role,
            rating=overall,
            comment=payload.comment.strip(),
            tags=",".join(payload.tags) if payload.tags else "",
            created_at=datetime.utcnow(),
            # Item criteria
            item_accuracy=payload.item_accuracy or 5,
            item_condition=payload.item_condition or 5,
            item_ease_of_use=payload.item_ease_of_use or 5,
            item_instructions=payload.item_instructions or 5,
            item_value=payload.item_value or 5,
            # Owner criteria
            owner_response_time=payload.owner_response_time or 5,
            owner_communication=payload.owner_communication or 5,
            owner_friendliness=payload.owner_friendliness or 5,
            owner_pickup_ease=payload.owner_pickup_ease or 5,
            owner_return_ease=payload.owner_return_ease or 5
        )
    else:
        # Owner rating Renter
        renter_scores = [
            payload.renter_communication or 5,
            payload.renter_responsibility or 5,
            payload.renter_friendliness or 5,
            payload.renter_care_of_item or 5,
            payload.renter_return_condition or 5
        ]
        for s in renter_scores:
            if not (1 <= s <= 5):
                raise HTTPException(status_code=400, detail="All rating criteria scores must be between 1 and 5 stars.")

        overall = round(sum(renter_scores) / len(renter_scores), 1)

        review = RentalReview(
            agreement_id=agreement.id,
            reviewer_id=payload.reviewer_id,
            reviewee_id=reviewee_id,
            item_id=agreement.item_id,
            role=role,
            rating=overall,
            comment=payload.comment.strip(),
            tags=",".join(payload.tags) if payload.tags else "",
            created_at=datetime.utcnow(),
            # Renter criteria
            renter_communication=payload.renter_communication or 5,
            renter_responsibility=payload.renter_responsibility or 5,
            renter_friendliness=payload.renter_friendliness or 5,
            renter_care_of_item=payload.renter_care_of_item or 5,
            renter_return_condition=payload.renter_return_condition or 5
        )

    db.add(review)
    db.commit()
    db.refresh(review)

    reviewer = review.reviewer
    reviewee = review.reviewee

    return ReviewResponse(
        id=review.id,
        agreement_id=review.agreement_id,
        reviewer_name=f"{reviewer.first_name} {reviewer.last_name}" if reviewer else "Member",
        reviewee_name=f"{reviewee.first_name} {reviewee.last_name}" if reviewee else "Member",
        role=review.role,
        rating=review.rating,
        comment=review.comment,
        tags=review.tags.split(",") if review.tags else [],
        created_at=review.created_at,
        item_accuracy=review.item_accuracy,
        item_condition=review.item_condition,
        item_ease_of_use=review.item_ease_of_use,
        item_instructions=review.item_instructions,
        item_value=review.item_value,
        owner_response_time=review.owner_response_time,
        owner_communication=review.owner_communication,
        owner_friendliness=review.owner_friendliness,
        owner_pickup_ease=review.owner_pickup_ease,
        owner_return_ease=review.owner_return_ease,
        renter_communication=review.renter_communication,
        renter_responsibility=review.renter_responsibility,
        renter_friendliness=review.renter_friendliness,
        renter_care_of_item=review.renter_care_of_item,
        renter_return_condition=review.renter_return_condition
    )


@app.get("/api/items/{item_id}/reviews", response_model=ItemReviewSummaryResponse)
def get_item_reviews(item_id: int, db: Session = Depends(get_db)):
    reviews = db.query(RentalReview).filter(
        RentalReview.item_id == item_id,
        RentalReview.role == "renter_to_owner"
    ).order_by(RentalReview.created_at.desc()).all()

    rev_list = []
    total_rating = 0.0
    acc_sum = 0.0
    cond_sum = 0.0
    ease_sum = 0.0
    inst_sum = 0.0
    val_sum = 0.0

    for r in reviews:
        total_rating += (r.rating or 5.0)
        acc_sum += (r.item_accuracy or 5)
        cond_sum += (r.item_condition or 5)
        ease_sum += (r.item_ease_of_use or 5)
        inst_sum += (r.item_instructions or 5)
        val_sum += (r.item_value or 5)

        rev_list.append(ReviewResponse(
            id=r.id,
            agreement_id=r.agreement_id,
            reviewer_name=f"{r.reviewer.first_name} {r.reviewer.last_name}" if r.reviewer else "Verified Renter",
            reviewee_name=f"{r.reviewee.first_name} {r.reviewee.last_name}" if r.reviewee else "Verified Owner",
            role=r.role,
            rating=r.rating,
            comment=r.comment,
            tags=r.tags.split(",") if r.tags else [],
            created_at=r.created_at,
            item_accuracy=r.item_accuracy,
            item_condition=r.item_condition,
            item_ease_of_use=r.item_ease_of_use,
            item_instructions=r.item_instructions,
            item_value=r.item_value,
            owner_response_time=r.owner_response_time,
            owner_communication=r.owner_communication,
            owner_friendliness=r.owner_friendliness,
            owner_pickup_ease=r.owner_pickup_ease,
            owner_return_ease=r.owner_return_ease
        ))

    n = len(reviews)
    avg_total = round(total_rating / n, 1) if n > 0 else 5.0
    breakdown = {
        "accuracy": round(acc_sum / n, 1) if n > 0 else 5.0,
        "condition": round(cond_sum / n, 1) if n > 0 else 5.0,
        "ease_of_use": round(ease_sum / n, 1) if n > 0 else 5.0,
        "instructions": round(inst_sum / n, 1) if n > 0 else 5.0,
        "value": round(val_sum / n, 1) if n > 0 else 5.0,
    }

    return ItemReviewSummaryResponse(
        item_id=item_id,
        average_rating=avg_total,
        total_reviews=n,
        criteria_breakdown=breakdown,
        reviews=rev_list
    )
