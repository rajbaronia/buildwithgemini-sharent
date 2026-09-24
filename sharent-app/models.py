from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import json

DATABASE_URL = "sqlite:///./sharent.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    first_name = Column(String(50), nullable=False)
    last_name = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    address = Column(String(255), nullable=False)
    username = Column(String(30), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    
    is_email_verified = Column(Boolean, default=False)
    is_phone_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def is_fully_verified(self) -> bool:
        return self.is_email_verified and self.is_phone_verified


class OTPVerification(Base):
    __tablename__ = "otp_verifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    channel = Column(String(10), nullable=False)  # "email" or "phone"
    destination = Column(String(100), nullable=False)
    otp_code = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="otps")


class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(120), nullable=False)
    category = Column(String(50), nullable=False)
    description = Column(Text, nullable=False)
    condition = Column(String(30), default="Good")
    base_rate_daily = Column(Float, nullable=False)
    base_rate_hourly = Column(Float, nullable=True)
    security_deposit = Column(Float, nullable=False)
    item_value = Column(Float, nullable=False)
    
    # Module 4 additions
    min_rental_days = Column(Integer, default=1, nullable=False)
    max_rental_days = Column(Integer, default=30, nullable=False)
    deposit_required = Column(Boolean, default=True)
    insurance_required = Column(Boolean, default=False)
    images_json = Column(Text, default="[]")  # JSON string array of image URLs
    manual_url = Column(String(500), nullable=True)
    brochure_url = Column(String(500), nullable=True)
    video_url = Column(String(500), nullable=True)

    location_city = Column(String(80), default="San Ramon, CA")
    is_available = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", backref="items")

    @property
    def images(self) -> list:
        try:
            return json.loads(self.images_json) if self.images_json else []
        except Exception:
            return []

    @images.setter
    def images(self, img_list: list):
        self.images_json = json.dumps(img_list)


def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

init_db()

from sqlalchemy import Date

class ItemAvailability(Base):
    __tablename__ = "item_availabilities"

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    date = Column(Date, nullable=False, index=True)
    status = Column(String(20), default="blocked", nullable=False)  # "blocked", "booked"
    reason = Column(String(100), nullable=True)  # "Owner Personal Use", "Maintenance", "Rental Booking"
    created_at = Column(DateTime, default=datetime.utcnow)

    item = relationship("Item", backref="availabilities")

Base.metadata.create_all(bind=engine)


class RentalAgreement(Base):
    __tablename__ = 'rental_agreements'

    id = Column(Integer, primary_key=True, index=True)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=False)
    renter_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    owner_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    total_days = Column(Integer, nullable=False)
    daily_rate = Column(Float, nullable=False)
    base_rent = Column(Float, nullable=False)
    security_deposit = Column(Float, nullable=False)
    service_fee = Column(Float, nullable=False)
    insurance_fee = Column(Float, default=0.0)
    total_amount = Column(Float, nullable=False)
    terms_version = Column(String, default='v1.0')
    agreed_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default='pending_payment')  # pending_payment, active, completed, cancelled

    item = relationship('Item')
    renter = relationship('User', foreign_keys=[renter_id])
    owner = relationship('User', foreign_keys=[owner_id])


class PaymentTransaction(Base):
    __tablename__ = 'payment_transactions'

    id = Column(Integer, primary_key=True, index=True)
    agreement_id = Column(Integer, ForeignKey('rental_agreements.id'), nullable=False)
    renter_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    transaction_code = Column(String, unique=True, index=True, nullable=False)
    payment_method = Column(String, default='credit_card')
    card_last4 = Column(String, default='4242')
    amount_charged = Column(Float, nullable=False)
    escrow_deposit_held = Column(Float, nullable=False)
    total_paid = Column(Float, nullable=False)
    payment_status = Column(String, default='succeeded')  # succeeded, escrow_held, refunded
    handover_pin = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    agreement = relationship('RentalAgreement')
    renter = relationship('User')


