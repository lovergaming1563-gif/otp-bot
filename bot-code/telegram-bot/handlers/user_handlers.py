import datetime
import logging
from zoneinfo import ZoneInfo
from telegram import Update, InputMediaPhoto
from telegram.ext import ContextTypes, ConversationHandler

IST = ZoneInfo("Asia/Kolkata")

logger = logging.getLogger(__name__)

from database import (
    get_user, create_user, get_session, update_session_status,
    get_available_number, assign_number, atomic_get_and_assign_number, return_number_to_stock,
    create_session, create_manual_session, get_settings, add_log, delete_number_from_stock,
    get_user_history, get_user_history_filtered, get_user_top_services,
    user_has_first_buy_used, create_deposit, deduct_balance,
    get_services, get_stock_summary, get_service_price, get_flash_sale, get_flash_discount_for_service,
    get_topup_slabs, compute_topup_bonus,
    acquire_order_lock, release_order_lock,
    create_refund_request, get_last_delivered_log, has_pending_refund,
    get_refundable_deliveries, get_log_by_id, is_log_refunded,
    add_user_blacklisted_device, get_user_blacklisted_devices, clear_user_blacklisted_devices
)
from keyboards import (
    main_menu_keyboard, force_join_keyboard, buy_otp_keyboard,
    service_select_keyboard, service_search_results_keyboard,
    waiting_keyboard, deposit_keyboard, back_keyboard,
    admin_refund_keyboard, deposit_amount_keyboard, deposit_payment_keyboard
)
from utils import check_channel_membership, format_balance, time_elapsed, time_remaining
from config import ADMIN_ID, ADMIN_IDS, SERVICE_NAME, SUPPORT_USERNAME, QR_CODE_FILE, VERIFY_API_KEY, VERIFY_MERCHANT_ID, PAYMENT_MAX_TRIES, UPI_ID
from ui import header, field, card, footer, DIV, BAR, safe_md
import os
import asyncio

WAITING_SCREENSHOT = 100


async def redeem_promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["waiting_for"] = "promo_code"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]])
    text = (
        f"{header('REDEEM PROMO CODE', '🎟', '🎟')}\n\n"
        f"💝  Apna promo code neeche type karke bhej de\n\n"
        f"{card(['📝  *Example:*  `WELCOME50`', '⚡  Bonus instantly credit hoga'])}\n\n"
        f"{DIV}\n"
        f"💰  _Bonus seedha tere balance mein jodega_"
    )
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def _get_flash_discounts_map(service_names: list) -> dict:
    """Build {name: discount_pct} for an active flash sale; empty dict if none."""
    fs = await get_flash_sale()
    if not fs:
        return {}
    pct = float(fs.get("discount_percent", 0) or 0)
    if pct <= 0:
        return {}
    if fs.get("all_services"):
        return {n: pct for n in service_names}
    covered = set(fs.get("service_names") or [])
    return {n: pct for n in service_names if n in covered}

def _flash_discounts_from_fs(fs: dict, service_names: list) -> dict:
    """Same as _get_flash_discounts_map but works on an already-fetched fs dict (no DB hit)."""
    if not fs:
        return {}
    pct = float(fs.get("discount_percent", 0) or 0)
    if pct <= 0:
        return {}
    if fs.get("all_services"):
        return {n: pct for n in service_names}
    covered = set(fs.get("service_names") or [])
    return {n: pct for n in service_names if n in covered}


def _flash_pct_for(fs: dict, service: str) -> float:
    """Compute flash discount % for a single service from already-fetched fs dict."""
    if not fs:
        return 0.0
    pct = float(fs.get("discount_percent", 0) or 0)
    if pct <= 0:
        return 0.0
    if fs.get("all_services"):
        return pct
    if service in (fs.get("service_names") or []):
        return pct
    return 0.0



def _flash_banner(fs: dict) -> str:
    """Return a markdown banner string for an active flash sale, or '' if none."""
    if not fs:
        return ""
    pct = float(fs.get("discount_percent", 0) or 0)
    import datetime as _dt
    ends_at = fs.get("ends_at")
    mins = max(0, int((ends_at - _dt.datetime.utcnow()).total_seconds() / 60)) if ends_at else 0
    if mins >= 60:
        time_str = f"{mins // 60}h {mins % 60}m"
    else:
        time_str = f"{mins}m"
    scope = "ALL services" if fs.get("all_services") else f"{len(fs.get('service_names') or [])} services"
    return (
        f"🔥 *FLASH SALE — {pct:g}% OFF*  ({scope})\n"
        f"⏳  _Ends in {time_str}_\n\n"
    )


