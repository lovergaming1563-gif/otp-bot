"""
AUTO MODE — OTP Group Listener
================================
The bot must be a member of the OTP source group.
Incoming messages are parsed for Myntra OTPs.
Device ID is extracted from the message text.
Matched to active sessions → OTP sent clean to user.
"""

import re
import logging
from telegram import Update
from telegram.ext import ContextTypes
from database import (
    get_session_by_device, update_session_status,
    deduct_balance, delete_number_from_stock, add_log,
    get_mode, get_settings, get_otp_group_id, get_all_active_sessions,
    get_active_service_keywords, get_services, get_service_price,
    get_service_otp_digits, record_otp_digit_usage, get_otp_digit_stats
)

from keyboards import main_menu_keyboard
from config import SERVICE_NAME
import time

# In-memory cooldown: avoid spamming admin with digit mismatch alerts
# key: service_name → last alert timestamp (unix)
_digit_alert_cooldown: dict = {}
_DIGIT_ALERT_COOLDOWN_SECS = 600  # notify at most once per 10 min per service

logger = logging.getLogger(__name__)

OTP_KEYWORDS = ["otp", "verification code", "one time password", "one-time password"]


async def detect_message_service(text: str) -> str | None:
    """
    Detect which active service this OTP message belongs to.
    Checks keywords against BOTH the full message text AND the extracted sender name
    (so 'bigbsk', 'bb-cart' etc. match even if the SMS body doesn't say 'bigbasket').
    Returns service name or None.
    """
    text_lower = text.lower()
    has_otp_kw = any(kw in text_lower for kw in OTP_KEYWORDS)
    has_code = bool(re.search(r'\b\d{4,8}\b', text))
    snippet = text_lower[:120].replace("\n", " | ")
    logger.info(f"[DETECT] msg='{snippet}' has_otp_kw={has_otp_kw} has_code={has_code}")
    if not (has_otp_kw or has_code):
        logger.info("[DETECT] REJECT: no otp keyword and no 4-8 digit code")
        return None

    # Build a combined search string: full text + extracted sender (if any)
    sender = _extract_sender_from_text(text)
    search_text = text_lower
    if sender:
        search_text = text_lower + " " + sender.lower()
        logger.info(f"[DETECT] sender extracted: '{sender}' — adding to keyword search")

    services = await get_services()
    active_names = [s["name"] for s in services if s.get("active")]
    logger.info(f"[DETECT] active services: {active_names}")
    for s in services:
        if not s.get("active"):
            continue
        kws = [kw.lower() for kw in s.get("keywords", [])]
        matched = [kw for kw in kws if kw in search_text]
        if matched:
            logger.info(f"[DETECT] MATCH service='{s['name']}' via keyword(s)={matched}")
            return s["name"]
        else:
            logger.info(f"[DETECT] no match for '{s['name']}' (keywords tried={kws})")
    logger.info("[DETECT] REJECT: no service keyword matched")
    return None


async def is_active_service_message(text: str) -> bool:
    """Check if the message belongs to any active service (dynamic from DB)."""
    service = await detect_message_service(text)
    return service is not None


