from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from models import RentalAgreement, RentalReview, DisputeClaim, Item

def evaluate_renter_deposit_tier(item: Item, renter_id: Optional[int], db: Session) -> Dict[str, Any]:
    """
    Evaluates the security deposit required from a Renter based on Owner discretion:
    1. Trusted Repeat Renter: 100% waiver ($0 deposit) if Renter has prior completed rentals
       with this Owner without disputes.
    2. Highly Rated Community Renter: 50% discount if Renter has positive reviews (avg >= 4.5).
    3. New / Unreviewed Renter: Standard 100% full deposit.
    """
    base_deposit = round(float(item.security_deposit or 0.0), 2)
    
    if not renter_id or base_deposit <= 0.0:
        return {
            "tier_status": "standard_full",
            "original_security_deposit": base_deposit,
            "security_deposit": base_deposit,
            "deposit_discount_pct": 0.0,
            "evaluation_reason": "Standard deposit required." if base_deposit > 0 else "No security deposit required."
        }

    # 1. Check for Repeat Transactions with this Specific Owner
    completed_with_owner = db.query(RentalAgreement).filter(
        RentalAgreement.renter_id == renter_id,
        RentalAgreement.owner_id == item.owner_id,
        RentalAgreement.status == "completed"
    ).all()

    if completed_with_owner:
        agreement_ids = [a.id for a in completed_with_owner]
        dispute_count = db.query(DisputeClaim).filter(
            DisputeClaim.agreement_id.in_(agreement_ids),
            DisputeClaim.status != "dismissed"
        ).count()

        if dispute_count == 0:
            count = len(completed_with_owner)
            return {
                "tier_status": "waived",
                "original_security_deposit": base_deposit,
                "security_deposit": 0.0,
                "deposit_discount_pct": 100.0,
                "evaluation_reason": f"Security Deposit 100% Waived! Trusted Renter with {count} prior satisfactory rental(s) with this Owner."
            }

    # 2. Check Community Reviews (Rated by Owners)
    reviews = db.query(RentalReview).filter(
        RentalReview.reviewee_id == renter_id,
        RentalReview.role == "owner_to_renter"
    ).all()

    if reviews:
        avg_rating = sum(r.rating for r in reviews) / len(reviews)
        if avg_rating >= 4.5:
            discounted_deposit = round(base_deposit * 0.5, 2)
            return {
                "tier_status": "reduced_half",
                "original_security_deposit": base_deposit,
                "security_deposit": discounted_deposit,
                "deposit_discount_pct": 50.0,
                "evaluation_reason": f"50% Deposit Reduction Applied! Highly rated community renter ({avg_rating:.1f}★ across {len(reviews)} review(s))."
            }

    # 3. New User or Insufficient Reviews
    return {
        "tier_status": "standard_full",
        "original_security_deposit": base_deposit,
        "security_deposit": base_deposit,
        "deposit_discount_pct": 0.0,
        "evaluation_reason": "Standard full deposit required for new user without established review history."
    }
