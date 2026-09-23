from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator
from typing import Optional, List

class UserRegisterRequest(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=50)
    last_name: str = Field(..., min_length=1, max_length=50)
    email: EmailStr
    phone: str = Field(..., min_length=7, max_length=20)
    address: str = Field(..., min_length=3, max_length=255)
    username: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=6, max_length=128)

class OTPVerifyRequest(BaseModel):
    user_id: int
    channel: str = Field(..., pattern="^(email|phone)$")
    otp_code: str = Field(..., min_length=6, max_length=6)

class ResendOTPRequest(BaseModel):
    user_id: int
    channel: str = Field(..., pattern="^(email|phone)$")

class UserLoginRequest(BaseModel):
    username: str
    password: str

class LoginInitiateRequest(BaseModel):
    username: str
    password: str
    preferred_channel: str = Field(..., pattern="^(email|phone)$")

class LoginVerifyOTPRequest(BaseModel):
    user_id: int
    channel: str = Field(..., pattern="^(email|phone)$")
    otp_code: str = Field(..., min_length=6, max_length=6)

class RoleSwitchRequest(BaseModel):
    user_id: int
    role: str = Field(..., pattern="^(owner|renter)$")

class ItemCreateRequest(BaseModel):
    owner_id: int
    title: str = Field(..., min_length=2, max_length=120)
    category: str = Field(..., min_length=2, max_length=50)
    description: str = Field(..., min_length=5)
    condition: str = Field(default="Good", max_length=30)
    base_rate_daily: float = Field(..., gt=0)
    base_rate_hourly: Optional[float] = Field(default=None, gt=0)
    security_deposit: float = Field(..., ge=0)
    item_value: float = Field(..., gt=0)
    
    # Module 4 fields
    min_rental_days: int = Field(default=1, ge=1)
    max_rental_days: int = Field(default=30, ge=1)
    deposit_required: bool = True
    insurance_required: bool = False
    images: List[str] = Field(default_factory=list)
    manual_url: Optional[str] = None
    brochure_url: Optional[str] = None
    video_url: Optional[str] = None
    location_city: str = Field(default="San Ramon, CA")

    @model_validator(mode="after")
    def check_duration_range(self):
        if self.min_rental_days > self.max_rental_days:
            raise ValueError("Minimum rental duration cannot exceed maximum rental duration.")
        return self

class ItemResponse(BaseModel):
    id: int
    owner_id: int
    owner_name: Optional[str] = None
    title: str
    category: str
    description: str
    condition: str
    base_rate_daily: float
    base_rate_hourly: Optional[float]
    security_deposit: float
    item_value: float
    min_rental_days: int
    max_rental_days: int
    deposit_required: bool
    insurance_required: bool
    images: List[str]
    manual_url: Optional[str] = None
    brochure_url: Optional[str] = None
    video_url: Optional[str] = None
    location_city: str
    is_available: bool

    model_config = ConfigDict(from_attributes=True)

class UserProfileResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: str
    phone: str
    address: str
    username: str
    is_email_verified: bool
    is_phone_verified: bool
    is_fully_verified: bool

    model_config = ConfigDict(from_attributes=True)
from datetime import date as date_type

class ItemAvailabilityItem(BaseModel):
    id: int
    item_id: int
    date: date_type
    status: str
    reason: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class DateBlockToggleRequest(BaseModel):
    owner_id: int
    date: date_type
    status: str = Field(default="blocked", pattern="^(blocked|available)$")
    reason: Optional[str] = "Owner Personal Use"

class CalendarRangeCheckRequest(BaseModel):
    start_date: date_type
    end_date: date_type

class CalendarRangeCheckResponse(BaseModel):
    is_available: bool
    total_days: int
    reason: Optional[str] = None
    daily_rate: float
    total_rent: float
    min_days: int
    max_days: int

class ItemStatusToggleRequest(BaseModel):
    owner_id: int
    is_available: bool


class RentalQuoteResponse(BaseModel):
    item_id: int
    item_title: str
    owner_name: str
    start_date: date_type
    end_date: date_type
    total_days: int
    daily_rate: float
    base_rent: float
    security_deposit: float
    insurance_fee: float
    insurance_required: bool
    service_fee_fixed: float
    service_fee_pct: float
    service_fee_total: float
    total_due_now: float
    refundable_deposit_portion: float


class RentalAgreementCreateRequest(BaseModel):
    item_id: int
    renter_id: int
    start_date: date_type
    end_date: date_type
    accepted_terms: bool
    accepted_deposit_policy: bool
    accepted_safety_rules: bool

class RentalAgreementResponse(BaseModel):
    id: int
    agreement_code: str
    item_id: int
    item_title: str
    owner_name: str
    renter_name: str
    start_date: date_type
    end_date: date_type
    total_days: int
    daily_rate: float
    base_rent: float
    security_deposit: float
    service_fee: float
    insurance_fee: float
    total_amount: float
    terms_version: str
    agreed_at: datetime
    status: str