def is_myntra_otp_message(text: str) -> bool:
    """Legacy sync check — kept for userbot.py compatibility (fallback only)."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in ["myntra", "myntra.com"]) and \
           any(kw in text_lower for kw in OTP_KEYWORDS)


def extract_otp_code(text: str, allowed_digits: list = None) -> str | None:
    """
    Extract OTP from text.
    allowed_digits: list of int digit-lengths to try, e.g. [4, 5, 6].
    Tries longest first so more specific codes are preferred.
    Default: [6, 5, 4] — accepts any 4/5/6 digit OTP.
    """
    if allowed_digits is None:
        allowed_digits = [6, 5, 4]
    else:
        allowed_digits = sorted(set(int(d) for d in allowed_digits), reverse=True)

    # Remove [#...] message reference tags before parsing (e.g. [#myntra-abc123])
    clean = re.sub(r'\[#[^\]]*\]', '', text)

    for digit_len in allowed_digits:
        pattern = r'\b(\d{' + str(digit_len) + r'})\b'
        match = re.search(pattern, clean)
        if match:
            return match.group(1)
    return None


def extract_device_id(text: str) -> str | None:
    """
    Extracts device_id from OTP group message.
    Supports formats:
      🔑 Device ID: f95190e4fbd9e50a   (SMS forwarder app format)
      device_id: ABC123
      device: ABC123
      Device ID: ABC123
      [ABC123]  (but NOT [#...] which are Myntra message refs)
      (ABC123)
    """
    # Exclude [#...] Myntra reference tags from matching
    search_text = re.sub(r'\[#[^\]]*\]', '', text)

    patterns = [
        # SMS forwarder app format: 🔑 Device ID: f95190e4fbd9e50a
        r'Device\s+ID\s*:\s*([A-Za-z0-9_\-]+)',
        r'device[_\s-]*id[:\s]+([A-Za-z0-9_\-]+)',
        r'device[:\s]+([A-Za-z0-9_\-]+)',
        r'imei[:\s]+([A-Za-z0-9_\-]+)',
        r'id[:\s]+([A-Za-z0-9_\-]{8,})',
        r'\[([A-Za-z0-9_\-]{5,})\]',
        r'\(([A-Za-z0-9_\-]{5,})\)',
    ]
    for pattern in patterns:
        match = re.search(pattern, search_text, re.IGNORECASE)
        if match:
            found = match.group(1).strip()
            logger.debug(f"extract_device_id matched pattern '{pattern}' → '{found}'")
            return found
    return None


def _escape_md(text: str) -> str:
    """Escape Markdown chars in user-supplied text (only the dangerous ones)."""
    if not text:
        return ""
    # Escape only characters that break basic Markdown parser
    return text.replace("*", "·").replace("_", " ").replace("`", "'").replace("[", "(").replace("]", ")")


def build_clean_otp_message(
    original_text: str,
    otp_code: str,
    price: float,
    *,
    service_name: str = None,
    number: str = None,
    received: int = 1,
    total: int = 1,
    is_last: bool = True,
) -> str:
    # Strip [#...] reference tags (e.g. [#myntra-abc123])
    cleaned = re.sub(r'\[#[^\]]*\]', '', original_text).strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]

    # Find the line containing OTP — that's the meaningful body
    otp_lines = [l for l in lines if otp_code in l]
    if otp_lines:
        message_body = "\n".join(otp_lines)
    else:
        meta_prefixes = ("device", "imei", "sender:", "source:", "from:", "batch:", "debug:", "raw:")
        kept = [l for l in lines if not any(l.lower().startswith(p) for p in meta_prefixes)]
        message_body = "\n".join(kept) if kept else cleaned

    # Escape dangerous Markdown chars in the original message body
    message_body = _escape_md(message_body)

    # ── HEADER ──
    if total > 1:
        if is_last:
            header = f"🎉  *FINAL OTP  {received}/{total}*  🎉"
        else:
            header = f"📩  *OTP RECEIVED  {received}/{total}*"
    else:
        header = "✨  *OTP DELIVERED*  ✨"

    parts = []
    parts.append("┏━━━━━━━━━━━━━━━━━━━━━┓")
    parts.append(f"  {header}")
    parts.append("┗━━━━━━━━━━━━━━━━━━━━━┛")
    parts.append("")

    # ── ORDER INFO ──
    if service_name:
        parts.append(f"🎯  *Service*  ›  `{service_name}`")
    if number:
        parts.append(f"📱  *Number*   ›  `{number}`")
    parts.append("")
    parts.append(f"┌─────────────────────")
    parts.append(f"│  🔐  *YOUR OTP*")
    parts.append(f"│")
    parts.append(f"│       👉 `{otp_code}` 👈")
    parts.append(f"│       _(tap to copy)_")
    parts.append(f"└─────────────────────")
    parts.append("")

    # ── ORIGINAL MESSAGE ──
    parts.append("💬  *Original Message:*")
    parts.append("```")
    parts.append(message_body)
    parts.append("```")

    # ── BILLING + STATUS ──
    parts.append("━━━━━━━━━━━━━━━━━━━━━")
    if total > 1:
        if is_last:
            parts.append(f"📊  Received     ›  *{received}/{total}*  ✅")
            parts.append(f"💰  Total Paid   ›  *₹{price:.2f}*  (1 charge, {total-1} FREE)")
            parts.append(f"🏁  Status       ›  *ORDER COMPLETE* ✅")
        else:
            charge_str = f"₹{price:.2f}" if price > 0 else "FREE"
            parts.append(f"📊  Progress     ›  *{received}/{total}*")
            parts.append(f"💰  This OTP     ›  *{charge_str}*")
            parts.append(f"⏳  Next OTP     ›  *{received+1}/{total}*  (FREE — wait kar)")
    else:
        parts.append(f"💰  Charged      ›  *₹{price:.2f}*")
        parts.append(f"🏁  Status       ›  *ORDER COMPLETE* ✅")
    parts.append("━━━━━━━━━━━━━━━━━━━━━")
    parts.append("")
    parts.append("🙏 _Thanks for choosing us!_")

    return "\n".join(parts)


def clean_sms_for_history(text: str) -> str:
    """
    Strip device_id / device_name / sender / source meta lines from raw SMS so
    that the saved history only shows the actual delivered message body
    (the same content the user sees in the OTP delivery card).
    """
    if not text:
        return ""
    # Drop [#...] message reference tags (e.g. [#myntra-abc123])
    cleaned = re.sub(r'\[#[^\]]*\]', '', text).strip()
    out_lines = []
    for raw_line in cleaned.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip leading emojis / bullets / dashes before checking the prefix
        head = re.sub(r'^[\s•\-→·*▪◦►✦🔑📡📱⚠️🆔📍📞✉️]+', '', line).lower()
        # Skip lines that are clearly only metadata (device id/name, sender, source, etc.)
        if re.match(
            r'^(device|imei|sender|source|from|batch|debug|raw|chip|sim|slot)'
            r'[\s_\-]*(id|name|no|number)?\s*[:=]',
            head,
        ):
            continue
        out_lines.append(line)
    return "\n".join(out_lines) if out_lines else cleaned


def _extract_sender_from_text(text: str) -> str | None:
    """
    Try to extract the SMS sender name from common SMS-forwarder formats.
    e.g.  "From: BIGBSK\nYour OTP..."  →  "BIGBSK"
          "BIGBSK: Your OTP..."         →  "BIGBSK"
          "[BIGBSK] Your OTP..."        →  "BIGBSK"
          "Sender: BB-CART\n..."        →  "BB-CART"
    """
    patterns = [
        r'(?:from|sender|source)\s*:\s*([A-Za-z0-9_\-\.]{3,20})',
        r'^\s*([A-Z0-9_\-]{4,15})\s*:\s',       # "BIGBSK: Your OTP..."
        r'^\s*\[([A-Z0-9_\-]{4,15})\]',          # "[BIGBSK] Your OTP..."
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            return m.group(1).strip()
    return None


async def _notify_admin_unknown_otp(context, text: str, otp_code: str):
    """
    Alert admin when a valid OTP is found in the OTP group but NO active service keyword matched.
    Shows a snippet of the message so admin knows which keyword to add.
    Cooldown: once per 5 min for exact same otp_code prefix to avoid spam.
    """
    from config import ADMIN_IDS
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    now = time.time()
    cooldown_key = f"__unknown__{otp_code[:3]}"
    last = _digit_alert_cooldown.get(cooldown_key, 0)
    if now - last < 300:
        return
    _digit_alert_cooldown[cooldown_key] = now

    sender = _extract_sender_from_text(text)
    snippet = text[:300].replace("`", "'")

    sender_line = f"\n📡  Sender detected: `{sender}`" if sender else ""
    msg = (
        f"🚨 *Unknown OTP — Service keyword match nahi hua!*\n"
        f"{sender_line}\n"
        f"🔢  OTP found: `{otp_code}`\n\n"
        f"📄  *Message snippet:*\n```\n{snippet}\n```\n\n"
        f"⚠️ Ye OTP kisi bhi user ko deliver *nahi* hua!\n\n"
        f"👉 Admin panel → Services → us service ke keywords mein\n"
        f"`{sender.lower() if sender else '<sender_name>'}` add karo."
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚙️ Admin Panel kholo", callback_data="admin_services"),
        InlineKeyboardButton("❌ Ignore", callback_data="noop"),
    ]])
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=msg,
                reply_markup=kb,
                parse_mode="Markdown"
            )
            logger.info(f"[UNKNOWN_OTP] Notified admin {admin_id}")
        except Exception as e:
            logger.warning(f"[UNKNOWN_OTP] Failed to notify admin {admin_id}: {e}")


async def _notify_admin_digit_mismatch(
    context, service_name: str, detected_len: int, current_digits: list
):
    """Send admin an alert when an OTP digit doesn't match current setting, with a fix button."""
    from config import ADMIN_IDS
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    # Cooldown — don't spam admin
    now = time.time()
    last_alert = _digit_alert_cooldown.get(service_name, 0)
    if now - last_alert < _DIGIT_ALERT_COOLDOWN_SECS:
        logger.info(f"[DIGIT_ALERT] cooldown active for {service_name}, skipping alert")
        return
    _digit_alert_cooldown[service_name] = now

    new_digits = sorted(set(current_digits) | {detected_len})
    new_digits_str = ",".join(str(d) for d in new_digits)
    current_str = ", ".join(str(d) for d in sorted(current_digits))

    msg = (
        f"⚠️ *OTP Digit Mismatch!*\n\n"
        f"🎯  Service: `{service_name}`\n"
        f"📏  Mila: *{detected_len} digit* ka OTP\n"
        f"❌  Current setting: `{current_str}` digit\n\n"
        f"Is wajah se user ko OTP deliver *nahi* hua!\n\n"
        f"👇 Kya setting update karni hai?"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"✅ Haan, {detected_len}d bhi add karo",
            callback_data=f"apply_digit_suggest_{service_name}|{new_digits_str}"
        ),
        InlineKeyboardButton("❌ Ignore", callback_data="noop"),
    ]])
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=msg,
                reply_markup=kb,
                parse_mode="Markdown"
            )
            logger.info(f"[DIGIT_ALERT] Notified admin {admin_id} about {detected_len}d mismatch for {service_name}")
        except Exception as e:
            logger.warning(f"[DIGIT_ALERT] Failed to notify admin {admin_id}: {e}")


