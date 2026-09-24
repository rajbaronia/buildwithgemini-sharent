# Sharent: Peer-to-Peer Neighborhood Equipment & Tool Sharing Platform
**Project Architecture, Evolution, Database Schema, and Continuation Manual**

> **Current Repository**: [https://github.com/rajbaronia/buildwithgemini-sharent](https://github.com/rajbaronia/buildwithgemini-sharent)  
> **Platform Version**: 1.0.0 (Modules 1 through 13 Completed)  
> **Language & Frameworks**: Python 3.13, FastAPI, SQLAlchemy ORM, SQLite, Jinja2, TailwindCSS, FontAwesome 6, Pytest

---

## 1. Executive Summary & Problem Mission

### Problem Statement
High-utility equipment, lawn care tools, carpet cleaners, pressure washers, and DIY power tools often sit idle in residential garages for 95% of their lifespan. Simultaneously, neighbors frequently purchase expensive single-use equipment or rent from commercial supply stores located far away, requiring cumbersome logistics, steep fees, and high friction.

### Solution
**Sharent** is a hyper-local, peer-to-peer equipment sharing marketplace enabling neighbors to monetize idle tools safely and rent equipment nearby with zero hassle. Sharent solves the traditional trust barrier through:
- Dual-channel verified user accounts (Email + SMS OTP).
- Transparent fee itemization and escrow security deposit protection.
- Binding digital rental agreements with mandatory safety acknowledgments.
- Contactless/in-person 4-digit Handover PIN verification at pickup.
- Multi-point return inspections with automated 100% escrow refunds.
- **Airbnb-style multi-criteria reviews** evaluating specific quality dimensions for the Item, Owner, and Renter.

---

## 2. Technology Stack & Directory Architecture

```
/config/Desktop/BuildWithGemini/
├── Sharent-Summary.md              # Master project summary (this document)
└── sharent-app/
    ├── main.py                     # FastAPI application endpoints & lifespan handlers
    ├── models.py                   # SQLAlchemy ORM data models
    ├── schemas.py                  # Pydantic request/response schemas
    ├── auth.py                     # Password hashing & OTP dispatch simulation
    ├── database.py                 # SQLite database connection & session setup
    ├── sharent.db                  # Local SQLite database file
    ├── templates/
    │   ├── landing.html            # Marketing landing page & sign-in modal
    │   └── dashboard.html          # Unified Owner/Renter dashboard with role toggle & modals
    ├── static/
    │   └── uploads/                # User-uploaded equipment photos
    ├── test_*.py                   # 12 comprehensive Pytest test suites (100% pass)
    └── .venv/                      # Python virtual environment
```

---

## 3. Database Schema Overview

```
users
├── id (Integer, PK)
├── first_name, last_name, username, email, phone, address
├── password_hash
├── is_email_verified, is_phone_verified
├── active_role ("owner" | "renter")
└── created_at

otp_verifications
├── id (Integer, PK)
├── user_id (FK -> users.id)
├── channel ("email" | "phone")
├── otp_code (6-digit random code)
├── expires_at, is_used, created_at

items
├── id (Integer, PK)
├── owner_id (FK -> users.id)
├── title, category, condition, description, location_city
├── base_rate_daily, security_deposit, item_value
├── min_rental_days, max_rental_days
├── deposit_required, insurance_required
├── manual_url, youtube_tutorial_url
├── is_active (Boolean: True = visible in catalog, False = hidden)
└── created_at

item_images
├── id (Integer, PK)
├── item_id (FK -> items.id)
├── image_url, is_primary
└── created_at

item_availability
├── id (Integer, PK)
├── item_id (FK -> items.id)
├── date (Date)
├── status ("available" | "booked" | "maintenance")
└── created_at

rental_agreements
├── id (Integer, PK)
├── agreement_code (e.g. "AGR-12345678")
├── item_id (FK -> items.id)
├── renter_id (FK -> users.id)
├── owner_id (FK -> users.id)
├── start_date, end_date (Date)
├── total_days (Integer)
├── daily_rate, base_rental_fee, platform_fee, insurance_fee, security_deposit, grand_total (Float)
├── accepted_terms, accepted_deposit_policy, accepted_safety_rules (Boolean)
├── agreed_at (DateTime)
└── status ("pending_payment" | "confirmed" | "active" | "completed" | "cancelled")

payment_transactions
├── id (Integer, PK)
├── agreement_id (FK -> rental_agreements.id)
├── renter_id (FK -> users.id)
├── transaction_code (e.g. "TXN-87654321")
├── payment_method ("credit_card")
├── card_last4 ("4242")
├── amount_charged, escrow_deposit_held, total_paid (Float)
├── handover_pin (4-digit random string, e.g. "7482")
├── payment_status ("paid_escrow_held" | "deposit_refunded")
└── created_at

rental_handover_inspections
├── id (Integer, PK)
├── agreement_id (FK -> rental_agreements.id)
├── pickup_verified_at (DateTime)
├── pickup_notes (Text)
├── return_verified_at (DateTime)
├── condition_on_return ("like_new" | "good" | "damaged")
├── all_accessories_returned, cleaned_properly (Boolean)
├── deposit_refund_status ("refunded_100_percent" | "dispute_held")
├── deposit_refunded_amount (Float)
└── inspection_notes (Text)

rental_reviews (Airbnb-Style Multi-Criteria)
├── id (Integer, PK)
├── agreement_id (FK -> rental_agreements.id)
├── reviewer_id (FK -> users.id)
├── reviewee_id (FK -> users.id)
├── item_id (FK -> items.id, nullable)
├── role ("renter_to_owner" | "owner_to_renter")
├── rating (Float: exact mathematical average of attributes)
├── comment (Text)
├── tags (Comma-separated compliment badges)
├── created_at (DateTime)
│   # 1. Item Rating Attributes (Rated by Renter)
├── item_accuracy (1 to 5)
├── item_condition (1 to 5)
├── item_ease_of_use (1 to 5)
├── item_instructions (1 to 5)
├── item_value (1 to 5)
│   # 2. Owner Rating Attributes (Rated by Renter)
├── owner_response_time (1 to 5)
├── owner_communication (1 to 5)
├── owner_friendliness (1 to 5)
├── owner_pickup_ease (1 to 5)
├── owner_return_ease (1 to 5)
│   # 3. Renter Rating Attributes (Rated by Owner)
├── renter_communication (1 to 5)
├── renter_responsibility (1 to 5)
├── renter_friendliness (1 to 5)
├── renter_care_of_item (1 to 5)
└── renter_return_condition (1 to 5)
```

---

## 4. Module-by-Module Evolution

### Module 1: Dual-Channel User Registration & OTP Verification
- Registration collects: first/last name, username, email, phone, address, and password.
- Two simulated OTP codes (6 digits) sent to email and SMS phone number.
- Registration complete only when both channels are verified (`is_email_verified=True` and `is_phone_verified=True`).

### Module 2: Secure Two-Factor Authentication (2FA) Login
- Renders dual-channel 2FA login verification modal.
- Protects unauthorized account takeovers.

### Module 3: Dynamic Owner ⇄ Renter Role Switching
- Single user account can switch between **Owner Mode** and **Renter Mode** with 1 click.
- Persistent in database (`users.active_role`).
- Owner view displays Inventory Management; Renter view displays Equipment Catalog.

### Module 4: Advanced Item Listing with Photo Upload & YouTube/Manual Links
- Item creation modal with drag-and-drop / file upload for multiple equipment photos.
- Stores photos in `/static/uploads/`.
- Fields for operating manual PDF links and YouTube video tutorial URLs.
- Video tutorial embedded directly into the Item Detail modal.

### Module 5: Interactive Availability Calendar & Booking Prevention
- Airbnb-style interactive calendar per item.
- Visual date indicators: Available (green), Booked (amber/red), Maintenance (gray).
- Prevents double-booking and locks past dates.

### Module 6: Listing Show/Hide Marketplace Toggle
- Toggle switch in Owner Inventory allows owners to activate/deactivate listings with 1 click.
- Deactivated items stay visible in Owner's Inventory but are hidden from Renters in the catalog.

### Module 7: Transparent Renter Charges Itemization & Fee Breakdown
- Endpoint `POST /api/items/{item_id}/quote` returning itemized billing:
  - Base Daily Rent (`rate * days`)
  - Platform Service Fee (`5% + $1.00`)
  - Equipment Insurance (`8%`)
  - Refundable Security Deposit Escrow
  - Grand Total Due
- Quote modal with formatted currency breakdown.

### Module 8: Rental Agreement Terms & Conditions (Mandatory Acknowledgment)
- Database model `RentalAgreement` capturing contract snapshot.
- Modal `#agreement-modal` with 5 legal clauses.
- Enforces 3 mandatory checkboxes:
  1. Safety compliance, PPE, and operational manual adherence.
  2. Security deposit return policy.
  3. Master P2P Terms & Conditions acceptance.
- Action button remains locked until all 3 are checked.

### Module 9: Payment Processing & Escrow Hold Simulation
- Database model `PaymentTransaction`.
- Endpoint `POST /api/checkout/pay` processing simulated card transactions (with sandbox helper `4242...` and `0000` decline simulation).
- Holds security deposit in escrow.
- Locks calendar dates in `item_availability` to `booked`.
- Generates a random 4-digit Handover Verification PIN.
- Modal `#checkout-modal` and digital receipt modal `#receipt-modal`.

### Module 10: In-Person Handover PIN Verification & Return Inspection Checklist
- **Pickup Verification**: Owner clicks `Verify Handover`, enters the Renter's 4-digit PIN, and records initial condition notes. Status transitions to `active`.
- **Return Inspection Checklist**: Owner inspects physical condition (`Like New`, `Good`, or `Damaged`), verifies all accessories/cables, and confirms cleanliness.
- **Automated Escrow Refund**: Submitting the inspection checklist immediately releases the **100% Security Deposit Escrow** back to the Renter and marks status `completed`.

### Module 11–13: Airbnb-Style Granular Multi-Attribute Rating System
- Specific rating dimensions evaluating each party in the rental transaction:
  - **Item Criteria (Rated by Renter)**:
    1. *Accuracy* (Listing description, specs & photos match actual item)
    2. *Working Condition* (Functional, well maintained, and clean)
    3. *Ease of Use* (Intuitive to operate and configure)
    4. *Operating Instructions* (Provided manuals, guides, or video links)
    5. *Value for Money* (Fair daily rental rate for the utility received)
  - **Owner Criteria (Rated by Renter)**:
    1. *Response Time* (Promptness in answering inquiries)
    2. *Clear Communications* (Clarity of pickup and coordination instructions)
    3. *Friendliness* (Professionalism, courtesy, and warmth)
    4. *Ease of Pick-up Process* (Smoothness of physical handover)
    5. *Ease of Return Process* (Simplicity and speed of deposit release)
  - **Renter Criteria (Rated by Owner)**:
    1. *Communication* (Promptness, responsiveness, and clarity)
    2. *Responsible* (Punctuality, reliability, agreement adherence)
    3. *Friendliness* (Respectful and polite conduct)
    4. *Takes Good Care of the Item* (Handled equipment with appropriate caution)
    5. *Returned the Item in Good Condition* (Clean, complete, all parts/accessories intact)
- **UI Implementation**:
  - Modal `#review-modal` dynamically displays role-specific criteria dropdowns with live rating labels and compliment tag chips.
  - Item detail modal `#detail-modal` displays an **Airbnb-style criteria progress bar grid** with average score bars for all 5 Item dimensions alongside verified renter reviews!
  - Duplicate review prevention (1 review per party per agreement).

---

### Module 14: Promotional Sign-Up Bonus, Split Fee Payments & Non-Withdrawable Credit Accounting
- **Automatic $20.00 Welcome Promotional Credit**:
  - Automatically credited to each newly registered and dual-verified user's wallet.
  - Automatically initialized for existing active members.
- **Credit Applicability Restrictions**:
  - Promotional credits **can** be applied toward:
    1. **Usage Fee (Base Rent)**
    2. **Platform Service Fee**
  - Promotional credits **cannot** be applied toward:
    1. **Security Deposit (Escrow)**
    2. **Insurance Fee**
- **Strict Non-Withdrawable Policy**:
  - Promotional credits and net earnings originating from promotional credits cannot be withdrawn to external bank accounts, PayPal, or Venmo.
  - Any payout withdrawal attempt against promotional credits is blocked with an informative restriction message.
- **Dual-Balance Ledger Architecture (`UserWallet` & `WalletTransaction`)**:
  - `promotional_credit_balance`: Non-withdrawable balance derived from sign-up promotions and bonus-funded rentals.
  - `withdrawable_cash_balance`: Real withdrawable earnings generated from cash/card transactions.
  - Full audit trail logging of transactions: `signup_bonus`, `rental_payment`, `owner_earning`, and `withdrawal`.
- **Origin/Taint Tracking for Owner Net Earnings**:
  - When a renter pays for equipment using promotional credit, the net owner earnings (after the 10% platform commission) are credited as promotional credit (non-withdrawable).
- **Interactive UI**:
  - Header credit chip displaying live balance (`Credits: $XX.XX`).
  - Dedicated Wallet & Payout modal with credit vs. cash breakdown, audit history, and cash withdrawal form.
  - Checkout summary automatically reflects credits applied against eligible rental & service fees.

### Module 15: Multi-Channel Wallet Deposits, Balance Overview & Transaction History
- **Multi-Channel Deposit Support**:
  - Connect external financial accounts and services to deposit funds directly into the user's Sharent Wallet:
    1. **Bank Account (ACH / Direct Debit)**: Routing number + account number authorization.
    2. **Google Pay**: Instant 1-tap biometric/token payment.
    3. **PayPal**: Linked PayPal account/email authentication.
    4. **Venmo**: Linked Venmo account/@handle integration.
- **Deposit Fund Classification (Real Cash Balance)**:
  - Deposited funds represent genuine real-money payments and are credited to **`withdrawable_cash_balance`**.
  - Unlike promotional sign-up bonuses, deposited cash can be applied towards all checkout charges (including **Security Deposit** and **Insurance Fee**), or withdrawn back to external bank/PayPal/Venmo accounts.
- **Comprehensive Account Balance Overview**:
  - **Total Balance**: Combined spending power across all available funds.
  - **Withdrawable Cash Balance**: Real cash from external deposits and verified cash rental earnings.
  - **Promotional Bonus Credits**: Non-withdrawable credits for usage & service fees only.
- **Full Audit Ledger & Filterable Transaction History**:
  - Audit trail displaying chronological records of all wallet movements: deposits, sign-up promotions, rental payments, owner net earnings, and cash payouts.
  - Interactive filter pills to view *All*, *Deposits*, *Payments*, and *Earnings*.
  - Reference tracking tags (e.g. `DEP-GPAY-XXXXXX`, `DEP-ACH-XXXXXX`, `DEP-PP-XXXXXX`, `DEP-VENMO-XXXXXX`).

### Module 16: Conditional Sign-Up Bonus Program (Inventory Listing & Active Duration Requirements with Dynamic Platform Configuration)
- **Goal-Oriented Sign-Up Bonus Program**:
  - Rather than granting promotional credits immediately upon registration, credits are unlocked only when the user satisfies marketplace supply onboarding prerequisites.
  - **Prerequisite Condition**:
    1. List at least **10 new Items** into their inventory.
    2. Maintain them as **Active** (`is_available = True`) with a commitment duration of at least **3 months (90 days)**.
- **Dynamic Platform Configuration (`PromotionalProgramConfig`)**:
  - Prerequisite conditions are fully parameterized platform variables that SHARENT administrators can change over time without redeployment:
    - `bonus_amount` (default: **$20.00**)
    - `required_active_items` (default: **10 items**)
    - `required_active_days` (default: **90 days / 3 months**)
    - `is_active` (toggleable program status)
- **Administrative APIs & Dynamic Threshold Tuning**:
  - `GET /api/admin/promotions/signup-bonus`: Returns current promotion rules, bonus amount, item requirement, and duration threshold.
  - `PUT /api/admin/promotions/signup-bonus`: Dynamically adjust bonus amount, required items, or active days in real time.
- **User Bonus Qualification Tracker & Auto-Credit**:
  - `GET /api/promotions/bonus-progress/{user_id}`: Real-time progress tracker reporting items listed, items remaining, completion percentage, and unlock status.
  - Automatic evaluation triggers when items are created or toggled active/inactive.
  - Once the threshold is met, the bonus is automatically unlocked and credited to the user's `UserWallet.promotional_credit_balance` with a verifiable audit transaction.
- **Milestone Progress UI**:
  - Interactive milestone tracker card with gradient progress bar in the Sharent Wallet Modal and inventory dashboard showing real-time progress toward unlocking the sign-up bonus.

### Module 17: Multi-Channel Social Referral Program with Dynamic Dual-Sided Incentives
- **Viral Referral Engine & Dual-Sided Incentives**:
  - Existing users (referrers) are incentivized to invite friends through multi-channel social sharing.
  - When the invitee successfully registers using the referral code and lists the required active items, a **dual reward** is triggered:
    1. **Invitee (New User)** receives their **Sign-Up Bonus** (Module 16).
    2. **Referrer (Existing User)** receives a **Referral Bonus** credited directly into their Sharent Wallet.
- **Unique Referral Code Generation**:
  - Every registered user automatically receives a branded unique referral code (e.g. `REF-ALIC-A1B2C3`).
  - Shareable link format: `http://localhost:8000/login-page?ref=REF-ALIC-A1B2C3`.
- **Multi-Channel Social Sharing Integration**:
  - Pre-composed instant sharing links for:
    - 💬 **WhatsApp**: Pre-formatted text with code and clickable registration link.
    - ✉️ **Email**: Mailto link with custom subject line and body.
    - 📘 **Facebook**: Direct sharing dialog link.
    - ✖️ **Twitter / X**: Pre-composed tweet with hashtags and invite URL.
    - 📋 **1-Click Copy Code & Direct Invite Link**.
- **Dynamic Platform Configuration (`PromotionalProgramConfig`)**:
  - Variable incentive parameters controlled dynamically via admin APIs:
    - `referrer_bonus_amount` (default: **$15.00**)
    - `invitee_bonus_amount` (default: **$20.00**)
    - `required_active_items` (default: **10 items**)
    - `required_active_days` (default: **90 days / 3 months**)
- **Referral Lifecycle & Automated Unlock (`UserReferral`)**:
  - Tracks referral state: `pending` (invitee registered) -> `completed` (invitee met listing milestone).
  - Automatically credits the referrer's wallet with a `referral_bonus` audit transaction the moment the invitee lists the 10th qualifying item.
- **Interactive UI & Real-Time Referral Dashboard**:
  - Added **"Invite & Earn $15"** navigation button and full modal with live counters (*Friends Invited*, *Pending Listings*, *Total Earned*), and an activity feed of invited friends.
  - Added **Referral Code (Optional)** input in registration form with auto-fill from `?ref=...` URL parameter.

### Module 18: Dispute & Damage Claims Management
- **Structured Dispute & Damage Claim Architecture**:
  - Allows either party (Owner or Renter) to file a formal dispute claim during or after return inspection.
  - Supports granular claim categorization: Physical Item Damage, Missing Parts/Accessories, Late Return, Not Working/Defective, or Other Violations.
  - Captures claim requested amount, detailed narrative, and photographic evidence URLs.
- **Deposit Escrow Freezing**:
  - Automatically flags and freezes the rental's security deposit transaction (`PaymentTransaction.payment_status = "disputed_freeze"`), preventing automatic release while adjudication is ongoing.
- **Respondent Rebuttal Workflow**:
  - Designated respondent can submit a formal response/rebuttal along with their own counter-evidence photos (`POST /api/disputes/{claim_id}/respond`), transitioning claim status to `under_review`.
- **Administrative Adjudication & Automated Disbursals (`POST /api/admin/disputes/{claim_id}/resolve`)**:
  - Full, partial, or split settlements:
    - **Approved damage settlement** is automatically credited as withdrawable cash to the Owner's wallet with audit type `dispute_payout`.
    - **Remaining deposit balance** is automatically refunded as withdrawable cash to the Renter's wallet with audit type `deposit_refund`.
    - **Rejection** releases 100% of the deposit back to the Renter's wallet.
- **Interactive UI & Dispute Modal**:
  - Styled modal on the dashboard with category selectors, claim amount validation, narrative descriptions, and photo evidence URL inputs.

### Module 19: In-App Real-Time Messaging & Chat Between Owners and Renters
- **Scoped Rental Agreement Chat Architecture**:
  - Encapsulated direct coordination thread for each rental transaction between Owner and Renter.
  - Strict security access controls: only verified parties to the specific rental agreement are authorized to send or read messages (`403 Forbidden` on unauthorized access).
- **Core Chat Capabilities**:
  - Real-time message exchange (`POST /api/chat/messages`) supporting formatted text and optional image/file attachment URLs.
  - Automated delivery and read receipts (`is_read: true/false`).
  - Thread summary and unread badge counters (`GET /api/chat/threads/{user_id}`).
  - Conversation feed retrieval with automated unread-to-read state transitions (`GET /api/chat/messages/{agreement_id}?user_id={user_id}`).
- **Interactive Chat Modal & Live Polling UI**:
  - Modal with real-time 3-second live polling feed in `dashboard.html`.
  - Distinguishes outgoing messages (green right-aligned bubble with timestamp and read receipt status) from incoming messages (white left-aligned bubble with sender name).

## 5. Automated Testing Suite

All 12 Pytest test suites are passing with 100% success rate:

```bash
cd /config/Desktop/BuildWithGemini/sharent-app
.venv/bin/pytest -v
```

1. `test_reviews.py` — Airbnb-style multi-attribute rating criteria & calculation.
2. `test_handover_and_return.py` — Pickup PIN verification, return checklist & escrow refund.
3. `test_payment_checkout.py` — Payment processing, escrow deposit hold & auto-booking.
4. `test_rental_agreement.py` — Terms agreement generation & mandatory checkbox enforcement.
5. `test_quote_api.py` — Rental quote breakdown & fee calculation math.
6. `test_item_activation_toggle.py` — Owner show/hide toggle for marketplace listings.
7. `test_calendar_availability.py` — Calendar date selection & conflict validation.
8. `test_item_listing_advanced.py` — Photo upload, YouTube embeds & manual URL links.
9. `test_roles_and_items.py` — Role switching between Owner and Renter modes.
10. `test_login.py` — 2FA login verification & credential checking.
11. `test_registration.py` (2 tests) — User registration & dual-channel OTP validation.

---

## 13. `test_wallet_and_bonus.py`:
    - Validates the exact multi-user scenario (User A, B, and C):
      - User A ($20 bonus), User B ($20 bonus), User C ($20 bonus).
      - User C rents User A's electric drill ($10/day) using promotional credit.
      - User A receives net $9 ($10 - 10%), increasing User A's balance to $29.
      - User A rents User B's kayak ($15/day for 2 days = $30). User A applies all $29 credit + $1 PayPal.
      - User B receives net $27 ($30 - 10%), increasing User B's balance to $47.
      - User B attempts to withdraw $47 to PayPal, which is strictly rejected due to non-withdrawable promotional credit rules.

14. `test_wallet_deposits.py`:
    - Tests multi-channel wallet deposits across Bank Account (ACH), Google Pay, PayPal, and Venmo.
    - Validates deposit reference codes, instant credit to `withdrawable_cash_balance`, and updated `total_balance`.
    - Confirms rejection of invalid amounts (<= 0) and unsupported channels.
    - Validates withdrawing deposited funds back out to external accounts while enforcing non-withdrawable limits on promotional credits.

15. `test_conditional_signup_bonus.py`:
    - Tests the conditional sign-up bonus lifecycle: 0 items listed ($0 balance) -> 9 items listed ($0 balance) -> 10th item listed with < 90 days commitment ($0 balance) -> 10th item listed with 90-day active commitment (automatically unlocks $20.00 bonus credit).
    - Tests dynamic platform variable updates via `PUT /api/admin/promotions/signup-bonus` (updating requirement to 3 items and $35.00 bonus).
    - Verifies another user qualifying under the dynamically updated thresholds.

16. `test_referral_bonus.py`:
    - Tests unique referral code generation and multi-channel social links (WhatsApp, Email, Facebook, Twitter).
    - Verifies invitee registration linking and pending referral tracking.
    - Tests incremental listing: 1 to 9 items keeps referral pending; 10th qualifying item triggers dual bonus payout (Invitee gets $20 sign-up bonus, Referrer automatically receives $15 referral bonus).
    - Tests dynamic administrative threshold adjustment ($25 referrer bonus, $30 invitee bonus, 2 items threshold) and subsequent qualification.

17. `test_dispute_claims.py`:
    - Tests complete rental checkout and escrow deposit hold ($100).
    - Verifies dispute claim filing with photographic damage evidence, freezing escrow hold to `disputed_freeze`.
    - Tests respondent rebuttal submission and status transition to `under_review`.
    - Tests administrative split resolution: $50 damage settlement awarded to Owner, $50 deposit balance refunded to Renter.
    - Validates exact accounting in both wallets and wallet transaction audit ledger entries.

18. `test_chat_messaging.py`:
    - Tests registration and agreement creation between Owner and Renter.
    - Tests sending coordination messages and verifying sender/receiver metadata and initial unread status.
    - Validates thread summaries with live unread badge counting.
    - Tests reading conversation messages and automated unread-to-read transition.
    - Verifies reply dispatch with image attachments.
    - Rigorously validates 403 authorization checks preventing unauthorized 3rd-party snooping or messaging.

## 6. How to Run Locally

```bash
cd /config/Desktop/BuildWithGemini/sharent-app
# Start the FastAPI server
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

- **Landing & Registration**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Bob's Dashboard (Renter)**: [http://127.0.0.1:8000/dashboard/1](http://127.0.0.1:8000/dashboard/1)
- **Alice's Dashboard (Owner)**: [http://127.0.0.1:8000/dashboard/2](http://127.0.0.1:8000/dashboard/2)
- **Interactive Swagger API Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 7. Recommended Next Steps

1. **In-App Messaging & Real-Time Chat (Module 14)**:
   - Direct messaging between Renter and Owner before and during the rental period.
   - Coordinate exact pickup address and exchange questions about equipment usage.
2. **Geo-Location & Map View (Module 15)**:
   - Interactive map (Leaflet / Google Maps) showing equipment availability by neighborhood radius (e.g. within 2 miles, 5 miles, 10 miles).
3. **Cloud Production Deployment (Module 16)**:
   - Containerize via Dockerfile.
   - Deploy to **Google Cloud Run** with a managed **Cloud SQL PostgreSQL** database.
