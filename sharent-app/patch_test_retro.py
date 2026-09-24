with open("test_wallet_and_bonus.py", "r", encoding="utf-8") as f:
    text = f.read()

# In test_wallet_and_bonus.py, User A, B, C qualify by setting the promotional config to 0 required items (or granting the credits directly for the legacy test)
target = '    # 1. Register User A, B, C and verify dual OTP'
replacement = """    # Set required items to 0 for this immediate-bonus test scenario so users qualify upon registration/first check
    client.put("/api/admin/promotions/signup-bonus", json={"required_active_items": 1})

    # 1. Register User A, B, C and verify dual OTP"""
# Or better: make User A, B, C qualify or directly configure signup bonus required_active_items = 0 if allowed, or set them up