async def service_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger service-name search input."""
    query = update.callback_query
    await query.answer()
    context.user_data["waiting_for"] = "service_search"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Show All Services", callback_data="buy_otp")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")],
    ])
    text = (
        f"{header('SERVICE SEARCH', '🔍', '🔍')}\n\n"
        f"⚡  Service ka naam type karke bhej —\n"
        f"_partial match bhi chalega!_\n\n"
        f"{card(['📝  *Examples:*', '   `whats`  →  WhatsApp', '   `pay`    →  PhonePe, Google Pay', '   `tele`   →  Telegram'])}\n\n"
        f"{DIV}\n"
        f"⌨️  _Service name neeche type kar:_"
    )
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def service_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pagination for the service select keyboard."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        page = int(query.data.replace("svc_page_", ""))
    except ValueError:
        page = 0

    settings = await get_settings()
    mode = settings.get("mode", "auto")
    services = await get_services()
    active_services = [s for s in services if s.get("active")]

    if mode == "auto":
        summary = await get_stock_summary()
        services_with_stock = [(s["name"], summary.get(s["name"], 0))
                               for s in active_services if summary.get(s["name"], 0) > 0]
    else:
        services_with_stock = [(s["name"], 0) for s in active_services]

    favorites = await get_user_top_services(user_id, limit=3)
    fs = await get_flash_sale()
    flash_map = await _get_flash_discounts_map([n for n, _ in services_with_stock])
    text = (
        f"{header('CHOOSE A SERVICE', '🛒', '🛒')}\n\n"
    )
    text += _flash_banner(fs)
    if favorites:
        text += "⭐  _Tere favorites top par hain_\n\n"
    text += (
        f"📦  *{len(services_with_stock)}* services available\n"
        f"{DIV}\n\n"
        f"👇  Konsi service chahiye?"
    )
    await query.edit_message_text(
        text,
        reply_markup=service_select_keyboard(services_with_stock, favorites=favorites,
                                             page=page, flash_discounts=flash_map),
        parse_mode="Markdown"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id

    args = context.args
    referrer_id = None
    if args:
        try:
            ref = int(args[0])
            if ref != user_id:
                referrer_id = ref
        except:
            pass

    db_user = await get_user(user_id)
    if not db_user:
        await create_user(user_id, user.username or "", user.first_name or "", referrer_id)

    db_user = await get_user(user_id)
    if db_user and db_user.get("banned"):
        await update.message.reply_text("🚫 You have been banned from using this bot.")
        return

    joined = await check_channel_membership(context.bot, user_id)
    if not joined:
        text = (
            f"{header('ACCESS LOCKED', '🚫', '🚫')}\n\n"
            f"👋  Welcome to *{SERVICE_NAME} OTP Service!*\n\n"
            f"{card(['🔒  Bot use karne ke liye', '   pehle channels join karna padega.', '', '📢  Sab join karke', '   neeche button dabao'])}\n\n"
            f"{DIV}\n"
            f"⚡  _Ek baar join karo, lifetime access milega_"
        )
        await update.message.reply_text(text, reply_markup=force_join_keyboard(), parse_mode="Markdown")
        return

    bal = float(db_user.get("balance", 0) or 0) if db_user else 0
    text = (
        f"{header(f'{SERVICE_NAME} OTP SERVICE', '🎯', '🎯')}\n\n"
        f"👋  Welcome back, *{safe_md(user.first_name or 'Friend')}!*\n\n"
        f"{card([f'💰  Balance:  *{format_balance(bal)}*', '⚡  Fast OTP Delivery', '🔒  100% Secure & Private', '💎  Instant Processing'])}\n\n"
        f"{DIV}\n"
        f"👇  Neeche option choose karo"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def check_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    db_user = await get_user(user_id)
    if db_user and db_user.get("banned"):
        await query.edit_message_text("🚫 You have been banned.")
        return

    joined = await check_channel_membership(context.bot, user_id)
    if not joined:
        text = (
            f"{header('STILL NOT JOINED', '❌', '❌')}\n\n"
            f"⚠️  *Saare channels join nahi kiye!*\n\n"
            f"{card(['1️⃣  Upar diye gaye sab channels join kar', '2️⃣  Phir niche button dabao'])}\n\n"
            f"{DIV}"
        )
        await query.edit_message_text(text, reply_markup=force_join_keyboard(), parse_mode="Markdown")
    else:
        bal = float((await get_user(user_id)).get("balance", 0) or 0)
        text = (
            f"{header(f'{SERVICE_NAME} OTP SERVICE', '🎯', '🎯')}\n\n"
            f"✅  *Channels joined successfully!*\n\n"
            f"{card([f'💰  Balance:  *{format_balance(bal)}*', '⚡  Fast OTP Delivery', '🔒  100% Secure & Private', '💎  Instant Processing'])}\n\n"
            f"{DIV}\n"
            f"👇  Neeche option choose karo"
        )
        await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("waiting_for", None)
    context.user_data.pop("deposit_amount", None)
    db_user = await get_user(query.from_user.id)
    bal = float(db_user.get("balance", 0) or 0) if db_user else 0
    text = (
        f"{header(f'{SERVICE_NAME} OTP SERVICE', '🎯', '🎯')}\n\n"
        f"👋  Welcome back!\n\n"
        f"{card([f'💰  Balance:  *{format_balance(bal)}*', '⚡  Fast OTP Delivery', '🔒  100% Secure & Private', '💎  Instant Processing'])}\n\n"
        f"{DIV}\n"
        f"👇  Neeche option choose karo"
    )
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def profile_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    db_user = await get_user(user_id)
    if not db_user:
        await query.edit_message_text("❌ User not found.", reply_markup=back_keyboard())
        return

    session = await get_session(user_id)
    if session:
        svc = session.get("service", SERVICE_NAME)
        active_order = f"⏳  {svc} — Waiting for OTP"
    else:
        active_order = "❌  Koi active order nahi"

    bal = float(db_user.get("balance", 0) or 0)
    spent = float(db_user.get("total_spent", 0) or 0)
    deposited = float(db_user.get("total_deposit", 0) or 0)
    referral_earn = float(db_user.get("referral_earning", 0) or 0)
    refs = int(db_user.get("total_referrals", 0) or 0)

    # Tier badge based on lifetime spend
    if spent >= 5000:
        tier = "💎  DIAMOND"
    elif spent >= 1000:
        tier = "🥇  GOLD"
    elif spent >= 200:
        tier = "🥈  SILVER"
    else:
        tier = "🥉  BRONZE"

    text = (
        f"{header('MY PROFILE', '👤', '👤')}\n\n"
        f"{card([f'🆔  ID:  `{user_id}`', f'🏆  Tier:  *{tier}*'])}\n\n"
        f"{field('Balance', f'*{format_balance(bal)}*', '💰')}\n"
        f"{field('Active Order', active_order, '📦')}\n\n"
        f"{DIV}\n"
        f"📊  *LIFETIME STATS*\n\n"
        f"{field('Total Deposited', f'*{format_balance(deposited)}*', '💸')}\n"
        f"{field('Total Spent', f'*{format_balance(spent)}*', '🛒')}\n"
        f"{field('Referral Earnings', f'*{format_balance(referral_earn)}*', '🎁')}\n"
        f"{field('Total Referrals', f'*{refs}*', '👥')}\n"
        f"{DIV}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")


async def refer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    settings = await get_settings()
    ref_percent = settings.get("referral_percent", 5)

    bot_info = await context.bot.get_me()
    bot_username = bot_info.username
    ref_link = f"https://t.me/{bot_username}?start={user_id}"

    db_user = await get_user(user_id)
    earned = float(db_user.get("referral_earning", 0) or 0) if db_user else 0
    refs = int(db_user.get("total_referrals", 0) or 0) if db_user else 0
    text = (
        f"{header('REFER & EARN', '🎁', '🎁')}\n\n"
        f"💰  Har deposit pe *{ref_percent}%* commission earn kar!\n\n"
        f"{card([f'🔗  *Tera Referral Link:*', f'`{ref_link}`', '', '👆  Long-press karke copy kar'])}\n\n"
        f"{DIV}\n"
        f"📊  *TERI EARNINGS:*\n\n"
        f"{field('Total Referrals', f'*{refs}*', '👥')}\n"
        f"{field('Total Earned', f'*{format_balance(earned)}*', '💵')}\n\n"
        f"{DIV}\n"
        f"📌  *RULES:*\n\n"
        f"   ✅  Commission admin approval ke baad\n"
        f"   🚫  Self-referral allowed nahi\n"
        f"   ♾  Lifetime earning on all deposits\n"
        f"{DIV}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")


async def support_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = (
        f"{header('SUPPORT CENTER', '💬', '💬')}\n\n"
        f"🤝  Koi bhi problem? Hum hain aapke saath!\n\n"
        f"{card([f'📩  *Contact Admin:*', f'   {SUPPORT_USERNAME}', '', '⏰  *Response Time:*', '   Usually within few hours'])}\n\n"
        f"{DIV}\n"
        f"💡  *COMMON ISSUES:*\n\n"
        f"   💰  Balance nahi aaya?\n"
        f"        → Screenshot share karo\n\n"
        f"   📵  OTP nahi mila?\n"
        f"        → Refund request bhejo\n\n"
        f"   ❓  Aur kuch?\n"
        f"        → Admin ko DM karo\n"
        f"{DIV}"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")


def _to_ist(dt):
    if dt is None:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(IST).strftime("%d %b %Y %I:%M %p")


async def _render_history(query, user_id: int, days=None, service=None, active_key="all"):
    from keyboards import history_filter_keyboard
    delivered, cancelled = await get_user_history_filtered(user_id, days=days, service=service, limit=30)
    db_user = await get_user(user_id)
    total_spent = float(db_user.get("total_spent", 0) or 0) if db_user else 0.0

    sub = ""
    if service:
        sub = f"_Service:  {service}_"
    elif days:
        sub = f"_Last {days} days_"

    text = (
        f"{header('ORDER HISTORY', '📋', '📋')}\n\n"
    )
    if sub:
        text += f"{sub}\n\n"
    text += (
        f"{card([f'💸  Lifetime Spend:  *{format_balance(total_spent)}*', f'✅  Delivered:  *{len(delivered)}*    ❌  Cancelled:  *{len(cancelled)}*'])}\n\n"
        f"{DIV}\n\n"
    )

    if delivered:
        text += "✅  *DELIVERED (Last 5):*\n\n"
        for i, d in enumerate(delivered[:5], 1):
            otp_code = d.get("otp_code", "")
            sms_text = d.get("sms_text", "")
            otp_line = f"\n        🔑  OTP:  `{otp_code}`" if otp_code else ""
            sms_line = f"\n        📩  _{sms_text}_" if sms_text else ""
            text += f"  `{i}.`  📦  {d.get('service', SERVICE_NAME)}{otp_line}{sms_line}\n        🕐  _{_to_ist(d.get('created_at'))}_\n\n"
    else:
        text += "✅  *DELIVERED:*  _Koi nahi._\n\n"

    text += f"{DIV}\n\n"

    if cancelled:
        text += "❌  *CANCELLED (Last 5):*\n\n"
        for i, c in enumerate(cancelled[:5], 1):
            text += f"  `{i}.`  📦  {c.get('service', SERVICE_NAME)}\n        🕐  _{_to_ist(c.get('created_at'))}_\n\n"
    else:
        text += "❌  *CANCELLED:*  _Koi nahi._\n\n"

    text += DIV

    await query.edit_message_text(text, reply_markup=history_filter_keyboard(active_key), parse_mode="Markdown")


async def history_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _render_history(query, query.from_user.id, days=None, service=None, active_key="all")


async def history_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "hist_filter_all":
        await _render_history(query, user_id, days=None, active_key="all")
    elif data == "hist_filter_7d":
        await _render_history(query, user_id, days=7, active_key="7d")
    elif data == "hist_filter_30d":
        await _render_history(query, user_id, days=30, active_key="30d")
    elif data == "hist_filter_svc":
        from keyboards import history_service_picker_keyboard
        services = await get_user_top_services(user_id, limit=20)
        if not services:
            await query.edit_message_text(
                "📦 *Service-wise History*\n━━━━━━━━━━━━━━━━━━━━\n\nAbhi koi delivered order nahi hai.",
                reply_markup=history_service_picker_keyboard([]), parse_mode="Markdown"
            )
        else:
            await query.edit_message_text(
                "📦 *Service-wise History*\n━━━━━━━━━━━━━━━━━━━━\n\nKonsi service ka history dekhna hai? 👇",
                reply_markup=history_service_picker_keyboard(services), parse_mode="Markdown"
            )


async def history_service_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    service = query.data.replace("hist_svc_", "", 1)
    await _render_history(query, query.from_user.id, service=service, active_key="all")


async def buy_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # 🚀 Parallelize all independent reads (5 queries → 1 RTT)
    db_user, existing_session, settings, services, favorites, fs = await asyncio.gather(
        get_user(user_id),
        get_session(user_id),
        get_settings(),
        get_services(),
        get_user_top_services(user_id, limit=3),
        get_flash_sale(),
    )

    if not db_user:
        await query.edit_message_text("❌ User not found.", reply_markup=back_keyboard())
        return

    if db_user.get("banned"):
        await query.edit_message_text("🚫 You are banned.", reply_markup=back_keyboard())
        return

    if existing_session:
        text = (
            f"{header('ACTIVE ORDER FOUND', '⚠️', '⚠️')}\n\n"
            f"📦  Aapka ek order pehle se chal raha hai!\n\n"
            f"{card(['⏳  Pehle usse complete hone do', '   ya cancel kar do', '', '👇  Cancel button neeche hai'])}\n\n"
            f"{DIV}"
        )
        await query.edit_message_text(text, reply_markup=waiting_keyboard(), parse_mode="Markdown")
        return

    price = settings.get("otp_price", 5.0)
    mode = settings.get("mode", "auto")
    active_services = [s for s in services if s.get("active")]

    if not active_services:
        text = (
            f"{header('NO SERVICES YET', '😔', '😔')}\n\n"
            f"Admin abhi services setup kar raha hai.\n\n"
            f"{DIV}\n"
            f"💬  Urgent? {SUPPORT_USERNAME}"
        )
        await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
        return

    if mode == "auto":
        summary = await get_stock_summary()
        services_with_stock = [(s["name"], summary.get(s["name"], 0))
                               for s in active_services if summary.get(s["name"], 0) > 0]
        if not services_with_stock:
            text = (
                f"{header('NO STOCK AVAILABLE', '😔', '😔')}\n\n"
                f"Abhi koi number available nahi hai.\n\n"
                f"{card(['🔄  Thodi der baad try kar', '⏰  Stock continuously refresh hota hai'])}\n\n"
                f"{DIV}\n"
                f"💬  Urgent help: {SUPPORT_USERNAME}"
            )
            await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
            return
    else:
        services_with_stock = [(s["name"], 0) for s in active_services]

    total_count = len(services_with_stock)
    flash_map = _flash_discounts_from_fs(fs, [n for n, _ in services_with_stock])

    text = (
        f"{header('CHOOSE A SERVICE', '🛒', '🛒')}\n\n"
    )
    text += _flash_banner(fs)
    if favorites:
        text += "⭐  _Tere favorites top par hain_\n\n"
    text += (
        f"📦  *{total_count}* services available\n"
        f"🟢 = high stock   🟡 = limited   🔴 = empty\n"
    )
    if total_count >= 6:
        text += f"\n💡  _Tip: Bahut services hain? **🔍 Search** se turant dhundo!_\n"
    text += f"{DIV}\n\n👇  Konsi service chahiye?"

    await query.edit_message_text(
        text,
        reply_markup=service_select_keyboard(services_with_stock, favorites=favorites,
                                             flash_discounts=flash_map),
        parse_mode="Markdown"
    )


async def buy_service_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected a specific service to buy OTP for."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    service = query.data.replace("buy_service_", "")

    # 🚀 Parallelize independent reads (5 queries → 1 RTT)
    db_user, settings, services_list, fs, has_used = await asyncio.gather(
        get_user(user_id),
        get_settings(),
        get_services(),
        get_flash_sale(),
        user_has_first_buy_used(user_id),
    )
    global_price = settings.get("otp_price", 5.0)

    # Compute the original (un-discounted) price first, then layer flash + first-buy on top
    svc_doc = next((s for s in services_list if s.get("name") == service), None)
    original_price = float(svc_doc["price"]) if svc_doc and svc_doc.get("price") is not None else float(global_price)
    flash_pct = _flash_pct_for(fs, service)
    if flash_pct > 0:
        base_price = round(original_price * (1.0 - flash_pct / 100.0), 2)
        if base_price < 0.01:
            base_price = 0.01
    else:
        base_price = original_price
    wait_time = settings.get("wait_time", 5)

    disc_pct = float(settings.get("first_buy_discount", 0) or 0)
    is_first_buy = (disc_pct > 0) and (not has_used)
    if is_first_buy:
        price = round(base_price * (100 - disc_pct) / 100.0, 2)
        if flash_pct > 0:
            price_card = [
                f"💰  *Price:*",
                f"     ~{format_balance(original_price)}~  →  *{format_balance(price)}*",
                "",
                f"🔥  *FLASH {flash_pct:g}% OFF*  +  🎉 *FIRST-BUY {disc_pct:g}% OFF*"
            ]
        else:
            price_card = [
                f"💰  *Price:*",
                f"     ~{format_balance(original_price)}~  →  *{format_balance(price)}*",
                "",
                f"🎉  *FIRST-BUY {disc_pct:g}% OFF*"
            ]
    else:
        price = base_price
        if flash_pct > 0:
            price_card = [
                f"💰  *Price:*",
                f"     ~{format_balance(original_price)}~  →  *{format_balance(price)}*",
                "",
                f"🔥  *FLASH SALE {flash_pct:g}% OFF*"
            ]
        else:
            price_card = [f"💰  *Price:*  {format_balance(price)}"]

    bal = float(db_user.get('balance', 0) or 0)
    can_afford = bal >= price
    status_emoji = "✅" if can_afford else "⚠️"
    status_text = "Sufficient" if can_afford else f"Need ₹{price - bal:.2f} more"

    text = (
        f"{header(f'BUY {service.upper()} OTP', '🛒', '🛒')}\n\n"
        f"{field('Service', f'`{service}`', '🎯')}\n"
        f"{field('OTP Validity', f'*{wait_time} min*', '⏱')}\n\n"
        f"{card(price_card)}\n\n"
        f"{DIV}\n"
        f"{field('Your Balance', f'*{format_balance(bal)}*', '💳')}\n"
        f"{field('Status', f'{status_emoji} {status_text}', '📊')}\n"
        f"{DIV}\n\n"
        f"👇  *Confirm* dabake order place karo"
    )
    await query.edit_message_text(text, reply_markup=buy_otp_keyboard(service), parse_mode="Markdown")


async def confirm_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    # --- Atomic lock: prevent double-click race condition ---
    lock_acquired = await acquire_order_lock(user_id)
    if not lock_acquired:
        await query.answer("⏳ Aapka order already process ho raha hai, please wait...", show_alert=True)
        return

    try:
        service = query.data.replace("confirm_buy_", "").strip() or "Myntra"

        # 🚀 Parallelize all independent reads (6 queries → 1 RTT)
        existing_session, db_user, settings, services_list, fs, has_used = await asyncio.gather(
            get_session(user_id),
            get_user(user_id),
            get_settings(),
            get_services(),
            get_flash_sale(),
            user_has_first_buy_used(user_id),
        )
        if existing_session:
            await query.answer("⚠️ Aapka ek order already chal raha hai!", show_alert=True)
            return

        global_price = settings.get("otp_price", 5.0)
        svc_doc = next((s for s in services_list if s.get("name") == service), None)
        original_price = float(svc_doc["price"]) if svc_doc and svc_doc.get("price") is not None else float(global_price)
        flash_pct = _flash_pct_for(fs, service)
        if flash_pct > 0:
            base_price = round(original_price * (1.0 - flash_pct / 100.0), 2)
            if base_price < 0.01:
                base_price = 0.01
        else:
            base_price = original_price
        disc_pct = float(settings.get("first_buy_discount", 0) or 0)
        is_first_buy = (disc_pct > 0) and (not has_used)
        price = round(base_price * (100 - disc_pct) / 100.0, 2) if is_first_buy else base_price
        mode = settings.get("mode", "auto")

        if db_user.get("balance", 0) < price:
            short = price - float(db_user.get('balance', 0) or 0)
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💰 Deposit Now", callback_data="deposit")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")],
            ])
            user_bal_str = format_balance(db_user.get('balance', 0))
            price_str = format_balance(price)
            short_str = format_balance(short)
            text = (
                f"{header('INSUFFICIENT BALANCE', '❌', '❌')}\n\n"
                f"{card([f'💳  Your Balance:  *{user_bal_str}*', f'💰  Required:       *{price_str}*', f'📉  Short by:       *{short_str}*'])}\n\n"
                f"{DIV}\n"
                f"💡  _Pehle deposit karo, phir order karo_\n\n"
                f"👇  *Deposit Now* dabake balance add kar"
            )
            await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
            return

        if mode == "auto":
            number_doc = None
            blacklist = await get_user_blacklisted_devices(user_id)
            if blacklist:
                logger.info(f"[BUY] user {user_id} blacklist (cancelled devices): {blacklist}")
            try:
                from database import atomic_assign_by_device_priority, get_recent_device_ids_db
                recent_dids = await get_recent_device_ids_db()
                if recent_dids:
                    number_doc = await atomic_assign_by_device_priority(service, recent_dids, exclude_device_ids=blacklist)
                    if number_doc:
                        logger.info(f"[BUY] device-priority match for user {user_id} | service={service} | device_id={number_doc.get('device_id')} | number={number_doc.get('number')}")
            except Exception as e:
                logger.error(f"[BUY] device-priority assign error: {e}")
            if not number_doc:
                number_doc = await atomic_get_and_assign_number(service, exclude_device_ids=blacklist)
                if number_doc:
                    logger.info(f"[BUY] fallback assign for user {user_id} | service={service} | number={number_doc.get('number')}")
            if not number_doc:
                text = (
                    f"{header(f'NO {service.upper()} STOCK', '😔', '😔')}\n\n"
                    f"Saare *{service}* numbers abhi busy hain.\n\n"
                    f"{card(['🔄  Few minutes mein try kar', '⏰  Stock auto-refresh hota hai', '💡  Doosri service bhi try karo'])}\n\n"
                    f"{DIV}\n"
                    f"💬  Urgent? {SUPPORT_USERNAME}"
                )
                await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
                return

            session = await create_session(user_id, number_doc["device_id"], number_doc["number"], service, price=price)
            if not session:
                # create_session blocked — user already has a session (race condition caught)
                await query.answer("⚠️ Aapka order already chal raha hai!", show_alert=True)
                return

            cancel_time = settings.get('cancel_time', 2)
            wait_time = settings.get('wait_time', 5)
            num_str = number_doc['number']
            price_str = format_balance(price)
            text = (
                f"{header('ORDER PLACED', '✅', '✅')}\n\n"
                f"{field('Service', f'`{service}`', '🎯')}\n"
                f"{field('Number', f'`{num_str}`', '📱')}\n"
                f"{field('Charged', f'*{price_str}*', '💰')}\n\n"
                f"{card(['🔄  *Status:*  Waiting for OTP...', '', '⚡  OTP automatically deliver hoga', f'⏱  Wait window:  *{wait_time} min*', f'❌  Cancel allowed after:  *{cancel_time} min*'])}\n\n"
                f"{DIV}\n"
                f"📲  _OTP aate hi tujhe message aayega_"
            )
            await query.edit_message_text(text, reply_markup=waiting_keyboard(), parse_mode="Markdown")

            context.job_queue.run_once(
                auto_cancel_expired,
                when=settings.get("wait_time", 5) * 60,
                data={"user_id": user_id, "number": number_doc["number"]},
                name=f"expire_{user_id}"
            )

        else:
            session = await create_manual_session(user_id, service, price=price)
            text = (
                f"{header('ORDER PLACED', '✅', '✅')}\n\n"
                f"{field('Service', f'`{service}`', '🎯')}\n"
                f"{field('Mode', '*Manual* (admin will assign)', '👨‍💼')}\n\n"
                f"{card(['🔄  *Status:*  Processing...', '', '⏳  Admin jaldi number assign karega', '📲  OTP DM mein bhej dega'])}\n\n"
                f"{DIV}\n"
                f"🙏  _Patience rakh, jaldi hojayega_"
            )
            await query.edit_message_text(text, reply_markup=waiting_keyboard(), parse_mode="Markdown")

            for _aid in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=_aid,
                        text=f"🔔 *New Manual Order*\n\nUser ID: `{user_id}`\nUser: {query.from_user.first_name}\n\nGo to Manual Control to send number and OTP.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            context.job_queue.run_once(
                auto_cancel_expired,
                when=settings.get("wait_time", 5) * 60,
                data={"user_id": user_id, "number": None},
                name=f"expire_{user_id}"
            )

    finally:
        # Always release lock after processing (success or failure)
        await release_order_lock(user_id)


async def cancel_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    session = await get_session(user_id)
    if not session:
        await query.answer()
        await query.edit_message_text(
            "❌ OTP already delivered or no active order.\n\nBalance was deducted on delivery.",
            reply_markup=main_menu_keyboard()
        )
        return

    if session.get("otp_count_received", 0) > 0:
        await query.answer(
            "❌ Pehla OTP already aa chuka hai — cancel nahi kar sakte.",
            show_alert=True
        )
        return

    settings = await get_settings()
    cancel_time = settings.get("cancel_time", 2)
    elapsed = time_elapsed(session["start_time"])

    if elapsed < cancel_time:
        remaining_secs = int((cancel_time - elapsed) * 60)
        mins = remaining_secs // 60
        secs = remaining_secs % 60
        time_str = f"{mins} min {secs} sec" if mins > 0 else f"{secs} sec"
        await query.answer(
            f"⏳ Abhi cancel nahi kar sakte.\n\n{time_str} baad cancel kar sakte ho.",
            show_alert=True
        )
        return

    await query.answer()

    number = session.get("number")
    service_name = session.get("service", SERVICE_NAME)
    device_id = session.get("device_id")
    if number:
        await return_number_to_stock(number, service_name)
        logger.info(f"[CANCEL] user={user_id} number={number} service={service_name} returned to stock")
    if device_id:
        await add_user_blacklisted_device(user_id, device_id)
        logger.info(f"[CANCEL] user={user_id} device_id={device_id} added to blacklist")

    current_jobs = context.job_queue.get_jobs_by_name(f"expire_{user_id}")
    for job in current_jobs:
        job.schedule_removal()

    await update_session_status(user_id, "cancelled")
    await add_log("cancelled", {"user_id": user_id, "service": service_name, "number": number})

    text = (
        f"{header('ORDER CANCELLED', '✅', '✅')}\n\n"
        f"{card(['💚  *No balance deducted*', '🔄  Number wapas stock mein gaya', '📦  Aap doosra order place kar sakte ho'])}\n\n"
        f"{DIV}\n"
        f"👇  Naya order ke liye menu se *Buy OTP*"
    )
    await query.edit_message_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")


async def auto_cancel_expired(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    user_id = data["user_id"]
    number = data.get("number")

    session = await get_session(user_id)
    if not session or session["status"] != "waiting":
        return

    service_name = session.get("service", SERVICE_NAME)
    device_id = session.get("device_id")
    received = session.get("otp_count_received", 0)

    if received > 0:
        # At least 1 OTP delivered: number was used, treat as completed delivery.
        # Don't return to stock, don't blacklist device.
        await delete_number_from_stock(number, service_name) if number else None
        try:
            from database import clear_user_blacklisted_devices
            await clear_user_blacklisted_devices(user_id)
        except Exception:
            pass
        await update_session_status(user_id, "delivered")
        await add_log("cancelled", {"user_id": user_id, "service": service_name, "reason": "expired_after_otp", "number": number, "otp_count_received": received})
        try:
            done_text = (
                f"{header('TIME UP — ORDER DONE', '⏰', '✅')}\n\n"
                f"{card([f'📩  Total OTP delivered:  *{received}*', '✅  Order successfully complete'])}\n\n"
                f"{DIV}\n"
                f"🙏  _Naya order ke liye menu use karo_"
            )
            await context.bot.send_message(chat_id=user_id, text=done_text,
                                            reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        except:
            pass
        return

    if number:
        await return_number_to_stock(number, service_name)
        logger.info(f"[AUTO_EXPIRE] user={user_id} number={number} service={service_name} returned to stock")
    if device_id:
        await add_user_blacklisted_device(user_id, device_id)
        logger.info(f"[AUTO_EXPIRE] user={user_id} device_id={device_id} added to blacklist")

    await update_session_status(user_id, "expired")
    await add_log("cancelled", {"user_id": user_id, "service": service_name, "reason": "expired", "number": number})

    try:
        exp_text = (
            f"{header('OTP TIME EXPIRED', '⏰', '⏰')}\n\n"
            f"😔  Time limit ke andar koi OTP nahi aaya\n\n"
            f"{card(['💰  *Aapka balance refund ho gaya*', '🔄  Number wapas stock mein gaya', '✅  Aap turant naya order kar sakte ho'])}\n\n"
            f"{DIV}\n"
            f"👇  Try again from menu"
        )
        await context.bot.send_message(chat_id=user_id, text=exp_text,
                                        reply_markup=main_menu_keyboard(), parse_mode="Markdown")
    except:
        pass


async def deposit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    settings = await get_settings()
    min_dep = float(settings.get("min_deposit", 1))
    text = (
        f"{header('DEPOSIT FUNDS', '💰', '💰')}\n\n"
        f"💳  Kitna deposit karna chahte ho?\n\n"
        f"{card([f'📌  Minimum deposit:  *₹{min_dep:g}*', '⚡  UPI QR scan karke pay karo', '✅  Automatic verify hoga'])}\n\n"
        f"{DIV}\n"
        f"👇  Amount select karo:"
    )
    await query.edit_message_text(text, reply_markup=deposit_amount_keyboard(), parse_mode="Markdown")


async def deposit_amount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    try:
        base_amount = float(query.data.replace("deposit_amt_", ""))
    except Exception:
        await query.answer("❌ Invalid amount.", show_alert=True)
        return
    await _show_deposit_qr(query, context, user_id, base_amount)


async def deposit_custom_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["waiting_for"] = "deposit_custom_amount"
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="deposit")]])
    settings = await get_settings()
    min_dep = float(settings.get("min_deposit", 1))
    text = (
        f"{header('CUSTOM AMOUNT', '✏️', '✏️')}\n\n"
        f"💬  Apna deposit amount type karke bhejo\n\n"
        f"{card([f'📌  Minimum:  *₹{min_dep:g}*', '📝  Example:  `300`'])}\n\n"
        f"{DIV}\n"
        f"👇  Amount type karo:"
    )
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def _show_deposit_qr(query, context, user_id: int, base_amount: float):
    """Generate unique-amount QR and show payment screen to user."""
    from payment_verifier import generate_unique_amount, generate_upi_qr_bytes
    from database import create_deposit, get_settings
    settings = await get_settings()
    min_dep = float(settings.get("min_deposit", 1))
    if base_amount < min_dep:
        await query.answer(f"❌ Minimum deposit ₹{min_dep:g} hai.", show_alert=True)
        return
    unique_amount = generate_unique_amount(base_amount)
    deposit_id = await create_deposit(user_id, "", unique_amount)
    context.user_data["pending_deposit"] = {
        "base_amount": base_amount,
        "unique_amount": unique_amount,
        "deposit_id": deposit_id,
        "tries": 0,
    }
    tries_left = PAYMENT_MAX_TRIES
    try:
        qr_buf = generate_upi_qr_bytes(UPI_ID, unique_amount)
        caption = (
            f"{header('SCAN & PAY', '💳', '💳')}\n\n"
            f"{field('Amount', f'*₹{unique_amount:.2f}*', '💰')}\n"
            f"{field('UPI ID', f'`{UPI_ID}`', '📲')}\n\n"
            f"{card(['⚠️  *IMPORTANT:*', f'   Exactly  *₹{unique_amount:.2f}*  hi pay karo', '   Alag amount mein verify nahi hoga'])}\n\n"
            f"{DIV}\n"
            f"📱  _QR scan karo ya UPI ID se manually pay karo_\n"
            f"✅  _Pay karne ke baad \"I Have Paid\" dabao_"
        )
        await query.message.reply_photo(
            photo=qr_buf,
            caption=caption,
            reply_markup=deposit_payment_keyboard(tries_left),
            parse_mode="Markdown",
        )
        try:
            await query.message.delete()
        except Exception:
            pass
    except Exception as e:
        logger.error(f"[DEPOSIT] QR generation failed: {e}")
        await query.edit_message_text(
            f"{header('PAY NOW', '💳', '💳')}\n\n"
            f"{field('Amount', f'*₹{unique_amount:.2f}*', '💰')}\n"
            f"{field('UPI ID', f'`{UPI_ID}`', '📲')}\n\n"
            f"{card(['⚠️  *IMPORTANT:*', f'   Exactly  *₹{unique_amount:.2f}*  hi pay karo'])}\n\n"
            f"{DIV}\n"
            f"✅  _Pay karne ke baad \"I Have Paid\" dabao_",
            reply_markup=deposit_payment_keyboard(tries_left),
            parse_mode="Markdown",
        )


async def _show_deposit_qr_from_message(message, context, user_id: int, base_amount: float):
    """Same as _show_deposit_qr but triggered from a text message (custom amount input)."""
    from payment_verifier import generate_unique_amount, generate_upi_qr_bytes
    from database import create_deposit, get_settings
    settings = await get_settings()
    min_dep = float(settings.get("min_deposit", 1))
    if base_amount < min_dep:
        await message.reply_text(f"❌ Minimum deposit ₹{min_dep:g} hai.")
        return
    unique_amount = generate_unique_amount(base_amount)
    deposit_id = await create_deposit(user_id, "", unique_amount)
    context.user_data["pending_deposit"] = {
        "base_amount": base_amount,
        "unique_amount": unique_amount,
        "deposit_id": deposit_id,
        "tries": 0,
    }
    tries_left = PAYMENT_MAX_TRIES
    try:
        qr_buf = generate_upi_qr_bytes(UPI_ID, unique_amount)
        caption = (
            f"{header('SCAN & PAY', '💳', '💳')}\n\n"
            f"{field('Amount', f'*₹{unique_amount:.2f}*', '💰')}\n"
            f"{field('UPI ID', f'`{UPI_ID}`', '📲')}\n\n"
            f"{card(['⚠️  *IMPORTANT:*', f'   Exactly  *₹{unique_amount:.2f}*  hi pay karo', '   Alag amount mein verify nahi hoga'])}\n\n"
            f"{DIV}\n"
            f"📱  _QR scan karo ya UPI ID se manually pay karo_\n"
            f"✅  _Pay karne ke baad \"I Have Paid\" dabao_"
        )
        await message.reply_photo(
            photo=qr_buf,
            caption=caption,
            reply_markup=deposit_payment_keyboard(tries_left),
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.error(f"[DEPOSIT] QR generation failed: {e}")
        await message.reply_text(
            f"{header('PAY NOW', '💳', '💳')}\n\n"
            f"{field('Amount', f'*₹{unique_amount:.2f}*', '💰')}\n"
            f"{field('UPI ID', f'`{UPI_ID}`', '📲')}\n\n"
            f"{card(['⚠️  *IMPORTANT:*', f'   Exactly  *₹{unique_amount:.2f}*  hi pay karo'])}\n\n"
            f"{DIV}\n"
            f"✅  _Pay karne ke baad \"I Have Paid\" dabao_",
            reply_markup=deposit_payment_keyboard(tries_left),
            parse_mode="Markdown",
        )


async def _edit_deposit_message(query, text: str, reply_markup, parse_mode="Markdown"):
    """Edit either caption (photo msg) or text (text msg) safely."""
    try:
        await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        try:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            logger.error(f"[DEPOSIT] edit message failed: {e}")


async def i_have_paid_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Verify ho raha hai...", show_alert=False)
    user_id = query.from_user.id
    pending = context.user_data.get("pending_deposit")
    if not pending:
        await query.answer("❌ Koi active deposit nahi mili. Deposit dobara shuru karo.", show_alert=True)
        return
    tries = pending.get("tries", 0) + 1
    pending["tries"] = tries
    tries_left = PAYMENT_MAX_TRIES - tries
    if tries > PAYMENT_MAX_TRIES:
        context.user_data.pop("pending_deposit", None)
        from database import reject_deposit
        try:
            await reject_deposit(pending["deposit_id"])
        except Exception:
            pass
        await _edit_deposit_message(
            query,
            f"{header('MAX TRIES REACHED', '🚫', '🚫')}\n\n"
            f"❌  5 baar verify kiya — payment nahi mili\n\n"
            f"{card(['📞  Admin se contact karo', f'   {SUPPORT_USERNAME}', '', '🆔  Apna User ID bhi bata dena:', f'   `{user_id}`'])}\n\n"
            f"{DIV}",
            reply_markup=back_keyboard(),
        )
        return
    from payment_verifier import verify_payment
    unique_amount = pending["unique_amount"]
    base_amount = pending["base_amount"]
    deposit_id = pending["deposit_id"]
    result = await verify_payment(VERIFY_API_KEY, VERIFY_MERCHANT_ID, unique_amount)
    if result["success"]:
        context.user_data.pop("pending_deposit", None)
        from database import approve_deposit
        await approve_deposit(deposit_id, base_amount)
        user_db = await get_user(user_id)
        new_balance = float(user_db.get("balance", 0)) if user_db else base_amount
        utr_line = f"{field('UTR', f'`{result[\"utr\"]}`', '🔖')}\n" if result.get("utr") else ""
        text = (
            f"{header('PAYMENT VERIFIED', '✅', '✅')}\n\n"
            f"{field('Paid', f'*₹{unique_amount:.2f}*', '💳')}\n"
            f"{field('Credited', f'*₹{base_amount:g}*', '💰')}\n"
            f"{field('New Balance', f'*₹{new_balance:.2f}*', '🏦')}\n"
            f"{utr_line}\n"
            f"{card(['🎉  Balance instantly credited!', '🛒  Ab OTP buy kar sakte ho'])}\n\n"
            f"{DIV}"
        )
        await _edit_deposit_message(query, text, reply_markup=main_menu_keyboard())
        logger.info(f"[DEPOSIT] user={user_id} credited ₹{base_amount} | UTR={result.get('utr')} | unique_amt={unique_amount}")
    else:
        if tries_left <= 0:
            context.user_data.pop("pending_deposit", None)
            from database import reject_deposit
            try:
                await reject_deposit(deposit_id)
            except Exception:
                pass
            await _edit_deposit_message(
                query,
                f"{header('MAX TRIES REACHED', '🚫', '🚫')}\n\n"
                f"❌  5 baar verify kiya — payment nahi mili\n\n"
                f"{card(['📞  Admin se contact karo', f'   {SUPPORT_USERNAME}', '', '🆔  Apna User ID bhi bata dena:', f'   `{user_id}`'])}\n\n"
                f"{DIV}",
                reply_markup=back_keyboard(),
            )
        else:
            await _edit_deposit_message(
                query,
                f"{header('PAYMENT NOT FOUND', '❌', '❌')}\n\n"
                f"{field('Looking for', f'*₹{unique_amount:.2f}*', '💰')}\n\n"
                f"{card(['⚠️  Abhi tak payment nahi mili', '⏳  Pay kar diya? Thodi der mein dobara try karo', f'🔁  Tries baaki:  *{tries_left}/{PAYMENT_MAX_TRIES}*'])}\n\n"
                f"{DIV}\n"
                f"_Make sure exactly ₹{unique_amount:.2f} pay kiya ho_",
                reply_markup=deposit_payment_keyboard(tries_left),
            )
        logger.info(f"[DEPOSIT] user={user_id} verify failed (try {tries}) | unique_amt={unique_amount} | err={result.get('error')}")


async def deposit_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pending = context.user_data.pop("pending_deposit", None)
    if pending:
        from database import reject_deposit
        try:
            await reject_deposit(pending["deposit_id"])
        except Exception:
            pass
    await _edit_deposit_message(
        query,
        f"{header('DEPOSIT CANCELLED', '❌', '❌')}\n\n"
        f"Deposit cancel kar diya gaya.\n\n"
        f"{DIV}",
        reply_markup=main_menu_keyboard(),
    )


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # ── Admin QR upload intercept ────────────────────────────────────────────
    if context.user_data.get("admin_action") == "set_qr":
        from config import ADMIN_IDS
        if user_id in ADMIN_IDS and update.message.photo:
            try:
                photo = update.message.photo[-1]
                tg_file = await photo.get_file()
                import os
                save_path = os.path.join(os.getcwd(), "qr.png")
                await tg_file.download_to_drive(custom_path=save_path)
                context.user_data.pop("admin_action", None)
                from keyboards import admin_main_keyboard
                await update.message.reply_text(
                    "✅ QR code updated successfully!\n\nDeposit screen pe turant naya QR dikhne lagega.",
                    reply_markup=admin_main_keyboard()
                )
            except Exception as e:
                await update.message.reply_text(f"❌ QR save failed: {e}")
            return


async def refund_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    db_user = await get_user(user_id)
    if not db_user:
        await query.edit_message_text("❌ User not found.", reply_markup=back_keyboard())
        return
    if db_user.get("banned"):
        await query.edit_message_text("🚫 You are banned.", reply_markup=back_keyboard())
        return

    if await has_pending_refund(user_id):
        text = (
            f"{header('REFUND PENDING', '⏳', '⏳')}\n\n"
            f"{card(['⚠️  Aapka pichla refund request', '   abhi review mein hai', '', '👨‍💼  Admin response ke baad', '   naya request bhejna'])}\n\n"
            f"{DIV}"
        )
        await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
        return

    orders = await get_refundable_deliveries(user_id, limit=10)
    if not orders:
        text = (
            f"{header('NO REFUNDABLE ORDERS', '❌', '❌')}\n\n"
            f"Aapke paas koi delivered order nahi hai\n"
            f"jiska refund le sako.\n\n"
            f"{card(['📌  *Note:*', '   Ek number ka refund', '   sirf 1 baar mil sakta hai'])}\n\n"
            f"{DIV}"
        )
        await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
        return

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    rows = []
    for o in orders:
        num = o.get("number", "N/A")
        svc = o.get("service", "?")
        ts = o.get("created_at")
        try:
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            ts_str = ts.astimezone(IST).strftime("%d %b %I:%M%p") if ts else ""
        except Exception:
            ts_str = ""
        label = f"{svc} | {num} | {ts_str}"
        rows.append([InlineKeyboardButton(label[:60], callback_data=f"refund_pick_{o['_id']}")])
    rows.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")])

    text = (
        f"{header('REFUND REQUEST', '🔄', '🔄')}\n\n"
        f"📋  Apne delivered numbers mein se select karo\n"
        f"jiska refund chahiye:\n\n"
        f"{card(['📌  *Note:*', '   Ek number ka refund', '   sirf 1 baar mil sakta hai'])}\n\n"
        f"{DIV}\n"
        f"👇  Order select kar:"
    )
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def refund_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    log_id = query.data.replace("refund_pick_", "")

    log = await get_log_by_id(log_id)
    if not log or log.get("user_id") != user_id:
        await query.edit_message_text(
            "❌ Order not found ya tumhara nahi hai.",
            reply_markup=back_keyboard()
        )
        return

    if await has_pending_refund(user_id):
        await query.edit_message_text(
            "⏳ Pichla refund request abhi pending hai.",
            reply_markup=back_keyboard()
        )
        return

    if await is_log_refunded(log_id):
        await query.edit_message_text(
            "⚠️ Is number ka refund already process ho chuka hai.",
            reply_markup=back_keyboard()
        )
        return

    context.user_data["waiting_for"] = "refund_video"
    context.user_data["refund_log_id"] = log_id

    num = log.get("number", "N/A")
    svc = log.get("service", "?")
    text = (
        f"{header(f'REFUND — {svc.upper()}', '🔄', '🔄')}\n\n"
        f"{field('Number', f'`{num}`', '📱')}\n"
        f"{field('Service', f'`{svc}`', '🎯')}\n\n"
        f"📹  Ab apni screen recording video bhejo\n"
        f"jisme problem clearly dikhe.\n\n"
        f"{card(['⚠️  *IMPORTANT:*', '   • Sirf VIDEO file accept hogi', '   • Photo accept nahi hoga', '   • Issue clearly dikhna chahiye', '   • Admin review karke decide karega'])}\n\n"
        f"{DIV}\n"
        f"👇  Video abhi send kar:"
    )
    await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")


async def handle_refund_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if context.user_data.get("waiting_for") != "refund_video":
        return

    msg = update.message
    video = msg.video or msg.video_note or (msg.document if msg.document and (msg.document.mime_type or "").startswith("video/") else None)
    if not video:
        await msg.reply_text(
            "❌ Sirf *VIDEO* accept hogi. Screen recording bhejo.",
            parse_mode="Markdown"
        )
        return

    file_id = video.file_id
    log_id = context.user_data.get("refund_log_id")
    if not log_id:
        await msg.reply_text("❌ Pehle order select karo. /start dabake refund menu se shuru karo.")
        context.user_data.pop("waiting_for", None)
        return

    if await is_log_refunded(log_id):
        await msg.reply_text("⚠️ Is number ka refund already process ho chuka hai.",
                             reply_markup=main_menu_keyboard())
        context.user_data.pop("waiting_for", None)
        context.user_data.pop("refund_log_id", None)
        return

    log = await get_log_by_id(log_id)
    order_info = {}
    if log:
        order_info = {
            "service": log.get("service"),
            "number": log.get("number"),
            "created_at": log.get("created_at"),
            "price": log.get("price"),
            "mode": log.get("mode"),
        }

    refund_id = await create_refund_request(user_id, file_id, log_id, order_info)
    context.user_data.pop("waiting_for", None)
    context.user_data.pop("refund_log_id", None)

    text = (
        f"{header('REFUND SUBMITTED', '✅', '✅')}\n\n"
        f"{card(['📹  Video successfully received', '⏳  Admin jaldi review karega', '💰  Approve hone par balance refund'])}\n\n"
        f"{DIV}\n"
        f"❓  Help chahiye?\n"
        f"      → {SUPPORT_USERNAME}\n"
        f"{DIV}"
    )
    await msg.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    user = update.effective_user
    uname = f"@{user.username}" if user.username else (user.first_name or "User")
    try:
        ts = order_info.get("created_at")
        if ts:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            ts_str = ts.astimezone(IST).strftime("%d %b %Y %I:%M %p")
        else:
            ts_str = "N/A"
    except Exception:
        ts_str = "N/A"

    price_val = order_info.get("price")
    price_str = format_balance(price_val) if isinstance(price_val, (int, float)) else "N/A"

    caption = (
        f"🔄 *Refund Request*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 User: {uname}\n"
        f"🆔 ID: `{user_id}`\n"
        f"📦 Service: {order_info.get('service', 'N/A')}\n"
        f"📱 Number: `{order_info.get('number', 'N/A')}`\n"
        f"💵 Order Price: {price_str}\n"
        f"🕐 Delivered: {ts_str}\n"
        f"🆔 Refund ID: `{refund_id}`"
    )

    for _aid in ADMIN_IDS:
        try:
            await context.bot.send_video(
                chat_id=_aid,
                video=file_id,
                caption=caption,
                parse_mode="Markdown",
                reply_markup=admin_refund_keyboard(refund_id),
            )
        except Exception as e:
            logger.error(f"FAILED to send refund video to admin {_aid}: {e}")
            try:
                await context.bot.send_message(
                    chat_id=_aid,
                    text=caption + f"\n\n⚠️ Video forward failed: {e}",
                    parse_mode="Markdown",
                    reply_markup=admin_refund_keyboard(refund_id),
                )
            except Exception:
                pass
    logger.info(f"Refund request {refund_id} forwarded to admins for user {user_id}")