async def group_message_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    text = update.message.text or update.message.caption
    if not text:
        return

    otp_group_id = await get_otp_group_id()
    chat_id = update.effective_chat.id

    # Health tracking — runs BEFORE mode/filter checks so we always know if group is alive
    if otp_group_id and str(chat_id) == str(otp_group_id):
        try:
            sender = update.message.from_user
            if sender:
                sender_name = sender.username or sender.first_name or f"user_{sender.id}"
                from database import record_group_activity
                await record_group_activity(chat_id, sender.id, sender_name)
                logger.info(f"[HEALTH] tracked msg from {sender_name} ({sender.id}) in group {chat_id}")
        except Exception as e:
            logger.warning(f"[HEALTH] record activity failed: {e}")

    mode = await get_mode()
    if mode != "auto":
        return

    if otp_group_id:
        if str(chat_id) != str(otp_group_id):
            return

    # ── STEP 1: Extract device_id from message ──
    device_id = extract_device_id(text)
    text_lower = text.lower()

    # ── STEP 2: Find session by device_id → get the user-bought service ──
    session = None
    if device_id:
        session = await get_session_by_device(device_id)
        logger.info(f"[FLOW] device_id={device_id} → session found={session is not None}")

    if not session:
        # No device_id session match — fallback path: detect service via keyword,
        # then deliver only if exactly one no-device session is waiting for it.
        if device_id:
            logger.warning(f"[FLOW] device_id={device_id} present in msg but no waiting session matched — skip")
            return

        services = await get_services()
        matched_service = None
        for s in services:
            if not s.get("active"):
                continue
            kws = [kw.lower() for kw in s.get("keywords", [])]
            if any(kw in text_lower for kw in kws):
                matched_service = s["name"]
                break
        if not matched_service:
            logger.info("[FLOW] no device_id and no service keyword matched — skip")
            return

        active = await get_all_active_sessions()
        waiting = [s for s in active if s.get("status") == "waiting" and not s.get("device_id")
                   and s.get("service") == matched_service]
        if len(waiting) != 1:
            logger.info(f"[FLOW] no device_id fallback: {len(waiting)} sessions for {matched_service} — skip")
            return
        session = waiting[0]
        logger.info(f"[FLOW] no device_id fallback → user {session['user_id']} for {matched_service}")

    if session.get("status") != "waiting":
        logger.debug(f"Session for device_id={device_id} is not 'waiting' (status={session.get('status')}). Ignoring.")
        return

    user_id = session["user_id"]
    number = session.get("number")
    service_name = session.get("service", "Myntra")

    # ── STEP 3: Verify the message contains a keyword for the SESSION's service ──
    services = await get_services()
    session_service = next((s for s in services if s.get("name") == service_name), None)
    if not session_service:
        logger.warning(f"[FLOW] session service '{service_name}' not found in services collection — skip")
        return
    svc_keywords = [kw.lower() for kw in session_service.get("keywords", [])]
    if not any(kw in text_lower for kw in svc_keywords):
        logger.info(f"[FLOW] device_id matched user {user_id} ({service_name}) but message has no '{service_name}' keyword (tried={svc_keywords}) — skip")
        return
    logger.info(f"[FLOW] keyword matched for session service='{service_name}'")

    # ── STEP 4: Extract OTP using THAT service's digit setting ──
    allowed_digits = await get_service_otp_digits(service_name)
    otp_code = extract_otp_code(text, allowed_digits=allowed_digits)
    if not otp_code:
        logger.info(f"[FLOW] [{service_name}] keyword matched but no {allowed_digits}-digit OTP in message — skip")
        return
    logger.info(f"[FLOW] service={service_name} otp={otp_code} device_id={device_id}")

    settings = await get_settings()
    global_price = settings.get("otp_price", 5.0)
    price = session.get("price")
    if price is None:
        price = await get_service_price(service_name, global_price)

    from database import consume_otp_slot, finalize_session_delivered, mark_first_buy_used
    updated = await consume_otp_slot(user_id, otp_code)
    if not updated:
        logger.debug(f"Session for user {user_id} already finalized or no slots left. Skipping.")
        return
    received = updated.get("otp_count_received", 1)
    total = updated.get("otp_count_total", 1)
    is_first = (received == 1)
    is_last = (received >= total)

    charged = 0.0
    if is_first:
        await deduct_balance(user_id, price)
        charged = price
        await mark_first_buy_used(user_id)

    if is_last:
        await finalize_session_delivered(user_id)
        if number:
            await delete_number_from_stock(number, service_name)
        try:
            from database import clear_user_blacklisted_devices
            await clear_user_blacklisted_devices(user_id)
        except Exception as e:
            logger.warning(f"clear_user_blacklisted_devices failed: {e}")
        current_jobs = context.job_queue.get_jobs_by_name(f"expire_{user_id}")
        for job in current_jobs:
            job.schedule_removal()

    # Record digit length for this service (used for auto-suggest stats)
    await record_otp_digit_usage(service_name, len(otp_code))

    await add_log("otp_delivered", {
        "user_id": user_id,
        "service": service_name,
        "mode": "auto",
        "otp_code": otp_code,
        "sms_text": clean_sms_for_history(text),
        "device_id": device_id,
        "number": number,
        "price": charged,
        "otp_index": received,
        "otp_total": total,
    })

    delivery_msg = build_clean_otp_message(
        text, otp_code, charged,
        service_name=service_name, number=number,
        received=received, total=total, is_last=is_last
    )

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=delivery_msg,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown"
        )
        logger.info(f"OTP delivered to user {user_id} | OTP: {otp_code} | device_id: {device_id}")
    except Exception as e:
        logger.error(f"Failed to deliver OTP to user {user_id}: {e}")
