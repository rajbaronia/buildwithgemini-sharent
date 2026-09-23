import secrets
import string
import hashlib
from datetime import datetime, timedelta
import bcrypt
from sqlalchemy.orm import Session
from models import OTPVerification, User

OTP_EXPIRY_MINUTES = 10

def hash_password(password: str) -> str:
    # Use standard bcrypt directly with bytes
    pwd_bytes = password.encode('utf-8')[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        pwd_bytes = plain_password.encode('utf-8')[:72]
        return bcrypt.checkpw(pwd_bytes, hashed_password.encode('utf-8'))
    except Exception:
        return False

def generate_otp_code(length: int = 6) -> str:
    """Generate a random numeric code."""
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length))

def create_and_send_otp(db: Session, user: User, channel: str) -> dict:
    """
    Creates an OTP in the database and simulates sending via SMS/Email.
    Returns the generated OTP record info.
    """
    destination = user.email if channel == "email" else user.phone
    
    # Invalidate previous unused OTPs for this user & channel
    db.query(OTPVerification).filter(
        OTPVerification.user_id == user.id,
        OTPVerification.channel == channel,
        OTPVerification.is_used == False
    ).update({"is_used": True})
    
    code = generate_otp_code(6)
    expires_at = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)
    
    otp_record = OTPVerification(
        user_id=user.id,
        channel=channel,
        destination=destination,
        otp_code=code,
        expires_at=expires_at,
        is_used=False
    )
    db.add(otp_record)
    db.commit()
    db.refresh(otp_record)

    # In a production environment, dispatch via Twilio / SendGrid / Firebase Auth here.
    print(f"\n[DISPATCH SIMULATOR] [{channel.upper()}] Sent OTP to {destination}: >>> {code} <<<\n")
    
    return {
        "channel": channel,
        "destination": destination,
        "code": code,
        "expires_at": expires_at.isoformat()
    }

def verify_otp_code(db: Session, user_or_id, channel: str, code: str) -> bool:
    user_id = user_or_id.id if hasattr(user_or_id, "id") else int(user_or_id)
    now = datetime.utcnow()
    record = db.query(OTPVerification).filter(
        OTPVerification.user_id == user_id,
        OTPVerification.channel == channel,
        OTPVerification.otp_code == code.strip(),
        OTPVerification.is_used == False,
        OTPVerification.expires_at > now
    ).first()
    
    if not record:
        return False
    
    record.is_used = True
    db.commit()
    return True

def mask_contact(destination: str, channel: str) -> str:
    if channel == "email":
        parts = destination.split("@")
        if len(parts) == 2:
            name, domain = parts
            masked_name = name[0] + "***" + name[-1] if len(name) > 2 else name[0] + "***"
            return f"{masked_name}@{domain}"
    elif channel == "phone":
        clean = destination.strip()
        if len(clean) >= 4:
            return clean[:-4] + "****" + clean[-2:]
    return destination
