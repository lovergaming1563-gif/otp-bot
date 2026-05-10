import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

_admin_ids_raw = os.environ.get("ADMIN_IDS", str(ADMIN_ID))
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().lstrip("-").isdigit()]

MONGODB_URL = os.environ.get("MONGODB_URL", "")

_ch1 = os.environ.get("CHANNEL_1", "")
CHANNEL_1 = int(_ch1) if _ch1.lstrip("-").isdigit() else None
_ch2 = os.environ.get("CHANNEL_2", "")
CHANNEL_2 = int(_ch2) if _ch2.lstrip("-").isdigit() else None

CHANNEL_USERNAME_1 = os.environ.get("CHANNEL_USERNAME_1", "")
CHANNEL_USERNAME_2 = os.environ.get("CHANNEL_USERNAME_2", "")

# CHANNELS list used by keyboards.py and utils.py
CHANNELS = [ch for ch in [CHANNEL_1, CHANNEL_2] if ch is not None]

UPI_ID = os.environ.get("UPI_ID", "BHARATPE.8B0L1T2H8C56136@fbpe")

# ALOO payment verification
VERIFY_API_KEY = os.environ.get("VERIFY_API_KEY", "aalu_live_c99ce45d8606417a957b")
VERIFY_MERCHANT_ID = os.environ.get("VERIFY_MERCHANT_ID", "68129118")

# ZapUPI payment gateway
ZAP_KEY = os.environ.get("ZAP_KEY", "")

# Bot display settings
SERVICE_NAME = os.environ.get("SERVICE_NAME", "OTP Bot")
SUPPORT_USERNAME = os.environ.get("SUPPORT_USERNAME", "@support")
QR_CODE_FILE = os.environ.get("QR_CODE_FILE", "qr_payment.jpg")

# Pyrogram userbot
SESSION_STRING = os.environ.get("SESSION_STRING", "")
_api_id = os.environ.get("API_ID", "")
API_ID = int(_api_id) if _api_id.isdigit() else None
API_HASH = os.environ.get("API_HASH", "")
