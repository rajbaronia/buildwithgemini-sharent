import deposit_engine
from geo_utils import resolve_coordinates, haversine_distance_miles
from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import List, Optional
import os
import uuid
import json

from models import init_db, get_db, User, Item, OTPVerification, ItemAvailability, RentalAgreement, PaymentTransaction, RentalHandoverInspection, RentalReview, UserWallet, WalletTransaction, PromotionalProgramConfig, UserBonusTracker, UserReferral, DisputeClaim, ChatMessage, NotificationEvent
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
    UserWalletResponse,
    WalletTransactionResponse,
    WithdrawalRequest,
    WalletDepositRequest,
    WalletDepositResponse,
    PromotionalProgramConfigResponse,
    PromotionalProgramConfigRequest,
    UserBonusProgressResponse,
    MyReferralCodeResponse,
    ReferralItemResponse,
    DisputeClaimCreateRequest,
    DisputeResponseRequest,
    AdminDisputeResolveRequest,
    DisputeClaimResponse,
    ChatMessageSendRequest,
    ChatMessageResponse,
    ChatThreadSummary,
    NotificationDispatchTestRequest,
    NotificationEventResponse,
    NotificationSummaryResponse,
)



import uuid
import urllib.parse

def generate_unique_referral_code(user_first_name: str, db: Session) -> str:
    clean_name = "".join(c for c in (user_first_name or "USER") if c.isalnum()).upper()[:4]
    if len(clean_name) < 2:
        clean_name = "SHARE"
    for _ in range(10):
        code = f"REF-{clean_name}-{uuid.uuid4().hex[:6].upper()}"
        existing = db.query(User).filter(User.referral_code == code).first()
        if not existing:
            return code
    return f"REF-{uuid.uuid4().hex[:8].upper()}"

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

    ref_code = generate_unique_referral_code(payload.first_name, db)
    referrer = None
    if payload.referral_code:
        referrer = db.query(User).filter(User.referral_code == payload.referral_code.strip().upper()).first()

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
        referral_code=ref_code,
        referred_by_id=referrer.id if referrer else None
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    if referrer:
        config = get_or_create_promotional_config(db)
        referral_record = UserReferral(
            referrer_id=referrer.id,
            invitee_id=new_user.id,
            referral_code=payload.referral_code.strip().upper(),
            status="pending",
            referrer_bonus_amount=config.referrer_bonus_amount if config.referrer_bonus_amount is not None else 15.0,
            invitee_bonus_amount=config.invitee_bonus_amount if config.invitee_bonus_amount is not None else 20.0,
            channel_source="link"
        )
        db.add(referral_record)
        db.commit()

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


def get_or_create_user_wallet(user_id: int, db: Session, initial_credit: float = 0.0) -> UserWallet:
    wallet = db.query(UserWallet).filter(UserWallet.user_id == user_id).first()
    if not wallet:
        wallet = UserWallet(
            user_id=user_id,
            promotional_credit_balance=initial_credit,
            withdrawable_cash_balance=0.0
        )
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
        if initial_credit > 0:
            tx = WalletTransaction(
                wallet_id=wallet.id,
                user_id=user_id,
                transaction_type="signup_bonus",
                balance_type="promotional_credit",
                amount=initial_credit,
                description="Welcome Sign-Up Bonus Credit (Non-Withdrawable)",
                created_at=datetime.utcnow()
            )
            db.add(tx)
            db.commit()
    return wallet

