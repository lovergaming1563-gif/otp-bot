import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))

_admin_ids_raw = os.environ.get("ADMIN_IDS", str(ADMIN_ID))
ADMIN_IDS = [int(x.strip()) for x in _admin_ids_raw.split(",") if x.strip().lstrip("-").isdigit()]

MONGODB_URL = os.environ.get("MONGODB_URL", "")

# Channel IDs for private channels (set these as env vars on your server)
_ch1_id = os.environ.get("CHANNEL_1_ID", "")
_ch2_id = os.environ.get("CHANNEL_2_ID", "")
CHANNELS = [
    {
        "id": int(_ch1_id) if _ch1_id.lstrip("-").isdigit() else None,
        "username": "",
        "url": "https://t.me/+dwOX61hgVdUzYTE1",
        "name": "Channel 1"
    },
    {
        "id": int(_ch2_id) if _ch2_id.lstrip("-").isdigit() else None,
        "username": "",
        "url": "https://t.me/+OnJsUcXtvoRkMjg9",
        "name": "Channel 2"
    },
    {
        "id": None,
        "username": "@withoutanyinvestmentwork",
        "url": "https://t.me/withoutanyinvestmentwork",
        "name": "Channel 3"
    },
    {
        "id": None,
        "username": "@OtpServiceXOfficial",
        "url": "https://t.me/OtpServiceXOfficial",
        "name": "Channel 4"
    },
]
# The most important channel — user is force-checked on every interaction
IMPORTANT_CHANNEL_USERNAME = "@withoutanyinvestmentwork"
IMPORTANT_CHANNEL_URL = "https://t.me/withoutanyinvestmentwork"

UPI_ID = os.environ.get("UPI_ID", "BHARATPE.8B0L1T2H8C56136@fbpe")



# ZapUPI (Rocket) payment
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
