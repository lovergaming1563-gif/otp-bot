import datetime
from telegram import Bot
from telegram.error import TelegramError
from config import CHANNELS


async def check_channel_membership(bot: Bot, user_id: int) -> bool:
    for channel in CHANNELS:
        username = channel.get("username", "")
        channel_id = channel.get("id", "")
        chat_id = username if username else channel_id
        if not chat_id:
            continue
        try:
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except TelegramError:
            continue
    return True


def format_balance(amount: float) -> str:
    return f"₹{amount:.2f}"


def time_elapsed(start_time: datetime.datetime) -> float:
    now = datetime.datetime.utcnow()
    return (now - start_time).total_seconds() / 60


def time_remaining(start_time: datetime.datetime, total_minutes: int) -> float:
    elapsed = time_elapsed(start_time)
    return max(0, total_minutes - elapsed)


def extract_otp_from_message(text: str) -> str:
    import re
    patterns = [
        r'\b\d{6}\b',
        r'\b\d{4}\b',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def is_myntra_message(text: str) -> bool:
    keywords = ["myntra", "otp", "verification", "code", "verify"]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)