def get_or_create_promotional_config(db: Session) -> PromotionalProgramConfig:
    config = db.query(PromotionalProgramConfig).filter(PromotionalProgramConfig.program_key == "signup_inventory_listing_bonus").first()
    if not config:
        config = PromotionalProgramConfig(
            program_key="signup_inventory_listing_bonus",
            program_name="Sign-Up Inventory Listing Bonus",
            bonus_amount=20.0,
            referrer_bonus_amount=15.0,
            invitee_bonus_amount=20.0,
            required_active_items=10,
            required_active_days=90,
            is_active=True,
            description="Earn $20.00 Sharent promotional bonus credit by listing at least 10 active items for at least 3 months (90 days)."
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    return config

def evaluate_user_promotional_bonus(user_id: int, db: Session):
    config = get_or_create_promotional_config(db)
    if not config.is_active:
        return None

    tracker = db.query(UserBonusTracker).filter(
        UserBonusTracker.user_id == user_id,
        UserBonusTracker.program_key == config.program_key
    ).first()

    if not tracker:
        tracker = UserBonusTracker(
            user_id=user_id,
            program_key=config.program_key,
            bonus_awarded=False
        )
        db.add(tracker)
        db.commit()
        db.refresh(tracker)

    if tracker.bonus_awarded:
        return tracker

    # Count qualifying items:
    # 1. Owner is user_id
    # 2. Item is currently active (is_available == True)
    # 3. Active committed duration >= required_active_days (default 90 days / 3 months)
    qualifying_items = db.query(Item).filter(
        Item.owner_id == user_id,
        Item.is_available == True,
        Item.active_duration_days >= config.required_active_days
    ).all()

    qualifying_count = len(qualifying_items)

    if config.required_active_items == 0 or qualifying_count >= config.required_active_items:
        # Conditions met! Unlock and credit the sign-up bonus into user's wallet
        wallet = get_or_create_user_wallet(user_id, db)
        wallet.promotional_credit_balance = round(wallet.promotional_credit_balance + config.bonus_amount, 2)

        tx = WalletTransaction(
            wallet_id=wallet.id,
            user_id=user_id,
            transaction_type="signup_bonus",
            balance_type="promotional_credit",
            amount=config.bonus_amount,
            description=f"Unlocked Welcome Sign-Up Bonus (Listed {qualifying_count}/{config.required_active_items} active items for {config.required_active_days}+ days)",
            created_at=datetime.utcnow()
        )
        db.add(tx)

        tracker.bonus_awarded = True
        tracker.bonus_amount_awarded = config.bonus_amount
        tracker.awarded_at = datetime.utcnow()
        tracker.last_evaluated_at = datetime.utcnow()

        # Check if this user was referred by someone -> Award Referrer Bonus!
        invitee_user = db.query(User).filter(User.id == user_id).first()
        if invitee_user and invitee_user.referred_by_id:
            referral = db.query(UserReferral).filter(
                UserReferral.invitee_id == user_id,
                UserReferral.status == "pending"
            ).first()
            if referral:
                ref_bonus = config.referrer_bonus_amount or 15.0
                referrer_wallet = get_or_create_user_wallet(invitee_user.referred_by_id, db)
                referrer_wallet.promotional_credit_balance = round(referrer_wallet.promotional_credit_balance + ref_bonus, 2)

                ref_tx = WalletTransaction(
                    wallet_id=referrer_wallet.id,
                    user_id=invitee_user.referred_by_id,
                    transaction_type="referral_bonus",
                    balance_type="promotional_credit",
                    amount=ref_bonus,
                    description=f"Referral Bonus for inviting {invitee_user.first_name} {invitee_user.last_name} (Completed active inventory listings)",
                    created_at=datetime.utcnow()
                )
                db.add(ref_tx)

                referral.status = "completed"
                referral.referrer_bonus_amount = ref_bonus
                referral.invitee_bonus_amount = config.bonus_amount
                referral.awarded_at = datetime.utcnow()

        db.commit()
        db.refresh(tracker)

    return tracker



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

    # Location resolution: Default to Owner's address if not provided or empty
    final_location_address = payload.location_address.strip() if (payload.location_address and payload.location_address.strip()) else (user.address or "San Ramon, CA")
    
    # Resolve coordinates for item
    if payload.latitude is not None and payload.longitude is not None:
        item_lat, item_lon = payload.latitude, payload.longitude
    else:
        item_lat, item_lon = resolve_coordinates(final_location_address)

    # Also backfill user coordinates if missing
    if user.latitude is None or user.longitude is None:
        u_lat, u_lon = resolve_coordinates(user.address)
        user.latitude = u_lat
        user.longitude = u_lon

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
        location_city=payload.location_city.strip() if payload.location_city else "San Ramon, CA",
        location_address=final_location_address,
        latitude=item_lat,
        longitude=item_lon,
        is_available=True,
        active_duration_days=payload.active_duration_days if payload.active_duration_days is not None else 90,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    # Evaluate conditional sign-up bonus criteria
    evaluate_user_promotional_bonus(payload.owner_id, db)

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
def get_marketplace_items(
    renter_id: int,
    radius_miles: Optional[float] = None,
    near_address: Optional[str] = None,
    category: Optional[str] = None,
    query: Optional[str] = None,
    db: Session = Depends(get_db)
):
    renter = db.query(User).filter(User.id == renter_id).first()
    
    # Determine renter reference coordinates for vicinity calculations
    if near_address and near_address.strip():
        center_lat, center_lon = resolve_coordinates(near_address.strip())
    elif renter and renter.latitude is not None and renter.longitude is not None:
        center_lat, center_lon = renter.latitude, renter.longitude
    elif renter and renter.address:
        center_lat, center_lon = resolve_coordinates(renter.address)
        renter.latitude = center_lat
        renter.longitude = center_lon
        db.commit()
    else:
        center_lat, center_lon = resolve_coordinates("San Ramon, CA")

    item_query = db.query(Item).filter(
        Item.owner_id != renter_id,
        Item.is_available == True
    )

    if category and category.strip() and category != "All":
        item_query = item_query.filter(Item.category == category.strip())

    items = item_query.order_by(Item.id.desc()).all()

    results = []
    for item in items:
        # Ensure item has lat/lon coordinates
        if item.latitude is None or item.longitude is None:
            item_coords = resolve_coordinates(item.location_address or item.location_city or "San Ramon, CA")
            item.latitude = item_coords[0]
            item.longitude = item_coords[1]
            db.commit()

        # Compute vicinity / Haversine distance from renter's center point
        dist = haversine_distance_miles(center_lat, center_lon, item.latitude, item.longitude)

        # Filter out if radius_miles is supplied and exceeds limit
        if radius_miles is not None and radius_miles > 0:
            if dist > radius_miles:
                continue

        # Optional keyword query filter
        if query and query.strip():
            q_lower = query.strip().lower()
            if q_lower not in item.title.lower() and q_lower not in item.description.lower() and q_lower not in item.category.lower() and (not item.location_address or q_lower not in item.location_address.lower()):
                continue

        r = ItemResponse.model_validate(item)
        owner = db.query(User).filter(User.id == item.owner_id).first()
        r.owner_name = f"{owner.first_name} {owner.last_name}" if owner else "Community Member"
        r.images = item.images
        r.distance_miles = dist
        results.append(r)

    # Sort results by proximity (closest items first)
    results.sort(key=lambda x: x.distance_miles if x.distance_miles is not None else 9999.0)
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

    # Owner Discretionary Security Deposit Evaluation (Module 22)
    deposit_eval = deposit_engine.evaluate_renter_deposit_tier(item, payload.renter_id, db)
    security_deposit = deposit_eval["security_deposit"]
    original_security_deposit = deposit_eval["original_security_deposit"]
    deposit_discount_pct = deposit_eval["deposit_discount_pct"]
    deposit_tier_status = deposit_eval["tier_status"]
    deposit_evaluation_reason = deposit_eval["evaluation_reason"]

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
        original_security_deposit=original_security_deposit,
        deposit_discount_pct=deposit_discount_pct,
        deposit_tier_status=deposit_tier_status,
        deposit_evaluation_reason=deposit_evaluation_reason,
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

    # 6. Calculate fee itemization with Owner Discretionary Deposit (Module 22)
    base_rent = round(total_days * item.base_rate_daily, 2)
    service_fee = round(1.00 + (base_rent * 0.05), 2)
    insurance_fee = round(max(3.00, base_rent * 0.08), 2) if item.insurance_required else 0.0
    
    deposit_eval = deposit_engine.evaluate_renter_deposit_tier(item, renter.id, db)
    security_deposit = deposit_eval["security_deposit"]
    original_security_deposit = deposit_eval["original_security_deposit"]
    deposit_discount_pct = deposit_eval["deposit_discount_pct"]
    deposit_evaluation_reason = deposit_eval["evaluation_reason"]
    deposit_adjusted_by_owner = False
    owner_adjustment_notes = payload.owner_adjustment_notes

    # Manual Owner Discretion Override if specified on creation
    if payload.owner_custom_deposit is not None:
        custom_dep = max(0.0, round(float(payload.owner_custom_deposit), 2))
        security_deposit = custom_dep
        deposit_adjusted_by_owner = True
        if original_security_deposit > 0:
            deposit_discount_pct = round(max(0.0, (original_security_deposit - security_deposit) / original_security_deposit * 100), 1)
        else:
            deposit_discount_pct = 100.0 if security_deposit == 0 else 0.0
        if security_deposit == 0:
            deposit_evaluation_reason = f"Security Deposit manually waived by Owner ({owner_adjustment_notes or 'Special courtesy'})."
        else:
            deposit_evaluation_reason = f"Security Deposit manually adjusted by Owner to ${security_deposit:.2f} ({owner_adjustment_notes or 'Case-by-case agreement'})."

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
        original_security_deposit=original_security_deposit,
        deposit_discount_pct=deposit_discount_pct,
        deposit_evaluation_reason=deposit_evaluation_reason,
        deposit_adjusted_by_owner=deposit_adjusted_by_owner,
        owner_adjustment_notes=owner_adjustment_notes,
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

    # Trigger Notification Engine: New booking request for owner
    dispatch_notification(
        db=db,
        user=agreement.owner,
        event_type="booking_request",
        title=f"New Booking Request: {item.title}",
        message=f"{renter.first_name} requested to rent {item.title} for {agreement.total_days} days.",
        channels=["push", "email"],
        metadata_json={"agreement_id": agreement.id}
    )

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
        original_security_deposit=agreement.original_security_deposit,
        deposit_discount_pct=agreement.deposit_discount_pct,
        deposit_evaluation_reason=agreement.deposit_evaluation_reason,
        deposit_adjusted_by_owner=agreement.deposit_adjusted_by_owner,
        owner_adjustment_notes=agreement.owner_adjustment_notes,
        service_fee=agreement.service_fee,
        insurance_fee=agreement.insurance_fee,
        total_amount=agreement.total_amount,
        terms_version=agreement.terms_version,
        agreed_at=agreement.agreed_at,
        status=agreement.status
    )



