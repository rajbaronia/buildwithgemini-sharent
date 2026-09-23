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
