import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGODB_URL = os.getenv("MONGODB_URL", "")
def _parse_admin_ids():
    raw = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "0"))
    return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

ADMIN_IDS = _parse_admin_ids()
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else 0

def _channel_url(username: str) -> str:
    u = username.lstrip("@")
    return f"https://t.me/{u}" if u else ""

CHANNELS = [
    {
        "id": os.getenv("CHANNEL_1", ""),
        "username": os.getenv("CHANNEL_USERNAME_1", ""),
        "url": _channel_url(os.getenv("CHANNEL_USERNAME_1", "")),
    },
    {
        "id": os.getenv("CHANNEL_2", ""),
        "username": os.getenv("CHANNEL_USERNAME_2", ""),
        "url": _channel_url(os.getenv("CHANNEL_USERNAME_2", "")),
    },
    {
        "id": "-1003040686190",
        "username": "",
        "url": "https://t.me/+_diGJbgVkeQzNzFl",
    },
    {
        "id": "-1003105822518",
        "username": "",
        "url": "https://t.me/+OnJsUcXtvoRkMjg9",
    },
]

UPI_ID = os.getenv("UPI_ID", "BHARATPE.8B0L1T2H8C56136@fbpe")
QR_CODE_FILE = "qr.png"

VERIFY_API_KEY = os.getenv("VERIFY_API_KEY", "aalu_live_c99ce45d8606417a957b").strip()
VERIFY_MERCHANT_ID = os.getenv("VERIFY_MERCHANT_ID", "BHARATPE.8B0L1T2H8C56136@fbpe").strip()

PAYMENT_MAX_TRIES = 5
DEPOSIT_PRESETS = [50, 100, 200, 500, 1000]

DEFAULT_OTP_PRICE = 5.0
DEFAULT_REFERRAL_PERCENT = 5.0
DEFAULT_WAIT_TIME = 5
DEFAULT_CANCEL_TIME = 2

SERVICE_NAME = "Premium OTP"
BOT_USERNAME = "OtpServiceBot"
SUPPORT_USERNAME = "@OtpServiceX"