from schemas import OwnerDepositAdjustmentRequest

@app.post("/api/rental-agreements/{agreement_id}/adjust-deposit")
def adjust_agreement_deposit_by_owner(
    agreement_id: int,
    payload: OwnerDepositAdjustmentRequest,
    db: Session = Depends(get_db)
):
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")

    if agreement.owner_id != payload.owner_id:
        raise HTTPException(status_code=403, detail="Only the listing Owner can adjust the security deposit for this rental agreement.")

    if agreement.status != "pending_payment":
        raise HTTPException(status_code=400, detail=f"Cannot adjust deposit for an agreement in '{agreement.status}' status. Only pending agreements can be adjusted before payment.")

    orig_deposit = agreement.original_security_deposit if (agreement.original_security_deposit is not None) else agreement.security_deposit
    
    if payload.action == "waive":
        new_deposit = 0.0
        pct = 100.0
        reason = f"Security Deposit 100% Waived by Owner ({payload.notes or 'Owner Discretion'})."
    elif payload.action == "reduce":
        # Default reduce: reduce by half or specified new_deposit
        if payload.new_deposit is not None:
            new_deposit = max(0.0, round(float(payload.new_deposit), 2))
        else:
            new_deposit = round(orig_deposit * 0.5, 2)
        pct = round(max(0.0, (orig_deposit - new_deposit) / orig_deposit * 100), 1) if orig_deposit > 0 else 0.0
        reason = f"Security Deposit manually reduced to ${new_deposit:.2f} by Owner ({payload.notes or 'Owner Discretion'})."
    elif payload.action == "custom":
        if payload.new_deposit is None:
            raise HTTPException(status_code=400, detail="Must provide 'new_deposit' for custom adjustment.")
        new_deposit = max(0.0, round(float(payload.new_deposit), 2))
        pct = round(max(0.0, (orig_deposit - new_deposit) / orig_deposit * 100), 1) if orig_deposit > 0 else 0.0
        reason = f"Security Deposit set to ${new_deposit:.2f} by Owner ({payload.notes or 'Special Terms'})."
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Must be 'waive', 'reduce', or 'custom'.")

    # Update agreement
    agreement.security_deposit = new_deposit
    agreement.deposit_discount_pct = pct
    agreement.deposit_evaluation_reason = reason
    agreement.deposit_adjusted_by_owner = True
    agreement.owner_adjustment_notes = payload.notes or ""
    agreement.total_amount = round(agreement.base_rent + agreement.service_fee + agreement.insurance_fee + new_deposit, 2)

    db.commit()
    db.refresh(agreement)

    # Notify renter about the deposit adjustment
    renter = agreement.renter
    item = agreement.item
    item_title = item.title if item else "Equipment"
    dispatch_notification(
        db=db,
        user=renter,
        event_type="deposit_adjusted",
        title=f"Deposit Adjusted for {item_title}!",
        message=f"The Owner has adjusted your deposit to ${new_deposit:.2f} ({reason}). You may now complete your payment.",
        channels=["push", "email", "sms"],
        metadata_json={"agreement_id": agreement.id, "new_deposit": new_deposit}
    )

    return {
        "message": "Security deposit successfully adjusted by Owner.",
        "agreement_id": agreement.id,
        "agreement_code": f"SHR-AGR-{agreement.id:05d}",
        "security_deposit": agreement.security_deposit,
        "original_security_deposit": orig_deposit,
        "deposit_discount_pct": agreement.deposit_discount_pct,
        "deposit_evaluation_reason": agreement.deposit_evaluation_reason,
        "deposit_adjusted_by_owner": agreement.deposit_adjusted_by_owner,
        "owner_adjustment_notes": agreement.owner_adjustment_notes,
        "total_amount": agreement.total_amount
    }


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

    renter_wallet = get_or_create_user_wallet(agreement.renter_id, db)

    # 2. Credit application rule:
    # Credits CAN be used for base_rent and service_fee.
    # Credits CANNOT be used for security_deposit and insurance_fee.
    # Credit is applied to base_rent first, then to service_fee.
    credit_to_apply = 0.0
    rent_credit_used = 0.0
    service_fee_credit_used = 0.0

    if payload.apply_credit and renter_wallet.total_balance > 0:
        # First cover base_rent
        rent_credit_used = min(renter_wallet.total_balance, agreement.base_rent)
        remaining_balance = round(renter_wallet.total_balance - rent_credit_used, 2)
        # Then cover service_fee
        service_fee_credit_used = min(remaining_balance, agreement.service_fee)
        credit_to_apply = round(rent_credit_used + service_fee_credit_used, 2)

    # External charge required
    external_rent = round(agreement.base_rent - rent_credit_used, 2)
    external_service_fee = round(agreement.service_fee - service_fee_credit_used, 2)
    insurance_fee = round(agreement.insurance_fee, 2)
    escrow_deposit_held = round(agreement.security_deposit, 2)
    
    amount_charged = round(external_rent + external_service_fee + insurance_fee, 2)
    external_total = round(amount_charged + escrow_deposit_held, 2)
    total_paid = agreement.total_amount

    # 3. Simulate Payment Gateway Authorization if external charge > 0
    card_last4 = "CREDIT"
    if external_total > 0:
        if payload.payment_method == "credit_card":
            if not payload.card_number:
                raise HTTPException(status_code=400, detail="Card number is required to cover insurance/deposit/remaining balance.")
            clean_card = payload.card_number.replace(" ", "").replace("-", "")
            if len(clean_card) < 13 or not clean_card.isdigit():
                raise HTTPException(status_code=400, detail="Invalid card number. Please provide a valid 13-19 digit card number.")
            if payload.cvv and (len(payload.cvv) not in (3, 4) or not payload.cvv.isdigit()):
                raise HTTPException(status_code=400, detail="Invalid CVV security code.")
            if clean_card.endswith("0000"):
                raise HTTPException(status_code=402, detail="Card was declined by issuing bank (insufficient funds / fraud trigger).")
            card_last4 = clean_card[-4:]
        elif payload.payment_method in ["paypal", "venmo"]:
            card_last4 = payload.payment_method.upper()
        else:
            card_last4 = "CARD"

    # 4. Deduct credit from Renter wallet (first promotional bonus, then withdrawable cash)
    promotional_credit_used = 0.0
    cash_credit_used = 0.0
    if credit_to_apply > 0:
        if renter_wallet.promotional_credit_balance >= credit_to_apply:
            promotional_credit_used = credit_to_apply
            renter_wallet.promotional_credit_balance = round(renter_wallet.promotional_credit_balance - credit_to_apply, 2)
        else:
            promotional_credit_used = renter_wallet.promotional_credit_balance
            remainder = round(credit_to_apply - promotional_credit_used, 2)
            renter_wallet.promotional_credit_balance = 0.0
            cash_credit_used = remainder
            renter_wallet.withdrawable_cash_balance = round(renter_wallet.withdrawable_cash_balance - remainder, 2)

        tx_renter = WalletTransaction(
            wallet_id=renter_wallet.id,
            user_id=agreement.renter_id,
            agreement_id=agreement.id,
            transaction_type="rental_payment",
            balance_type="promotional_credit" if promotional_credit_used > 0 else "withdrawable_cash",
            amount=-credit_to_apply,
            description=f"Applied ${credit_to_apply:.2f} credit to rental (Agr #{agreement.id})",
            created_at=datetime.utcnow()
        )
        db.add(tx_renter)

    # 5. Owner Earnings Calculation (10% platform commission on base rent)
    # Net owner earnings = base_rent * 0.90
    net_owner_earning = round(agreement.base_rent * 0.90, 2)
    owner_wallet = get_or_create_user_wallet(agreement.owner_id, db)

    # Origin Tracking:
    # If the base rent was paid via promotional credit, owner receives promotional (non-withdrawable) credit.
    # If paid via external cash, owner receives withdrawable cash.
    # If promotional credit was used towards this rental, net owner earnings derived from bonus are non-withdrawable
    if promotional_credit_used > 0:
        # As specified: earnings funded by promotional bonus credits are non-withdrawable promotional credits
        owner_bonus_earning = net_owner_earning
        owner_cash_earning = 0.0
    else:
        owner_bonus_earning = 0.0
        owner_cash_earning = net_owner_earning

    if owner_bonus_earning > 0:
        owner_wallet.promotional_credit_balance = round(owner_wallet.promotional_credit_balance + owner_bonus_earning, 2)
        tx_owner_bonus = WalletTransaction(
            wallet_id=owner_wallet.id,
            user_id=agreement.owner_id,
            agreement_id=agreement.id,
            transaction_type="owner_earning",
            balance_type="promotional_credit",
            amount=owner_bonus_earning,
            description=f"Rental earnings (Agr #{agreement.id}) - Promotional Credit (Non-Withdrawable)",
            created_at=datetime.utcnow()
        )
        db.add(tx_owner_bonus)

    if owner_cash_earning > 0:
        owner_wallet.withdrawable_cash_balance = round(owner_wallet.withdrawable_cash_balance + owner_cash_earning, 2)
        tx_owner_cash = WalletTransaction(
            wallet_id=owner_wallet.id,
            user_id=agreement.owner_id,
            agreement_id=agreement.id,
            transaction_type="owner_earning",
            balance_type="withdrawable_cash",
            amount=owner_cash_earning,
            description=f"Rental earnings (Agr #{agreement.id}) - Withdrawable Cash",
            created_at=datetime.utcnow()
        )
        db.add(tx_owner_cash)

    # 6. Generate secure Transaction Reference and 4-digit Handover Verification PIN
    txn_code = f"TXN-{random.randint(10000000, 99999999)}"
    handover_pin = f"{random.randint(1000, 9999)}"

    # 7. Record Payment Transaction
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
        credit_applied=credit_to_apply,
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
            "original_security_deposit": agr.original_security_deposit,
            "deposit_discount_pct": agr.deposit_discount_pct,
            "deposit_evaluation_reason": agr.deposit_evaluation_reason,
            "deposit_adjusted_by_owner": agr.deposit_adjusted_by_owner,
            "owner_adjustment_notes": agr.owner_adjustment_notes,
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