class RentalHandoverInspection(Base):
    __tablename__ = 'rental_handover_inspections'

    id = Column(Integer, primary_key=True, index=True)
    agreement_id = Column(Integer, ForeignKey('rental_agreements.id'), unique=True, nullable=False)
    pickup_verified_at = Column(DateTime, nullable=True)
    pickup_notes = Column(String, nullable=True)
    return_verified_at = Column(DateTime, nullable=True)
    condition_on_return = Column(String, nullable=True)  # like_new, good, damaged
    all_accessories_returned = Column(Boolean, default=True)
    cleaned_properly = Column(Boolean, default=True)
    deposit_refund_status = Column(String, default='pending')  # pending, released, held_dispute
    deposit_refunded_amount = Column(Float, default=0.0)
    inspection_notes = Column(String, nullable=True)

    agreement = relationship('RentalAgreement')


class RentalReview(Base):
    __tablename__ = 'rental_reviews'

    id = Column(Integer, primary_key=True, index=True)
    agreement_id = Column(Integer, ForeignKey('rental_agreements.id'), nullable=False)
    reviewer_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    reviewee_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('items.id'), nullable=True)
    role = Column(String, nullable=False)  # renter_to_owner, owner_to_renter
    rating = Column(Float, nullable=False)  # 1.0 to 5.0 (calculated average of criteria)
    comment = Column(String, nullable=False)
    tags = Column(String, nullable=True)  # comma separated
    created_at = Column(DateTime, default=datetime.utcnow)

    # 1. Item Rating Attributes (Rated by Renter)
    item_accuracy = Column(Integer, nullable=True)          # 1 to 5
    item_condition = Column(Integer, nullable=True)         # 1 to 5
    item_ease_of_use = Column(Integer, nullable=True)       # 1 to 5
    item_instructions = Column(Integer, nullable=True)      # 1 to 5
    item_value = Column(Integer, nullable=True)             # 1 to 5

    # 2. Owner Rating Attributes (Rated by Renter)
    owner_response_time = Column(Integer, nullable=True)    # 1 to 5
    owner_communication = Column(Integer, nullable=True)    # 1 to 5
    owner_friendliness = Column(Integer, nullable=True)     # 1 to 5
    owner_pickup_ease = Column(Integer, nullable=True)      # 1 to 5
    owner_return_ease = Column(Integer, nullable=True)      # 1 to 5

    # 3. Renter Rating Attributes (Rated by Owner)
    renter_communication = Column(Integer, nullable=True)   # 1 to 5
    renter_responsibility = Column(Integer, nullable=True)  # 1 to 5
    renter_friendliness = Column(Integer, nullable=True)    # 1 to 5
    renter_care_of_item = Column(Integer, nullable=True)    # 1 to 5
    renter_return_condition = Column(Integer, nullable=True)# 1 to 5

    agreement = relationship('RentalAgreement')
    reviewer = relationship('User', foreign_keys=[reviewer_id])
    reviewee = relationship('User', foreign_keys=[reviewee_id])
    item = relationship('Item')


class UserWallet(Base):
    __tablename__ = 'user_wallets'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    promotional_credit_balance = Column(Float, default=20.0)  # Non-withdrawable promotional credit
    withdrawable_cash_balance = Column(Float, default=0.0)    # Withdrawable real cash earnings
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship('User')

    @property
    def total_balance(self) -> float:
        return round((self.promotional_credit_balance or 0.0) + (self.withdrawable_cash_balance or 0.0), 2)


class WalletTransaction(Base):
    __tablename__ = 'wallet_transactions'

    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey('user_wallets.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    agreement_id = Column(Integer, ForeignKey('rental_agreements.id'), nullable=True)
    transaction_type = Column(String, nullable=False)  # signup_bonus, rental_payment, owner_earning, withdrawal
    balance_type = Column(String, nullable=False)      # promotional_credit, withdrawable_cash
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    wallet = relationship('UserWallet')
    user = relationship('User')
    agreement = relationship('RentalAgreement')
