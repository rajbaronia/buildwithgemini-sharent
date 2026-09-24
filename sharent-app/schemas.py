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
    active_duration_days: Optional[int] = Field(default=90)

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
    active_duration_days: Optional[int] = 90
    active_duration_days: Optional[int] = 90

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
    active_duration_days: Optional[int] = 90
    total_days: int
    reason: Optional[str] = None
    daily_rate: float
    total_rent: float
    min_days: int
    max_days: int

class ItemStatusToggleRequest(BaseModel):
    owner_id: int
    is_available: bool
    active_duration_days: Optional[int] = 90


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


class CheckoutPaymentRequest(BaseModel):
    agreement_id: int
    renter_id: int
    payment_method: str = 'credit_card'  # credit_card, paypal, venmo, sharent_credit
    card_number: Optional[str] = None
    exp_month: Optional[str] = None
    exp_year: Optional[str] = None
    cvv: Optional[str] = None
    billing_zip: Optional[str] = None
    apply_credit: Optional[bool] = True

class CheckoutPaymentResponse(BaseModel):
    id: int
    transaction_code: str
    credit_applied: Optional[float] = 0.0
    agreement_code: str
    item_title: str
    owner_name: str
    renter_name: str
    start_date: date_type
    end_date: date_type
    total_days: int
    amount_charged: float
    escrow_deposit_held: float
    total_paid: float
    card_last4: str
    payment_status: str
    handover_pin: str
    created_at: datetime


class HandoverVerificationRequest(BaseModel):
    agreement_id: int
    owner_id: int
    entered_pin: str
    pickup_notes: Optional[str] = None

class ReturnInspectionRequest(BaseModel):
    agreement_id: int
    owner_id: int
    condition_on_return: str = 'good'
    all_accessories_returned: bool = True
    cleaned_properly: bool = True
    inspection_notes: Optional[str] = None

class RentalSummaryItem(BaseModel):
    agreement_id: int
    agreement_code: str
    item_id: int
    item_title: str
    renter_id: int
    renter_name: str
    owner_id: int
    owner_name: str
    start_date: date_type
    end_date: date_type
    total_days: int
    total_amount: float
    security_deposit: float
    status: str
    handover_pin: Optional[str] = None
    deposit_refund_status: Optional[str] = None
    deposit_refunded_amount: Optional[float] = None


class CreateReviewRequest(BaseModel):
    agreement_id: int
    reviewer_id: int
    comment: str
    tags: Optional[List[str]] = None
    
    # 1. Item criteria (for Renter)
    item_accuracy: Optional[int] = 5
    item_condition: Optional[int] = 5
    item_ease_of_use: Optional[int] = 5
    item_instructions: Optional[int] = 5
    item_value: Optional[int] = 5

    # 2. Owner criteria (for Renter)
    owner_response_time: Optional[int] = 5
    owner_communication: Optional[int] = 5
    owner_friendliness: Optional[int] = 5
    owner_pickup_ease: Optional[int] = 5
    owner_return_ease: Optional[int] = 5

    # 3. Renter criteria (for Owner)
    renter_communication: Optional[int] = 5
    renter_responsibility: Optional[int] = 5
    renter_friendliness: Optional[int] = 5
    renter_care_of_item: Optional[int] = 5
    renter_return_condition: Optional[int] = 5

class ReviewResponse(BaseModel):
    id: int
    agreement_id: int
    reviewer_name: str
    reviewee_name: str
    role: str
    rating: float
    comment: str
    tags: List[str]
    created_at: datetime
    # Granular scores
    item_accuracy: Optional[int] = None
    item_condition: Optional[int] = None
    item_ease_of_use: Optional[int] = None
    item_instructions: Optional[int] = None
    item_value: Optional[int] = None
    owner_response_time: Optional[int] = None
    owner_communication: Optional[int] = None
    owner_friendliness: Optional[int] = None
    owner_pickup_ease: Optional[int] = None
    owner_return_ease: Optional[int] = None
    renter_communication: Optional[int] = None
    renter_responsibility: Optional[int] = None
    renter_friendliness: Optional[int] = None
    renter_care_of_item: Optional[int] = None
    renter_return_condition: Optional[int] = None

class ItemCriteriaBreakdown(BaseModel):
    accuracy: float
    condition: float
    ease_of_use: float
    instructions: float
    value: float

class ItemReviewSummaryResponse(BaseModel):
    item_id: int
    average_rating: float
    total_reviews: int
    criteria_breakdown: ItemCriteriaBreakdown
    reviews: List[ReviewResponse]


class WalletTransactionResponse(BaseModel):
    id: int
    transaction_type: str
    balance_type: str
    amount: float
    payment_channel: Optional[str] = None
    external_reference: Optional[str] = None
    description: str
    created_at: datetime

class WalletDepositRequest(BaseModel):
    user_id: int
    amount: float
    channel: str  # bank_account, google_pay, paypal, venmo
    channel_details: Optional[str] = None  # e.g., account last4, email, handle

class WalletDepositResponse(BaseModel):
    success: bool
    deposit_reference: str
    amount: float
    channel: str
    new_total_balance: float
    new_cash_balance: float
    message: str

class UserWalletResponse(BaseModel):
    user_id: int
    total_balance: float
    promotional_credit_balance: float  # Non-withdrawable
    withdrawable_cash_balance: float   # Withdrawable
    transactions: List[WalletTransactionResponse] = []

class WithdrawalRequest(BaseModel):
    user_id: int
    amount: float
    destination_type: str  # paypal, bank_transfer, venmo
    destination_account: str


class PromotionalProgramConfigResponse(BaseModel):
    program_key: str
    program_name: str
    bonus_amount: float
    required_active_items: int
    required_active_days: int
    is_active: bool
    description: Optional[str] = None

class PromotionalProgramConfigRequest(BaseModel):
    bonus_amount: Optional[float] = None
    required_active_items: Optional[int] = None
    required_active_days: Optional[int] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None

class UserBonusProgressResponse(BaseModel):
    user_id: int
    bonus_awarded: bool
    bonus_amount: float
    required_active_items: int
    required_active_days: int
    qualifying_items_count: int
    items_remaining: int
    progress_percentage: float
    awarded_at: Optional[datetime] = None
    status_message: str