# ---------------------------------------------------------------------------
# Module 18: Dispute & Damage Claims Management
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Module 19: In-App Real-Time Messaging & Chat Between Owners and Renters
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Module 20: Push / SMS / Email Notification Engine for Rental Milestones
# ---------------------------------------------------------------------------

def dispatch_notification(
    db: Session,
    user: User,
    event_type: str,
    title: str,
    message: str,
    channels: Optional[List[str]] = None,
    metadata_json: Optional[dict] = None
) -> List[NotificationEvent]:
    if not channels:
        channels = ["push", "sms", "email"]

    created_events = []
    for ch in channels:
        dest = user.email if ch == "email" else (user.phone if ch == "sms" else f"device_push_{user.id:04d}")
        notif = NotificationEvent(
            user_id=user.id,
            channel=ch,
            event_type=event_type,
            title=title,
            message=message,
            destination=dest,
            status="delivered",
            metadata_json=metadata_json or {},
            is_read=False,
            created_at=datetime.utcnow()
        )
        db.add(notif)
        created_events.append(notif)
        print(f"[NOTIFICATION DISPATCH ENGINE] [{ch.upper()}] Destination: {dest} | Type: {event_type} | {title} - {message}")

    db.commit()
    return created_events

@app.post("/api/notifications/dispatch-test", response_model=NotificationEventResponse)
def dispatch_test_notification(payload: NotificationDispatchTestRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == payload.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    events = dispatch_notification(
        db=db,
        user=user,
        event_type=payload.event_type,
        title=payload.title,
        message=payload.message,
        channels=[payload.channel],
        metadata_json=payload.metadata_json
    )
    e = events[0]
    return NotificationEventResponse(
        id=e.id,
        user_id=e.user_id,
        channel=e.channel,
        event_type=e.event_type,
        title=e.title,
        message=e.message,
        destination=e.destination,
        status=e.status,
        metadata_json=e.metadata_json,
        is_read=e.is_read,
        created_at=e.created_at
    )

@app.get("/api/notifications/{user_id}", response_model=NotificationSummaryResponse)
def get_user_notifications(user_id: int, unread_only: bool = False, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    query = db.query(NotificationEvent).filter(NotificationEvent.user_id == user_id)
    if unread_only:
        query = query.filter(NotificationEvent.is_read == False)

    notifications = query.order_by(NotificationEvent.created_at.desc()).all()
    unread_count = db.query(NotificationEvent).filter(
        NotificationEvent.user_id == user_id,
        NotificationEvent.is_read == False
    ).count()

    results = []
    for n in notifications:
        results.append(NotificationEventResponse(
            id=n.id,
            user_id=n.user_id,
            channel=n.channel,
            event_type=n.event_type,
            title=n.title,
            message=n.message,
            destination=n.destination,
            status=n.status,
            metadata_json=n.metadata_json,
            is_read=n.is_read,
            created_at=n.created_at
        ))

    return NotificationSummaryResponse(
        user_id=user_id,
        total_notifications=len(results),
        unread_count=unread_count,
        notifications=results
    )

@app.put("/api/notifications/{notification_id}/read")
def mark_notification_as_read(notification_id: int, db: Session = Depends(get_db)):
    notif = db.query(NotificationEvent).filter(NotificationEvent.id == notification_id).first()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found.")
    notif.is_read = True
    db.commit()
    return {"message": "Notification marked as read.", "id": notification_id}

@app.put("/api/notifications/read-all/{user_id}")
def mark_all_user_notifications_as_read(user_id: int, db: Session = Depends(get_db)):
    db.query(NotificationEvent).filter(
        NotificationEvent.user_id == user_id,
        NotificationEvent.is_read == False
    ).update({"is_read": True})
    db.commit()
    return {"message": "All notifications marked as read.", "user_id": user_id}


@app.post("/api/chat/messages", response_model=ChatMessageResponse)
def send_chat_message(payload: ChatMessageSendRequest, db: Session = Depends(get_db)):
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == payload.agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")

    if payload.sender_id not in [agreement.renter_id, agreement.owner_id]:
        raise HTTPException(status_code=403, detail="Unauthorized: Only agreement parties can participate in chat.")

    receiver_id = agreement.owner_id if payload.sender_id == agreement.renter_id else agreement.renter_id
    sender = db.query(User).filter(User.id == payload.sender_id).first()
    receiver = db.query(User).filter(User.id == receiver_id).first()

    msg = ChatMessage(
        agreement_id=payload.agreement_id,
        sender_id=payload.sender_id,
        receiver_id=receiver_id,
        message_text=payload.message_text.strip(),
        attachment_url=payload.attachment_url,
        is_read=False,
        created_at=datetime.utcnow()
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return ChatMessageResponse(
        id=msg.id,
        agreement_id=msg.agreement_id,
        sender_id=msg.sender_id,
        sender_name=f"{sender.first_name} {sender.last_name}",
        receiver_id=msg.receiver_id,
        receiver_name=f"{receiver.first_name} {receiver.last_name}",
        message_text=msg.message_text,
        attachment_url=msg.attachment_url,
        is_read=msg.is_read,
        created_at=msg.created_at
    )

@app.get("/api/chat/messages/{agreement_id}", response_model=List[ChatMessageResponse])
def get_chat_thread_messages(agreement_id: int, user_id: int, mark_as_read: bool = True, db: Session = Depends(get_db)):
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")

    if user_id not in [agreement.renter_id, agreement.owner_id]:
        raise HTTPException(status_code=403, detail="Unauthorized: Only agreement parties can view messages.")

    messages = db.query(ChatMessage).filter(ChatMessage.agreement_id == agreement_id).order_by(ChatMessage.created_at.asc()).all()

    # Mark incoming messages as read
    if mark_as_read:
        for m in messages:
            if m.receiver_id == user_id and not m.is_read:
                m.is_read = True
        db.commit()

    results = []
    for m in messages:
        results.append(ChatMessageResponse(
            id=m.id,
            agreement_id=m.agreement_id,
            sender_id=m.sender_id,
            sender_name=f"{m.sender.first_name} {m.sender.last_name}" if m.sender else "Sender",
            receiver_id=m.receiver_id,
            receiver_name=f"{m.receiver.first_name} {m.receiver.last_name}" if m.receiver else "Receiver",
            message_text=m.message_text,
            attachment_url=m.attachment_url,
            is_read=m.is_read,
            created_at=m.created_at
        ))
    return results

@app.get("/api/chat/threads/{user_id}", response_model=List[ChatThreadSummary])
def get_user_chat_threads(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    agreements = db.query(RentalAgreement).filter(
        (RentalAgreement.renter_id == user_id) | (RentalAgreement.owner_id == user_id)
    ).order_by(RentalAgreement.id.desc()).all()

    threads = []
    for agr in agreements:
        other_party_id = agr.owner_id if user_id == agr.renter_id else agr.renter_id
        other_party = db.query(User).filter(User.id == other_party_id).first()
        other_name = f"{other_party.first_name} {other_party.last_name}" if other_party else "User"

        # Fetch last message
        last_msg = db.query(ChatMessage).filter(
            ChatMessage.agreement_id == agr.id
        ).order_by(ChatMessage.created_at.desc()).first()

        # Count unread messages for this user
        unread_count = db.query(ChatMessage).filter(
            ChatMessage.agreement_id == agr.id,
            ChatMessage.receiver_id == user_id,
            ChatMessage.is_read == False
        ).count()

        threads.append(ChatThreadSummary(
            agreement_id=agr.id,
            agreement_code=f"AGR-{agr.id:05d}",
            item_title=agr.item.title if agr.item else "Rental Item",
            other_party_id=other_party_id,
            other_party_name=other_name,
            last_message=last_msg.message_text if last_msg else None,
            last_message_time=last_msg.created_at if last_msg else None,
            unread_count=unread_count
        ))

    return threads


@app.post("/api/disputes", response_model=DisputeClaimResponse)
def file_dispute_claim(payload: DisputeClaimCreateRequest, db: Session = Depends(get_db)):
    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == payload.agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")

    claimant = db.query(User).filter(User.id == payload.claimant_id).first()
    if not claimant:
        raise HTTPException(status_code=404, detail="Claimant not found.")

    if payload.claimant_id not in [agreement.renter_id, agreement.owner_id]:
        raise HTTPException(status_code=403, detail="Only parties to the rental agreement can file a dispute.")

    respondent_id = agreement.owner_id if payload.claimant_id == agreement.renter_id else agreement.renter_id
    respondent = db.query(User).filter(User.id == respondent_id).first()

    if payload.requested_amount <= 0:
        raise HTTPException(status_code=400, detail="Requested claim amount must be greater than $0.00.")

    # Freeze any active security deposit hold on this agreement
    deposit_hold = db.query(PaymentTransaction).filter(
        PaymentTransaction.agreement_id == agreement.id
    ).first()

    if deposit_hold:
        deposit_hold.payment_status = "disputed_freeze"

    claim = DisputeClaim(
        agreement_id=payload.agreement_id,
        claimant_id=payload.claimant_id,
        respondent_id=respondent_id,
        claim_type=payload.claim_type,
        requested_amount=round(payload.requested_amount, 2),
        status="open",
        claimant_description=payload.claimant_description,
        photos=payload.photos or [],
        respondent_photos=[],
        created_at=datetime.utcnow()
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    return DisputeClaimResponse(
        id=claim.id,
        agreement_id=claim.agreement_id,
        claimant_id=claim.claimant_id,
        claimant_name=f"{claimant.first_name} {claimant.last_name}",
        respondent_id=claim.respondent_id,
        respondent_name=f"{respondent.first_name} {respondent.last_name}",
        claim_type=claim.claim_type,
        requested_amount=claim.requested_amount,
        status=claim.status,
        claimant_description=claim.claimant_description,
        respondent_response=claim.respondent_response,
        photos=claim.photos or [],
        respondent_photos=claim.respondent_photos or [],
        admin_notes=claim.admin_notes,
        settled_amount_to_owner=claim.settled_amount_to_owner,
        settled_amount_refunded_to_renter=claim.settled_amount_refunded_to_renter,
        created_at=claim.created_at,
        resolved_at=claim.resolved_at
    )

@app.get("/api/disputes/agreement/{agreement_id}", response_model=List[DisputeClaimResponse])
def get_disputes_for_agreement(agreement_id: int, db: Session = Depends(get_db)):
    claims = db.query(DisputeClaim).filter(DisputeClaim.agreement_id == agreement_id).order_by(DisputeClaim.created_at.desc()).all()
    results = []
    for c in claims:
        results.append(DisputeClaimResponse(
            id=c.id,
            agreement_id=c.agreement_id,
            claimant_id=c.claimant_id,
            claimant_name=f"{c.claimant.first_name} {c.claimant.last_name}" if c.claimant else "Claimant",
            respondent_id=c.respondent_id,
            respondent_name=f"{c.respondent.first_name} {c.respondent.last_name}" if c.respondent else "Respondent",
            claim_type=c.claim_type,
            requested_amount=c.requested_amount,
            status=c.status,
            claimant_description=c.claimant_description,
            respondent_response=c.respondent_response,
            photos=c.photos or [],
            respondent_photos=c.respondent_photos or [],
            admin_notes=c.admin_notes,
            settled_amount_to_owner=c.settled_amount_to_owner,
            settled_amount_refunded_to_renter=c.settled_amount_refunded_to_renter,
            created_at=c.created_at,
            resolved_at=c.resolved_at
        ))
    return results

@app.get("/api/disputes/{claim_id}", response_model=DisputeClaimResponse)
def get_dispute_by_id(claim_id: int, db: Session = Depends(get_db)):
    c = db.query(DisputeClaim).filter(DisputeClaim.id == claim_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Dispute claim not found.")

    return DisputeClaimResponse(
        id=c.id,
        agreement_id=c.agreement_id,
        claimant_id=c.claimant_id,
        claimant_name=f"{c.claimant.first_name} {c.claimant.last_name}" if c.claimant else "Claimant",
        respondent_id=c.respondent_id,
        respondent_name=f"{c.respondent.first_name} {c.respondent.last_name}" if c.respondent else "Respondent",
        claim_type=c.claim_type,
        requested_amount=c.requested_amount,
        status=c.status,
        claimant_description=c.claimant_description,
        respondent_response=c.respondent_response,
        photos=c.photos or [],
        respondent_photos=c.respondent_photos or [],
        admin_notes=c.admin_notes,
        settled_amount_to_owner=c.settled_amount_to_owner,
        settled_amount_refunded_to_renter=c.settled_amount_refunded_to_renter,
        created_at=c.created_at,
        resolved_at=c.resolved_at
    )

@app.post("/api/disputes/{claim_id}/respond", response_model=DisputeClaimResponse)
def respond_to_dispute(claim_id: int, payload: DisputeResponseRequest, db: Session = Depends(get_db)):
    claim = db.query(DisputeClaim).filter(DisputeClaim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Dispute claim not found.")

    if payload.respondent_id != claim.respondent_id:
        raise HTTPException(status_code=403, detail="Only the designated respondent can submit a rebuttal.")

    claim.respondent_response = payload.respondent_response
    if payload.photos:
        current_photos = list(claim.respondent_photos or [])
        current_photos.extend(payload.photos)
        claim.respondent_photos = current_photos

    claim.status = "under_review"
    db.commit()
    db.refresh(claim)

    return DisputeClaimResponse(
        id=claim.id,
        agreement_id=claim.agreement_id,
        claimant_id=claim.claimant_id,
        claimant_name=f"{claim.claimant.first_name} {claim.claimant.last_name}" if claim.claimant else "Claimant",
        respondent_id=claim.respondent_id,
        respondent_name=f"{claim.respondent.first_name} {claim.respondent.last_name}" if claim.respondent else "Respondent",
        claim_type=claim.claim_type,
        requested_amount=claim.requested_amount,
        status=claim.status,
        claimant_description=claim.claimant_description,
        respondent_response=claim.respondent_response,
        photos=claim.photos or [],
        respondent_photos=claim.respondent_photos or [],
        admin_notes=claim.admin_notes,
        settled_amount_to_owner=claim.settled_amount_to_owner,
        settled_amount_refunded_to_renter=claim.settled_amount_refunded_to_renter,
        created_at=claim.created_at,
        resolved_at=claim.resolved_at
    )

@app.get("/api/admin/disputes", response_model=List[DisputeClaimResponse])
def list_all_disputes(status: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(DisputeClaim)
    if status:
        query = query.filter(DisputeClaim.status == status)
    claims = query.order_by(DisputeClaim.created_at.desc()).all()

    results = []
    for c in claims:
        results.append(DisputeClaimResponse(
            id=c.id,
            agreement_id=c.agreement_id,
            claimant_id=c.claimant_id,
            claimant_name=f"{c.claimant.first_name} {c.claimant.last_name}" if c.claimant else "Claimant",
            respondent_id=c.respondent_id,
            respondent_name=f"{c.respondent.first_name} {c.respondent.last_name}" if c.respondent else "Respondent",
            claim_type=c.claim_type,
            requested_amount=c.requested_amount,
            status=c.status,
            claimant_description=c.claimant_description,
            respondent_response=c.respondent_response,
            photos=c.photos or [],
            respondent_photos=c.respondent_photos or [],
            admin_notes=c.admin_notes,
            settled_amount_to_owner=c.settled_amount_to_owner,
            settled_amount_refunded_to_renter=c.settled_amount_refunded_to_renter,
            created_at=c.created_at,
            resolved_at=c.resolved_at
        ))
    return results

@app.post("/api/admin/disputes/{claim_id}/resolve", response_model=DisputeClaimResponse)
def admin_resolve_dispute(claim_id: int, payload: AdminDisputeResolveRequest, db: Session = Depends(get_db)):
    claim = db.query(DisputeClaim).filter(DisputeClaim.id == claim_id).first()
    if not claim:
        raise HTTPException(status_code=404, detail="Dispute claim not found.")

    agreement = db.query(RentalAgreement).filter(RentalAgreement.id == claim.agreement_id).first()
    if not agreement:
        raise HTTPException(status_code=404, detail="Rental agreement not found.")

    deposit_amount = agreement.security_deposit

    deposit_tx = db.query(PaymentTransaction).filter(
        PaymentTransaction.agreement_id == agreement.id
    ).first()

    award_owner = 0.0
    refund_renter = deposit_amount

    if payload.decision in ["approve_full", "approve_partial"]:
        if payload.decision == "approve_full":
            award_owner = min(claim.requested_amount, deposit_amount)
        else:
            award_owner = min(payload.approved_amount_to_owner, deposit_amount)

        refund_renter = max(round(deposit_amount - award_owner, 2), 0.0)
        claim.status = "resolved_approved" if award_owner == claim.requested_amount else "resolved_split"

        # Disburse cash to Owner's wallet for the approved damage amount
        if award_owner > 0:
            owner_wallet = get_or_create_user_wallet(agreement.owner_id, db)
            owner_wallet.withdrawable_cash_balance = round(owner_wallet.withdrawable_cash_balance + award_owner, 2)
            db.add(WalletTransaction(
                wallet_id=owner_wallet.id,
                user_id=agreement.owner_id,
                transaction_type="dispute_payout",
                balance_type="withdrawable_cash",
                amount=award_owner,
                description=f"Dispute claim settlement payout for agreement #{agreement.id} ({claim.claim_type})",
                created_at=datetime.utcnow()
            ))

        # Disburse remainder refund to Renter's wallet
        if refund_renter > 0:
            renter_wallet = get_or_create_user_wallet(agreement.renter_id, db)
            renter_wallet.withdrawable_cash_balance = round(renter_wallet.withdrawable_cash_balance + refund_renter, 2)
            db.add(WalletTransaction(
                wallet_id=renter_wallet.id,
                user_id=agreement.renter_id,
                transaction_type="deposit_refund",
                balance_type="withdrawable_cash",
                amount=refund_renter,
                description=f"Security deposit balance refund after dispute resolution for agreement #{agreement.id}",
                created_at=datetime.utcnow()
            ))

    elif payload.decision == "reject":
        claim.status = "resolved_rejected"
        award_owner = 0.0
        refund_renter = deposit_amount

        # 100% refund of deposit to Renter
        renter_wallet = get_or_create_user_wallet(agreement.renter_id, db)
        renter_wallet.withdrawable_cash_balance = round(renter_wallet.withdrawable_cash_balance + refund_renter, 2)
        db.add(WalletTransaction(
            wallet_id=renter_wallet.id,
            user_id=agreement.renter_id,
            transaction_type="deposit_refund",
            balance_type="withdrawable_cash",
            amount=refund_renter,
            description=f"Full security deposit refund: dispute claim rejected for agreement #{agreement.id}",
            created_at=datetime.utcnow()
        ))

    claim.settled_amount_to_owner = round(award_owner, 2)
    claim.settled_amount_refunded_to_renter = round(refund_renter, 2)
    claim.admin_notes = payload.admin_notes
    claim.resolved_at = datetime.utcnow()

    if deposit_tx:
        deposit_tx.payment_status = f"settled_{claim.status}"

    db.commit()
    db.refresh(claim)

    return DisputeClaimResponse(
        id=claim.id,
        agreement_id=claim.agreement_id,
        claimant_id=claim.claimant_id,
        claimant_name=f"{claim.claimant.first_name} {claim.claimant.last_name}" if claim.claimant else "Claimant",
        respondent_id=claim.respondent_id,
        respondent_name=f"{claim.respondent.first_name} {claim.respondent.last_name}" if claim.respondent else "Respondent",
        claim_type=claim.claim_type,
        requested_amount=claim.requested_amount,
        status=claim.status,
        claimant_description=claim.claimant_description,
        respondent_response=claim.respondent_response,
        photos=claim.photos or [],
        respondent_photos=claim.respondent_photos or [],
        admin_notes=claim.admin_notes,
        settled_amount_to_owner=claim.settled_amount_to_owner,
        settled_amount_refunded_to_renter=claim.settled_amount_refunded_to_renter,
        created_at=claim.created_at,
        resolved_at=claim.resolved_at
    )


@app.get("/api/referrals/my-code/{user_id}", response_model=MyReferralCodeResponse)
def get_user_referral_details(user_id: int, request: Request, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if not user.referral_code:
        user.referral_code = generate_unique_referral_code(user.first_name, db)
        db.commit()
        db.refresh(user)

    config = get_or_create_promotional_config(db)
    ref_bonus = config.referrer_bonus_amount if config.referrer_bonus_amount is not None else 15.0
    inv_bonus = config.invitee_bonus_amount if config.invitee_bonus_amount is not None else 20.0

    # Build shareable link
    base_url = str(request.base_url).rstrip('/')
    share_link = f"{base_url}/login-page?ref={user.referral_code}"

    # Pre-compose multi-channel social links
    share_text = f"Join me on SHARENT! Use my referral code {user.referral_code} to get a ${inv_bonus:.2f} welcome bonus on peer-to-peer equipment rentals."
    encoded_text = urllib.parse.quote(share_text)
    encoded_link = urllib.parse.quote(share_link)

    social_links = {
        "whatsapp": f"https://api.whatsapp.com/send?text={encoded_text}%20{encoded_link}",
        "email": f"mailto:?subject=Get%20${inv_bonus:.2f}%20bonus%20on%20SHARENT&body={encoded_text}%0A%0ASign%20up%20here:%20{encoded_link}",
        "facebook": f"https://www.facebook.com/sharer/sharer.php?u={encoded_link}",
        "twitter": f"https://twitter.com/intent/tweet?text={encoded_text}&url={encoded_link}",
        "copy_text": f"{share_text} {share_link}"
    }

    # Fetch user's referrals sent
    records = db.query(UserReferral).filter(UserReferral.referrer_id == user_id).order_by(UserReferral.created_at.desc()).all()
    referral_items = []
    completed_count = 0
    total_earnings = 0.0

    for r in records:
        if r.status == "completed":
            completed_count += 1
            total_earnings += r.referrer_bonus_amount
        referral_items.append(ReferralItemResponse(
            id=r.id,
            invitee_id=r.invitee_id,
            invitee_name=f"{r.invitee.first_name} {r.invitee.last_name}" if r.invitee else "Invited User",
            invitee_email_masked=mask_contact(r.invitee.email, "email") if r.invitee else "***",
            status=r.status,
            referrer_bonus_amount=r.referrer_bonus_amount,
            invitee_bonus_amount=r.invitee_bonus_amount,
            channel_source=r.channel_source,
            created_at=r.created_at,
            awarded_at=r.awarded_at
        ))

    return MyReferralCodeResponse(
        user_id=user_id,
        referral_code=user.referral_code,
        referral_link=share_link,
        referrer_bonus_amount=ref_bonus,
        invitee_bonus_amount=inv_bonus,
        required_active_items=config.required_active_items,
        total_referrals_sent=len(records),
        completed_referrals=completed_count,
        pending_referrals=len(records) - completed_count,
        total_referral_earnings=round(total_earnings, 2),
        share_links=social_links,
        referrals=referral_items
    )


@app.get("/api/admin/promotions/signup-bonus", response_model=PromotionalProgramConfigResponse)
def get_promotional_program_config(db: Session = Depends(get_db)):
    config = get_or_create_promotional_config(db)
    return PromotionalProgramConfigResponse(
        program_key=config.program_key,
        program_name=config.program_name,
        bonus_amount=config.bonus_amount,
        referrer_bonus_amount=config.referrer_bonus_amount if config.referrer_bonus_amount is not None else 15.0,
        invitee_bonus_amount=config.invitee_bonus_amount if config.invitee_bonus_amount is not None else 20.0,
        required_active_items=config.required_active_items,
        required_active_days=config.required_active_days,
        is_active=config.is_active,
        description=config.description
    )

@app.put("/api/admin/promotions/signup-bonus", response_model=PromotionalProgramConfigResponse)
def update_promotional_program_config(payload: PromotionalProgramConfigRequest, db: Session = Depends(get_db)):
    config = get_or_create_promotional_config(db)
    if payload.bonus_amount is not None:
        if payload.bonus_amount < 0:
            raise HTTPException(status_code=400, detail="Bonus amount cannot be negative.")
        config.bonus_amount = payload.bonus_amount
    if payload.referrer_bonus_amount is not None:
        if payload.referrer_bonus_amount < 0:
            raise HTTPException(status_code=400, detail="Referrer bonus amount cannot be negative.")
        config.referrer_bonus_amount = payload.referrer_bonus_amount
    if payload.invitee_bonus_amount is not None:
        if payload.invitee_bonus_amount < 0:
            raise HTTPException(status_code=400, detail="Invitee bonus amount cannot be negative.")
        config.invitee_bonus_amount = payload.invitee_bonus_amount
    if payload.required_active_items is not None:
        if payload.required_active_items < 0:
            raise HTTPException(status_code=400, detail="Required active items cannot be negative.")
        config.required_active_items = payload.required_active_items
    if payload.required_active_days is not None:
        if payload.required_active_days < 1:
            raise HTTPException(status_code=400, detail="Required active days must be at least 1.")
        config.required_active_days = payload.required_active_days
    if payload.is_active is not None:
        config.is_active = payload.is_active
    if payload.description is not None:
        config.description = payload.description

    db.commit()
    db.refresh(config)
    return PromotionalProgramConfigResponse(
        program_key=config.program_key,
        program_name=config.program_name,
        bonus_amount=config.bonus_amount,
        referrer_bonus_amount=config.referrer_bonus_amount if config.referrer_bonus_amount is not None else 15.0,
        invitee_bonus_amount=config.invitee_bonus_amount if config.invitee_bonus_amount is not None else 20.0,
        required_active_items=config.required_active_items,
        required_active_days=config.required_active_days,
        is_active=config.is_active,
        description=config.description
    )

@app.get("/api/promotions/bonus-progress/{user_id}", response_model=UserBonusProgressResponse)
def get_user_bonus_progress(user_id: int, db: Session = Depends(get_db)):
    config = get_or_create_promotional_config(db)
    tracker = db.query(UserBonusTracker).filter(
        UserBonusTracker.user_id == user_id,
        UserBonusTracker.program_key == config.program_key
    ).first()

    qualifying_items = db.query(Item).filter(
        Item.owner_id == user_id,
        Item.is_available == True,
        Item.active_duration_days >= config.required_active_days
    ).all()
    q_count = len(qualifying_items)

    is_awarded = tracker.bonus_awarded if tracker else False
    awarded_date = tracker.awarded_at if tracker else None

    # Calculate progress
    needed = config.required_active_items
    remaining = max(0, needed - q_count) if not is_awarded else 0
    pct = 100.0 if is_awarded else round(min(100.0, (q_count / needed) * 100.0), 1)

    if is_awarded:
        msg = f"Congratulations! You unlocked your ${config.bonus_amount:.2f} Welcome Bonus by listing {q_count} active items for at least {config.required_active_days} days!"
    else:
        msg = f"List {remaining} more active item{'s' if remaining != 1 else ''} with at least {config.required_active_days} days commitment (3 months) to unlock your ${config.bonus_amount:.2f} bonus."

    return UserBonusProgressResponse(
        user_id=user_id,
        bonus_awarded=is_awarded,
        bonus_amount=config.bonus_amount,
        required_active_items=config.required_active_items,
        required_active_days=config.required_active_days,
        qualifying_items_count=q_count,
        items_remaining=remaining,
        progress_percentage=pct,
        awarded_at=awarded_date,
        status_message=msg
    )


@app.get("/api/wallet/{user_id}", response_model=UserWalletResponse)
def get_user_wallet(user_id: int, db: Session = Depends(get_db)):
    wallet = get_or_create_user_wallet(user_id, db)
    # Evaluate promo bonus (e.g. if required_active_items == 0 or listings met)
    evaluate_user_promotional_bonus(user_id, db)
    db.refresh(wallet)
    txs = db.query(WalletTransaction).filter(WalletTransaction.user_id == user_id).order_by(WalletTransaction.created_at.desc()).all()
    
    tx_list = [
        WalletTransactionResponse(
            id=t.id,
            transaction_type=t.transaction_type,
            balance_type=t.balance_type,
            amount=t.amount,
            payment_channel=t.payment_channel,
            external_reference=t.external_reference,
            description=t.description,
            created_at=t.created_at
        ) for t in txs
    ]

    return UserWalletResponse(
        user_id=user_id,
        total_balance=wallet.total_balance,
        promotional_credit_balance=round(wallet.promotional_credit_balance, 2),
        withdrawable_cash_balance=round(wallet.withdrawable_cash_balance, 2),
        transactions=tx_list
    )



@app.post("/api/wallet/deposit", response_model=WalletDepositResponse)
def deposit_funds(payload: WalletDepositRequest, db: Session = Depends(get_db)):
    wallet = get_or_create_user_wallet(payload.user_id, db)

    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Deposit amount must be greater than $0.00.")

    valid_channels = ["bank_account", "google_pay", "paypal", "venmo"]
    if payload.channel not in valid_channels:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported deposit channel '{payload.channel}'. Supported: {', '.join(valid_channels)}"
        )

    # Channel-specific validation & reference code generation
    channel_prefix_map = {
        "bank_account": "ACH",
        "google_pay": "GPAY",
        "paypal": "PP",
        "venmo": "VENMO"
    }
    prefix = channel_prefix_map.get(payload.channel, "DEP")
    ref_code = f"DEP-{prefix}-{random.randint(100000, 999999)}"

    channel_name_map = {
        "bank_account": "Bank Account (ACH)",
        "google_pay": "Google Pay",
        "paypal": "PayPal",
        "venmo": "Venmo"
    }
    display_channel = channel_name_map.get(payload.channel, payload.channel)
    details_str = f" ({payload.channel_details})" if payload.channel_details else ""
    description = f"Deposit via {display_channel}{details_str} [{ref_code}]"

    # Deposited real money increases withdrawable cash balance
    wallet.withdrawable_cash_balance = round(wallet.withdrawable_cash_balance + payload.amount, 2)

    tx = WalletTransaction(
        wallet_id=wallet.id,
        user_id=payload.user_id,
        transaction_type="deposit",
        balance_type="withdrawable_cash",
        amount=payload.amount,
        payment_channel=payload.channel,
        external_reference=ref_code,
        description=description,
        created_at=datetime.utcnow()
    )
    db.add(tx)
    db.commit()
    db.refresh(wallet)

    return WalletDepositResponse(
        success=True,
        deposit_reference=ref_code,
        amount=payload.amount,
        channel=payload.channel,
        new_total_balance=wallet.total_balance,
        new_cash_balance=wallet.withdrawable_cash_balance,
        message=f"Successfully deposited ${payload.amount:.2f} via {display_channel}! Your wallet has been credited."
    )


@app.post("/api/wallet/withdraw")
def withdraw_funds(payload: WithdrawalRequest, db: Session = Depends(get_db)):
    wallet = get_or_create_user_wallet(payload.user_id, db)
    
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Withdrawal amount must be greater than $0.00.")

    # Check withdrawable cash balance vs promotional bonus
    if payload.amount > wallet.withdrawable_cash_balance:
        if wallet.promotional_credit_balance > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Withdrawal failed. Your available withdrawable cash is ${wallet.withdrawable_cash_balance:.2f}. "
                       f"Your remaining ${wallet.promotional_credit_balance:.2f} balance consists of promotional sign-up bonus credits, "
                       f"which can only be used for renting items on Sharent and cannot be withdrawn to {payload.destination_type.title()}."
            )
        else:
            raise HTTPException(status_code=400, detail="Insufficient withdrawable balance.")

    # Process cash withdrawal
    wallet.withdrawable_cash_balance = round(wallet.withdrawable_cash_balance - payload.amount, 2)
    
    tx = WalletTransaction(
        wallet_id=wallet.id,
        user_id=payload.user_id,
        transaction_type="withdrawal",
        balance_type="withdrawable_cash",
        amount=-payload.amount,
        description=f"Withdrawal to {payload.destination_type.title()} ({payload.destination_account})",
        created_at=datetime.utcnow()
    )
    db.add(tx)
    db.commit()

    return {
        "success": True,
        "message": f"Successfully initiated transfer of ${payload.amount:.2f} to {payload.destination_type.title()} ({payload.destination_account}).",
        "remaining_withdrawable_cash": wallet.withdrawable_cash_balance,
        "total_credit_balance": wallet.total_balance
    }
