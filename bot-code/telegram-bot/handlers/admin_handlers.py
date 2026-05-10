import datetime
import logging
logger = logging.getLogger(__name__)
from telegram import Update
from telegram.ext import ContextTypes
from database import (
    get_stats, get_all_users, get_stock, add_stock, remove_stock_item,
    get_pending_deposits, approve_deposit, reject_deposit, add_referral_bonus,
    get_settings, update_settings, get_mode, set_mode, get_logs,
    get_user, update_user_balance, deduct_balance, ban_user, unban_user,
    update_session_number, get_session, update_session_status, add_log,
    delete_number_from_stock, get_otp_group_id, set_otp_group_id, get_deposit,
    clear_all_stock, clear_service_stock, reset_user_balance, get_top_spenders, reset_all_stats,
    add_balance_manual, get_services, add_service, toggle_service, delete_service,
    get_stock_summary, update_service_price,
    get_refund_request, approve_refund_request, reject_refund_request,
    get_upi_id, set_upi_id, get_min_deposit, set_min_deposit, get_deposit_stats,
    add_user_note, get_user_notes, delete_user_note,
    get_recent_otp_sessions
)
from keyboards import (
    admin_main_keyboard, admin_stock_keyboard, admin_stock_manage_keyboard,
    admin_deposit_approve_keyboard, admin_logs_keyboard, admin_settings_keyboard,
    admin_mode_keyboard, admin_manual_keyboard, user_actions_keyboard, back_keyboard,
    main_menu_keyboard, stock_clear_confirm_keyboard, reset_stats_confirm_keyboard,
    admin_services_keyboard, bulk_select_keyboard, bulk_final_confirm_keyboard,
    svc_add_extracted_keyboard
)
from utils import format_balance
from config import ADMIN_ID, ADMIN_IDS, SERVICE_NAME
import database as _database  # for direct db access (e.g. db.services.find_one)


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Unauthorized.")
        return
    await update.message.reply_text(
        "🔐 *Admin Panel*\n\nSelect an option:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )


async def admin_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data.clear()
    await query.edit_message_text(
        "🔐 *Admin Panel*\n\nSelect an option:",
        reply_markup=admin_main_keyboard(),
        parse_mode="Markdown"
    )


async def admin_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    stats = await get_stats()
    text = (
        f"📊 *Bot Statistics*\n\n"
        f"👥 Total Users: {stats['total_users']}\n"
        f"💰 Total Deposits Approved: {stats['total_deposits']}\n"
        f"📤 Total OTPs Delivered: {stats['total_otp']}\n"
        f"⏳ Active Sessions: {stats['active_sessions']}"
    )
    from keyboards import admin_main_keyboard
    keyboard = [[]]
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def admin_stock_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    summary = await get_stock_summary()
    text = "📦 *Stock Management*\n\nHar service ka alag stock. Service choose karo:"
    await query.edit_message_text(
        text,
        reply_markup=admin_stock_keyboard(services, summary),
        parse_mode="Markdown"
    )


async def stock_svc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin clicks on a service to manage its stock."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service = query.data.replace("stock_svc_", "")
    context.user_data["stock_service"] = service
    stock = await get_stock(service)
    await query.edit_message_text(
        f"📦 *{service} Stock*\n\nAbhi *{len(stock)}* numbers available hain.\n\nKya karna hai?",
        reply_markup=admin_stock_manage_keyboard(service),
        parse_mode="Markdown"
    )


async def stock_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service = query.data.replace("stock_view_", "")
    stock = await get_stock(service)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"stock_svc_{service}")]])

    if not stock:
        await query.edit_message_text(
            f"📦 *{service} Stock*\n\n⚠️ Koi number nahi hai.",
            reply_markup=kb, parse_mode="Markdown"
        )
        return

    # Build paginated messages (Telegram limit ~4096 chars)
    header = f"📦 *{service} Stock — {len(stock)} numbers*\n\n"
    lines = [f"`{item['number']}` | `{item.get('device_id', 'N/A')}`" for item in stock]
    chunks, current = [], header
    for line in lines:
        if len(current) + len(line) + 1 > 3800:
            chunks.append(current)
            current = f"📦 *{service} Stock (cont.)*\n\n"
        current += line + "\n"
    chunks.append(current)

    # Send first chunk as edit, rest as new messages
    await query.edit_message_text(chunks[0], reply_markup=kb if len(chunks) == 1 else None, parse_mode="Markdown")
    for i, chunk in enumerate(chunks[1:], 1):
        is_last = (i == len(chunks) - 1)
        await query.message.reply_text(chunk, reply_markup=kb if is_last else None, parse_mode="Markdown")


async def stock_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service = query.data.replace("stock_add_", "")
    context.user_data["admin_action"] = "add_stock"
    context.user_data["stock_service"] = service
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"stock_svc_{service}")]])
    await query.edit_message_text(
        f"📦 *Add Numbers — {service}*\n\n"
        f"Ek ya zyaada numbers send karo:\n`number | device_id`\n\n"
        f"Example:\n`+919876543210 | f95190e4fbd9e50a`\n`+918888888888 | 7dc588c24bd5db02`\n\n"
        f"Device ID: SMS Forwarder app se lo.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def stock_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service = query.data.replace("stock_remove_", "")
    context.user_data["admin_action"] = "remove_stock_number"
    context.user_data["stock_service"] = service
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"stock_svc_{service}")]])
    await query.edit_message_text(
        f"🗑 *Remove Number — {service}*\n\nNumber type karo jo delete karna hai:\n`+919876543210`",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def stock_clear_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    stock = await get_stock()
    count = len(stock)
    await query.edit_message_text(
        f"⚠️ *Confirm Clear ALL Stock*\n\nAbhi *{count}* numbers available hain (saari services).\n\nKya aap *saara stock delete* karna chahte ho?\n\nYeh action undo nahi ho sakta!",
        reply_markup=stock_clear_confirm_keyboard(),
        parse_mode="Markdown"
    )


async def stock_clear_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    deleted = await clear_all_stock()
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Stock", callback_data="admin_stock")]])
    await query.edit_message_text(
        f"✅ *All Stock Cleared!*\n\n{deleted} numbers delete kar diye gaye.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def stock_clear_svc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask confirmation before clearing all stock for a specific service."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service = query.data.replace("stock_clear_svc_", "")
    stock = await get_stock(service)
    count = len(stock)
    await query.edit_message_text(
        f"⚠️ *Confirm Clear {service} Stock*\n\n"
        f"Abhi *{count}* numbers hain {service} mein.\n\n"
        f"Kya aap *sare {service} numbers delete* karna chahte ho?\n\n"
        f"Yeh action undo nahi ho sakta!",
        reply_markup=stock_clear_confirm_keyboard(service),
        parse_mode="Markdown"
    )


async def stock_clear_svc_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually delete all stock for a specific service."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service = query.data.replace("stock_clear_svc_confirm_", "")
    deleted = await clear_service_stock(service)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"stock_svc_{service}")]])
    await query.edit_message_text(
        f"✅ *{service} Stock Cleared!*\n\n{deleted} numbers delete kar diye gaye.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def resetbal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.replace("resetbal_", ""))
    await reset_user_balance(user_id)
    db_user = await get_user(user_id)
    await query.edit_message_text(
        f"✅ User `{user_id}` ka balance, total deposit aur referral earning — sab *zero* kar diya gaya.\n\n(User account delete nahi hua)",
        reply_markup=user_actions_keyboard(user_id, db_user.get("banned", False) if db_user else False),
        parse_mode="Markdown"
    )


async def admin_deposits_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    pending = await get_pending_deposits()
    if not pending:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
        await query.edit_message_text("💰 No pending deposits.", reply_markup=kb)
        return

    text = f"💰 *Pending Deposits ({len(pending)})*\n\nShowing first deposit:"
    dep = pending[0]
    dep_id = str(dep["_id"])
    user_id = dep["user_id"]

    db_user = await get_user(user_id)
    username_str = f"@{db_user.get('username', '')}" if db_user and db_user.get("username") else "N/A"

    caption = (
        f"💰 *Deposit Request*\n\n"
        f"User ID: `{user_id}`\n"
        f"Username: {username_str}\n"
        f"Total Deposited Before: {format_balance(db_user.get('total_deposit', 0) if db_user else 0)}\n"
        f"Deposit ID: `{dep_id}`\n\n"
        f"Click Approve and enter amount, or Reject."
    )

    try:
        await query.message.reply_photo(
            photo=dep["screenshot_file_id"],
            caption=caption,
            reply_markup=admin_deposit_approve_keyboard(dep_id),
            parse_mode="Markdown"
        )
        await query.message.delete()
    except Exception as e:
        await query.edit_message_text(caption, reply_markup=admin_deposit_approve_keyboard(dep_id), parse_mode="Markdown")


async def dep_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    deposit_id = query.data.replace("dep_approve_", "")

    dep = await get_deposit(deposit_id)

    # --- Already processed? Show alert and stop ---
    if not dep:
        await query.answer("⚠️ Deposit nahi mila.", show_alert=True)
        return
    if dep.get("status") != "pending":
        status = dep.get("status", "unknown")
        await query.answer(f"⚠️ Yeh deposit already {status} ho chuka hai!", show_alert=True)
        return

    saved_amount = dep.get("amount")

    if saved_amount is not None:
        approved = await approve_deposit(deposit_id, float(saved_amount))
        if approved:
            settings = await get_settings()
            ref_percent = settings.get("referral_percent", 5)
            db_user = await get_user(approved["user_id"])
            if db_user and db_user.get("referrer_id"):
                bonus = float(saved_amount) * ref_percent / 100
                await add_referral_bonus(db_user["referrer_id"], bonus)
                await add_log("referral_bonus", {
                    "user_id": db_user["referrer_id"],
                    "from_user": approved["user_id"],
                    "amount": bonus
                })
                try:
                    await context.bot.send_message(
                        chat_id=db_user["referrer_id"],
                        text=f"Referral bonus! You earned {format_balance(bonus)} from a deposit."
                    )
                except:
                    pass
            await add_log("deposit_approved", {"user_id": approved["user_id"], "amount": float(saved_amount)})
            try:
                await context.bot.send_message(
                    chat_id=approved["user_id"],
                    text=f"✅ Deposit approved!\n\n₹{float(saved_amount):.2f} aapke balance mein add kar diye gaye."
                )
            except:
                pass
            try:
                await query.edit_message_caption(
                    f"✅ Approved — ₹{saved_amount} added to user {approved['user_id']}.",
                    reply_markup=None
                )
            except:
                pass
        else:
            # approve_deposit returned None — already approved by another click
            await query.answer("⚠️ Yeh deposit already approve ho chuka hai!", show_alert=True)
    else:
        context.user_data["admin_action"] = "approve_deposit"
        context.user_data["deposit_id"] = deposit_id
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_deposits")]])
        try:
            await query.edit_message_caption(
                f"💰 Kitna amount approve karna hai? (Rs. mein type karo)\n\nDeposit ID: `{deposit_id}`",
                reply_markup=kb
            )
        except:
            await query.message.reply_text(
                f"💰 Kitna amount approve karna hai? (Rs. mein type karo)\n\nDeposit ID: `{deposit_id}`"
            )


async def dep_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    deposit_id = query.data.replace("dep_reject_", "")

    # --- Already processed? Show alert and stop ---
    raw = await get_deposit(deposit_id)
    if not raw:
        await query.answer("⚠️ Deposit nahi mila.", show_alert=True)
        return
    if raw.get("status") != "pending":
        status = raw.get("status", "unknown")
        await query.answer(f"⚠️ Yeh deposit already {status} ho chuka hai!", show_alert=True)
        return

    dep = await reject_deposit(deposit_id)
    if dep:
        try:
            await context.bot.send_message(
                chat_id=dep["user_id"],
                text="❌ Aapka deposit reject ho gaya.\n\nKoi problem hai toh support se contact karo.",
                reply_markup=main_menu_keyboard()
            )
        except:
            pass
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
        try:
            await query.edit_message_caption("❌ Deposit rejected. User ko notify kar diya.", reply_markup=kb)
        except:
            await query.edit_message_text("❌ Deposit rejected. User ko notify kar diya.", reply_markup=kb)
    else:
        await query.answer("⚠️ Yeh deposit already process ho chuka hai!", show_alert=True)


async def admin_users_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "search_user"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
    await query.edit_message_text(
        "👥 *User Search*\n\nSend the User ID to look up:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def admin_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "broadcast"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_back")]])
    await query.edit_message_text(
        "📢 *Broadcast*\n\nSend the message you want to broadcast to ALL users:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def admin_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "📜 *Logs*\n\nSelect log type:",
        reply_markup=admin_logs_keyboard(),
        parse_mode="Markdown"
    )


async def log_type_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    log_map = {
        "log_otp": "otp_delivered",
        "log_deposit": "deposit_approved",
        "log_cancel": "cancelled",
        "log_referral": "referral_bonus"
    }
    log_type = log_map.get(query.data, "otp_delivered")
    logs = await get_logs(log_type, 20)

    if not logs:
        text = f"📜 No {log_type} logs found."
    else:
        text = f"📜 *{log_type.replace('_', ' ').title()} Logs (last {len(logs)}):*\n\n"
        for log in logs:
            t = log.get("created_at", datetime.datetime.utcnow()).strftime("%d %b %H:%M")
            uid = log.get("user_id", "N/A")
            text += f"• UID: `{uid}` — {t}\n"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_logs")]])
    await query.edit_message_text(text[:4000], reply_markup=kb, parse_mode="Markdown")


async def admin_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    settings = await get_settings()
    otp_group = settings.get("otp_group_id", None)
    group_display = f"`{otp_group}`" if otp_group else "Not set (all groups)"
    fb_disc = settings.get("first_buy_discount", 0) or 0
    h_enabled = settings.get("health_enabled", True)
    h_threshold = settings.get("health_threshold_min", 10)
    h_reminder = settings.get("health_reminder_min", 4)
    h_window = settings.get("health_bot_window_min", 60)
    h_status = "🟢 ON" if h_enabled else "🔴 OFF"
    m_enabled = settings.get("maintenance_mode", False)
    m_status = "🔴 ON (users blocked)" if m_enabled else "🟢 OFF (normal)"
    from database import get_recent_devices_cache_size, get_recent_device_ids_db
    cache_size = await get_recent_devices_cache_size()
    cache_now = await get_recent_device_ids_db()
    # Payment method toggle status
    aloo_enabled   = settings.get("aloo_enabled",   True)
    zapupi_enabled = settings.get("zapupi_enabled",  False)
    aloo_status    = "✅ ON" if aloo_enabled   else "❌ OFF"
    zapupi_status  = "✅ ON" if zapupi_enabled else "❌ OFF"
    # Payment settings
    upi_now = await get_upi_id()
    upi_display = f"`{upi_now}`" if upi_now else "_Not set_"
    min_dep = await get_min_deposit()
    import os
    qr_display = "✅ Set" if os.path.exists("qr.png") else "❌ Not uploaded"
    text = (
        f"⚙️ *Settings*\n\n"
        f"💵 OTP Price: {format_balance(settings.get('otp_price', 5))}\n"
        f"🎁 Referral %: {settings.get('referral_percent', 5)}%\n"
        f"⏱ Wait Time: {settings.get('wait_time', 5)} min\n"
        f"⏳ Cancel Time: {settings.get('cancel_time', 2)} min\n"
        f"🏦 UPI ID: {upi_display}\n"
        f"🖼 QR Code: {qr_display}\n"
        f"💵 Min Deposit: ₹{min_dep:.0f}\n"
        f"🆕 First-Buy Discount: {fb_disc}%\n"
        f"🧠 Smart Match Cache: *{cache_size}* slots ({len(cache_now)} cached now)\n"
        f"📡 OTP Group: {group_display}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🛠 *Maintenance Mode*: {m_status}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📡 *Group Health Monitor*\n"
        f"Status: {h_status}\n"
        f"⏰ Silence Threshold: {h_threshold} min\n"
        f"🔔 Reminder Gap: {h_reminder} min\n"
        f"🤖 Bot Active Window: {h_window} min\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💳 *Payment Methods*\n"
        f"🟡 Aloo: {aloo_status}  |  ⚡ ZapUPI: {zapupi_status}\n"
    )
    await query.edit_message_text(text, reply_markup=admin_settings_keyboard(h_enabled, m_enabled, aloo_enabled, zapupi_enabled), parse_mode="Markdown")


# ============================================================================
# UPI / QR / Min Deposit settings (admin)
# ============================================================================

async def set_upi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "set_upi"
    current = await get_upi_id()
    cur_display = f"`{current}`" if current else "_Not set_"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        f"🏦 *Change UPI ID*\n\n"
        f"Current: {cur_display}\n\n"
        f"Naya UPI ID bhejo (e.g. `yourname@paytm` , `9876543210@ybl`):",
        reply_markup=kb, parse_mode="Markdown"
    )


async def set_qr_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "set_qr"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        f"🖼 *Change QR Code*\n\n"
        f"📸 Naya QR code ka *photo* bhejo (image as photo, file nahi).\n"
        f"Purana QR replace ho jayega aur turant deposit screen pe naya QR dikhne lagega.",
        reply_markup=kb, parse_mode="Markdown"
    )


async def set_min_deposit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "set_min_deposit"
    current = await get_min_deposit()
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        f"💵 *Change Minimum Deposit*\n\n"
        f"Current: *₹{current:.0f}*\n\n"
        f"Naya minimum amount bhejo (e.g. `10`, `50`, `100`):",
        reply_markup=kb, parse_mode="Markdown"
    )


# ============================================================================
# Deposit Stats dashboard (admin)
# ============================================================================

async def admin_deposit_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    s = await get_deposit_stats()
    top_lines = ""
    if s["top"]:
        for i, t in enumerate(s["top"], 1):
            medal = ["🥇", "🥈", "🥉", "🏅", "🏅"][i-1]
            top_lines += f"{medal} `{t['user_id']}` — ₹{t['amount']:.0f} ({t['count']} deposits)\n"
    else:
        top_lines = "_Koi deposit nahi hua abhi tak_\n"

    text = (
        f"💰 *Deposit Stats*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💸 *Total Approved:*  ₹{s['total_amount']:.2f}\n"
        f"👥 *Unique Depositors:*  {s['unique_users']}\n\n"
        f"📅 *Today (24h):*  ₹{s['today_amount']:.2f}\n"
        f"📅 *Last 7 days:*  ₹{s['week_amount']:.2f}\n"
        f"📅 *Last 30 days:*  ₹{s['month_amount']:.2f}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🔢 *UTR / Deposit Counts*\n"
        f"⏳ Pending:  *{s['pending_count']}*\n"
        f"✅ Approved (total):  *{s['approved_count']}*\n"
        f"  ⚡ Auto-verified:  {s['auto_count']}\n"
        f"  ✋ Manual approved:  {s['manual_count']}\n"
        f"❌ Rejected:  *{s['rejected_count']}*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *Top 5 Depositors*\n"
        f"{top_lines}"
    )
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_deposit_stats")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def admin_sms_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show SMS auto-verifier health/stats + ON/OFF toggle."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from sms_verifier import verifier as _sms, SMS_GROUP_ID, SMS_SENDER_FILTER, CACHE_TTL_SECONDS
    from database import get_settings
    s = await get_settings()
    enabled = s.get("sms_verify_enabled", True)
    toggle_label = "🔴 Turn OFF Auto-Verify" if enabled else "🟢 Turn ON Auto-Verify"
    status_emoji = "✅ Configured" if _sms.is_configured() else "❌ NOT configured"
    enabled_emoji = "🟢 ON" if enabled else "🔴 OFF"

    def _fmt(dt):
        if not dt:
            return "_never_"
        delta = (datetime.datetime.utcnow() - dt).total_seconds()
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta/60)}m ago"
        return f"{int(delta/3600)}h ago"

    text = (
        f"📱 *SMS Auto-Verify Status*\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚙️  Config:  {status_emoji}\n"
        f"🔘  Toggle:  {enabled_emoji}\n"
        f"📥  Group ID:  `{SMS_GROUP_ID or 'NOT SET'}`\n"
        f"🏷  Sender filter:  `{SMS_SENDER_FILTER}`\n"
        f"⏱  Cache TTL:  {CACHE_TTL_SECONDS // 60} min\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Lifetime counters*\n"
        f"📩 Messages seen:  *{_sms.total_seen}*\n"
        f"✅ Credits cached:  *{_sms.total_parsed}*\n"
        f"⏭ Skipped:  *{_sms.total_skipped}*\n"
        f"💾 Cached now:  *{len(_sms.cache)}*\n\n"
        f"🕒 Last message:  {_fmt(_sms.last_message_at)}\n"
        f"🕒 Last credit:  {_fmt(_sms.last_credit_at)}\n"
    )
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(toggle_label, callback_data="toggle_sms_verify")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_sms_status")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_settings")],
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def toggle_sms_verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flip the sms_verify_enabled flag in settings."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_settings, update_settings
    s = await get_settings()
    new_val = not s.get("sms_verify_enabled", True)
    await update_settings("sms_verify_enabled", new_val)
    await query.answer(f"SMS Auto-Verify {'ENABLED' if new_val else 'DISABLED'}", show_alert=True)
    # Re-render status panel
    await admin_sms_status_callback(update, context)


async def admin_used_utrs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last 50 UTRs already auto-credited (anti-reuse audit list)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_recent_used_utrs
    rows = await get_recent_used_utrs(limit=50)
    if not rows:
        body = "_Abhi tak koi UTR auto-verify nahi hua._"
    else:
        lines = []
        for i, r in enumerate(rows, 1):
            ts = r.get("created_at")
            ts_str = ts.strftime("%d-%b %H:%M") if ts else "?"
            uid = r.get("user_id", "?")
            amt = r.get("amount", 0)
            utr = r.get("utr", "?")
            lines.append(f"`{i:>2}.` `{utr}`  ₹{amt:.0f}  • `{uid}` • {ts_str}")
        body = "\n".join(lines)
    text = (
        f"📜 *Used UTRs (last 50)*\n\n"
        f"_Format: UTR  ₹amount • user_id • time_\n\n"
        f"{body}"
    )
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh", callback_data="admin_used_utrs")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_settings")],
    ])
    try:
        await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        # Markdown parse fail fallback
        await query.edit_message_text(text, reply_markup=kb)


async def set_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_action"] = "set_price"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text("💵 Enter new OTP price (e.g. `5.00`):", reply_markup=kb, parse_mode="Markdown")


async def set_referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_action"] = "set_referral"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text("🎁 Enter new referral percentage (e.g. `5`):", reply_markup=kb, parse_mode="Markdown")


async def set_wait_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_action"] = "set_wait"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text("⏱ Enter new wait time in minutes (e.g. `5`):", reply_markup=kb, parse_mode="Markdown")


async def set_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["admin_action"] = "set_cancel"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text("⏳ Enter new cancel time in minutes (e.g. `2`):", reply_markup=kb, parse_mode="Markdown")


async def toggle_maintenance_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    settings = await get_settings()
    current = settings.get("maintenance_mode", False)
    await update_settings("maintenance_mode", not current)
    new_status = "🔴 ON — Users blocked" if not current else "🟢 OFF — Bot live"
    await query.answer(f"Maintenance: {new_status}", show_alert=True)
    await admin_settings_callback(update, context)


async def set_maintenance_msg_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    settings = await get_settings()
    current = settings.get("maintenance_message") or (
        "🛠 Bot Under Maintenance\n\n"
        "Hum thodi der mein wapas aayenge. Aapka balance aur order safe hai.\n\n"
        "Thanks for your patience! 🙏"
    )
    context.user_data["admin_action"] = "set_maintenance_msg"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        f"📝 *Maintenance Message Edit*\n\n"
        f"*Current:*\n{current}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Naya message bhej (Markdown supported). `default` likh ke default reset kar sake.",
        reply_markup=kb, parse_mode="Markdown"
    )


async def admin_alert_bots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all tracked bots in OTP group with per-bot alert toggle (✅/⬜)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_otp_group_id, get_tracked_bots
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import datetime as _dt

    gid_raw = await get_otp_group_id()
    if not gid_raw:
        await query.edit_message_text(
            "❌ *OTP Group Not Set*\n\nPehle settings mein OTP group set karo.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_settings")]]),
            parse_mode="Markdown"
        )
        return
    try:
        gid = int(gid_raw)
    except Exception:
        await query.edit_message_text(
            "❌ Invalid OTP group ID.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_settings")]])
        )
        return

    bots = await get_tracked_bots(group_id=gid)
    if not bots:
        await query.edit_message_text(
            "🤖 *No Bots Tracked Yet*\n\n"
            "Group mein abhi tak koi bot ka msg track nahi hua.\n"
            "Bots ke msg aane do, phir yahan list aa jayegi.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_settings")]]),
            parse_mode="Markdown"
        )
        return

    now = _dt.datetime.utcnow()
    enabled_count = sum(1 for b in bots if b.get("alert_enabled"))
    lines = [
        "🔔 *Per-Bot Alert Settings*",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"📊  Tracked: *{len(bots)}*  |  ✅ Alert ON: *{enabled_count}*",
        "",
        "_Sirf ✅ wale bots ke silent hone par DM alert aayega._",
        "_Toggle karne ke liye button dabao._",
        "",
    ]
    rows = []
    # Bulk actions
    rows.append([
        InlineKeyboardButton("✅ Enable All", callback_data="alert_all_on"),
        InlineKeyboardButton("⬜ Disable All", callback_data="alert_all_off"),
    ])
    rows.append([InlineKeyboardButton("───────────", callback_data="noop")])

    for b in bots[:30]:
        sid = b.get("sender_id")
        name = b.get("sender_name", "Unknown") or "Unknown"
        if name.startswith("user_") or name in ("Unknown", "BOOTSTRAP", "GROUP"):
            display = f"ID {sid}"
        else:
            display = f"@{name}"
        last = b.get("last_message_at")
        mins = int((now - last).total_seconds() / 60) if last else 9999
        if mins < 60:
            seen = f"{mins}m"
        elif mins < 1440:
            seen = f"{mins // 60}h"
        else:
            seen = f"{mins // 1440}d"
        emoji = "✅" if b.get("alert_enabled") else "⬜"
        label = f"{emoji} {display}  •  {seen} ago"
        rows.append([InlineKeyboardButton(label[:64], callback_data=f"alert_toggle_{sid}")])

    if len(bots) > 30:
        rows.append([InlineKeyboardButton(f"… +{len(bots) - 30} more (refresh later)", callback_data="noop")])
    rows.append([InlineKeyboardButton("🔄 Refresh", callback_data="admin_alert_bots")])
    rows.append([InlineKeyboardButton("🔙 Back to Settings", callback_data="admin_settings")])

    await query.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows), parse_mode="Markdown")


async def alert_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Flip alert_enabled for one bot."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    from database import get_otp_group_id, get_tracked_bots, set_bot_alert_enabled
    try:
        sid = int(query.data.replace("alert_toggle_", ""))
    except ValueError:
        await query.answer("Invalid toggle", show_alert=True)
        return
    gid_raw = await get_otp_group_id()
    if not gid_raw:
        await query.answer("OTP group not set", show_alert=True)
        return
    gid = int(gid_raw)
    bots = await get_tracked_bots(group_id=gid)
    target = next((b for b in bots if b.get("sender_id") == sid), None)
    if not target:
        await query.answer("Bot not found", show_alert=True)
        return
    new_state = not bool(target.get("alert_enabled"))
    await set_bot_alert_enabled(gid, sid, new_state)
    name = target.get("sender_name", str(sid))
    await query.answer(
        f"{'✅ Alert ON' if new_state else '⬜ Alert OFF'}  for  {name}",
        show_alert=False
    )
    await admin_alert_bots_callback(update, context)


async def alert_all_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bulk enable/disable alerts for ALL bots."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    from database import get_otp_group_id, set_all_bots_alert_enabled
    enable = query.data == "alert_all_on"
    gid_raw = await get_otp_group_id()
    if not gid_raw:
        await query.answer("OTP group not set", show_alert=True)
        return
    await set_all_bots_alert_enabled(int(gid_raw), enable)
    await query.answer(
        f"{'✅ Saare bots ke alerts ON' if enable else '⬜ Saare bots ke alerts OFF'}",
        show_alert=True
    )
    await admin_alert_bots_callback(update, context)


# ─────────────────────────────────────────────────────────────
# 🔥 FLASH SALE
# ─────────────────────────────────────────────────────────────

async def admin_flash_sale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show flash sale status panel."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_flash_sale
    from keyboards import flash_sale_panel_keyboard
    import datetime as _dt

    fs = await get_flash_sale()
    if fs:
        ends_at = fs.get("ends_at")
        mins_left = max(0, int((ends_at - _dt.datetime.utcnow()).total_seconds() / 60)) if ends_at else 0
        if mins_left >= 60:
            time_str = f"{mins_left // 60}h {mins_left % 60}m"
        else:
            time_str = f"{mins_left}m"
        if fs.get("all_services"):
            scope = "🌐 *ALL services*"
        else:
            names = fs.get("service_names") or []
            if not names:
                scope = "_(none)_"
            elif len(names) <= 6:
                scope = ", ".join(f"`{n}`" for n in names)
            else:
                scope = ", ".join(f"`{n}`" for n in names[:6]) + f"  + {len(names) - 6} more"
        text = (
            "🔥 *FLASH SALE — ACTIVE*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"💸 Discount: *{fs.get('discount_percent', 0):.0f}% OFF*\n"
            f"⏳ Time left: *{time_str}*\n"
            f"📦 Scope: {scope}\n\n"
            "_Discount automatically applied to user-facing prices._"
        )
        active = True
    else:
        text = (
            "🔥 *Flash Sale*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Status: ⬜ *Inactive*\n\n"
            "Limited-time discount banao — selected services par OR\n"
            "saare services par % off. Tap-tap se select karo.\n\n"
            "▶️ *Create Flash Sale* dabao start karne ke liye."
        )
        active = False

    await query.edit_message_text(
        text, reply_markup=flash_sale_panel_keyboard(active), parse_mode="Markdown"
    )


async def flash_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Step 1: ask for discount %."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "flash_set_discount"
    context.user_data.pop("flash_selected", None)
    context.user_data.pop("flash_all_mode", None)
    context.user_data.pop("flash_discount", None)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_flash_sale")]])
    await query.edit_message_text(
        "🔥 *Step 1 of 3 — Discount %*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Discount percentage bhej (1–95):\n\n"
        "Examples: `30` for 30% off, `50` for half-price.",
        reply_markup=kb, parse_mode="Markdown"
    )


async def flash_show_select(update_or_query, context: ContextTypes.DEFAULT_TYPE):
    """Render the multi-select services keyboard. Works from message OR callback."""
    from database import get_services
    from keyboards import flash_select_keyboard
    services = await get_services()
    services.sort(key=lambda s: s.get("name", "").lower())
    selected = context.user_data.setdefault("flash_selected", set())
    all_mode = context.user_data.setdefault("flash_all_mode", False)
    disc = context.user_data.get("flash_discount", 0)
    text = (
        "🔥 *Step 2 of 3 — Select Services*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💸 Discount: *{disc:.0f}% OFF*\n\n"
        "Tap karke select/deselect karo.\n"
        "🌐 *ALL Services* dabane par sab pe lag jayega.\n\n"
        "Done ho jaye toh ✅ *Confirm* dabao."
    )
    kb = flash_select_keyboard(services, selected, all_mode)
    if hasattr(update_or_query, "edit_message_text"):
        await update_or_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update_or_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


async def flash_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle service selection or 'all' or confirm."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    data = query.data
    if data == "flash_pick_all":
        context.user_data["flash_all_mode"] = not context.user_data.get("flash_all_mode", False)
        await query.answer("🌐 ALL toggled")
        await flash_show_select(query, context)
        return
    if data == "flash_pick_confirm":
        all_mode = context.user_data.get("flash_all_mode", False)
        selected = context.user_data.get("flash_selected", set())
        if not all_mode and not selected:
            await query.answer("❌ Pehle koi service select karo (ya ALL toggle karo)", show_alert=True)
            return
        await query.answer()
        context.user_data["admin_action"] = "flash_set_duration"
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_flash_sale")]])
        scope = "🌐 ALL services" if all_mode else f"{len(selected)} services"
        disc = context.user_data.get("flash_discount", 0)
        await query.edit_message_text(
            "🔥 *Step 3 of 3 — Duration*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"💸 {disc:.0f}% OFF on {scope}\n\n"
            "Duration kitne minutes? (1–10080 = up to 7 days)\n\n"
            "Examples: `30` (30 min), `60` (1 hour), `1440` (1 day).",
            reply_markup=kb, parse_mode="Markdown"
        )
        return
    # Individual service toggle
    name = data.replace("flash_pick_", "", 1)
    selected = context.user_data.setdefault("flash_selected", set())
    if not isinstance(selected, set):
        selected = set(selected)
    if name in selected:
        selected.remove(name)
        await query.answer(f"➖ {name} removed")
    else:
        selected.add(name)
        await query.answer(f"➕ {name} added")
    context.user_data["flash_selected"] = selected
    await flash_show_select(query, context)


async def flash_stop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import stop_flash_sale
    await stop_flash_sale()
    await query.answer("🛑 Flash sale stopped", show_alert=True)
    await admin_flash_sale_callback(update, context)


# ─────────────────────────────────────────────────────────────
# 💎 TOP-UP BONUS
# ─────────────────────────────────────────────────────────────

async def admin_topup_bonus_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_topup_slabs
    from keyboards import topup_bonus_keyboard

    slabs = await get_topup_slabs()
    if slabs:
        body_lines = [f"📊  *Active slabs:* {len(slabs)}", ""]
        for s in slabs:
            mn = float(s.get("min", 0)); mx = float(s.get("max", 0)); pct = float(s.get("bonus_pct", 0))
            body_lines.append(f"  • ₹{mn:g}–₹{mx:g}  →  *+{pct:g}%* extra")
        body = "\n".join(body_lines)
    else:
        body = (
            "_No slabs configured yet._\n\n"
            "Slab add karne par users ko deposit pe extra bonus milega.\n"
            "Example: ₹100–₹499 = 10% bonus → user ₹100 deposit kare toh ₹110 milta hai."
        )
    text = (
        "💎 *Top-up Bonus Slabs*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"{body}\n\n"
        "_Multiple slabs match hone par highest one apply hota hai._\n"
        "_Bonus user ke balance mein add hota hai (total\\_deposit mein nahi)._"
    )
    await query.edit_message_text(text, reply_markup=topup_bonus_keyboard(slabs), parse_mode="Markdown")


async def topup_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "topup_add_slab"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_topup_bonus")]])
    await query.edit_message_text(
        "💎 *Add Top-up Bonus Slab*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Format: `min | max | bonus_pct`\n\n"
        "*Examples:*\n"
        "`100 | 499 | 10`   → ₹100–499 deposit pe 10% extra\n"
        "`500 | 999 | 15`   → ₹500–999 deposit pe 15% extra\n"
        "`1000 | 99999 | 20` → ₹1000+ deposit pe 20% extra\n\n"
        "_Tip: large max value (e.g. 99999) use kar last slab ke liye._",
        reply_markup=kb, parse_mode="Markdown"
    )


async def topup_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    from database import delete_topup_slab
    try:
        idx = int(query.data.replace("topup_del_", ""))
    except ValueError:
        await query.answer("Invalid", show_alert=True)
        return
    ok = await delete_topup_slab(idx)
    await query.answer("🗑 Slab removed" if ok else "❌ Failed", show_alert=True)
    await admin_topup_bonus_callback(update, context)


async def topup_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import clear_topup_slabs
    await clear_topup_slabs()
    await query.answer("🗑 All slabs cleared", show_alert=True)
    await admin_topup_bonus_callback(update, context)


async def toggle_health_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    settings = await get_settings()
    current = settings.get("health_enabled", True)
    await update_settings("health_enabled", not current)
    new_status = "🟢 ON" if not current else "🔴 OFF"
    await query.answer(f"Health Monitor: {new_status}", show_alert=True)
    # Refresh settings panel
    await admin_settings_callback(update, context)


async def set_health_threshold_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "set_health_threshold"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        "⏰ *Silence Threshold*\n\n"
        "Group itne minute silent ho to alert aayega.\n"
        "Default: `10` minutes.\n\n"
        "Enter number (e.g. `10`, `15`, `30`):",
        reply_markup=kb, parse_mode="Markdown"
    )


async def set_health_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "set_health_reminder"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        "🔔 *Reminder Gap*\n\n"
        "Itne minute baad dobara alert aayega jab tak group silent rahega.\n"
        "Default: `4` minutes (recommended: 4-10).\n\n"
        "Enter number:",
        reply_markup=kb, parse_mode="Markdown"
    )


async def set_health_window_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "set_health_window"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        "🤖 *Bot Active Window*\n\n"
        "Sirf un forwarder bots ka alert aayega jo *itne minute ke andar* active the.\n"
        "Purane bots ignore honge.\n"
        "Default: `60` minutes.\n\n"
        "Enter number:",
        reply_markup=kb, parse_mode="Markdown"
    )


async def set_first_buy_disc_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "set_first_buy_disc"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        "🆕 *First-Buy Discount %*\n\n"
        "Enter a number 0-100 (e.g. `50` = 50% off first OTP, `0` = disabled).\n\n"
        "Discount applies to *every user's first OTP only* — once.",
        reply_markup=kb, parse_mode="Markdown"
    )


async def set_cache_size_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import (
        get_recent_devices_cache_size, get_recent_device_ids_db,
        MIN_RECENT_DEVICES_CACHE_SIZE, MAX_RECENT_DEVICES_CACHE_SIZE
    )
    current = await get_recent_devices_cache_size()
    cached_now = await get_recent_device_ids_db()
    context.user_data["admin_action"] = "set_cache_size"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        "🧠 *Smart Match Cache Size*\n\n"
        f"Current: *{current}* slots  ({len(cached_now)} cached right now)\n\n"
        "Group ke last N messages ka *device_id* yaad rakha jaata hai. "
        "Buy ke time agar stock mein usi device ka number ho to *priority* se diya jaata hai "
        "(zyada chance OTP mile, kyunki woh device abhi active hai).\n\n"
        f"Naya number bhej (range *{MIN_RECENT_DEVICES_CACHE_SIZE}–{MAX_RECENT_DEVICES_CACHE_SIZE}*):\n"
        "• Chhota (e.g. `10`) → sirf abhi-abhi active devices\n"
        "• Bada (e.g. `50`) → zyada devices yaad, better matching\n"
        "• Bahut bada (e.g. `200`) → almost all recent devices",
        reply_markup=kb, parse_mode="Markdown"
    )


async def admin_export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    users = await get_all_users()
    users_with_balance = [u for u in users if u.get("balance", 0) > 0]
    total_liability = sum(u.get("balance", 0) for u in users_with_balance)

    text = f"🧾 *Data Export*\n\nTotal Users: {len(users)}\n\n"
    text += f"*Users with Balance:*\n"
    for u in users_with_balance[:30]:
        text += f"ID: `{u['user_id']}` → {format_balance(u['balance'])}\n"
    text += f"\n*Total Liability: {format_balance(total_liability)}*"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
    await query.edit_message_text(text[:4000], reply_markup=kb, parse_mode="Markdown")





async def admin_restore_balances_callback(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    context.user_data["admin_action"] = "restore_balances"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]])
    await query.edit_message_text(
        "📤 *Balance Restore*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "Ab backup JSON file bhejo jo `📥 Users Export` se download ki thi.\n\n"
        "⚠️ _Sirf wahi users ka balance update hoga jinke backup mein balance > 0 hai._\n"
        "_Naye users create nahi honge — sirf existing users update honge._",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def handle_restore_backup_file(update, context):
    if not is_admin(update.effective_user.id):
        return
    if context.user_data.get("admin_action") != "restore_balances":
        return
    import json, io
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    doc = update.message.document
    if not doc or not doc.file_name.endswith(".json"):
        await update.message.reply_text(
            "❌ *Sirf JSON file bhejo.*\n`users_backup_*.json` file chahiye.",
            parse_mode="Markdown"
        )
        return

    context.user_data.pop("admin_action", None)

    wait_msg = await update.message.reply_text(
        "⏳ *Backup file process ho rahi hai...*\nPlease wait...",
        parse_mode="Markdown"
    )

    try:
        file = await context.bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        buf.seek(0)
        data = json.loads(buf.read().decode("utf-8"))
    except Exception as e:
        await wait_msg.edit_text(f"❌ File read error: `{str(e)[:200]}`", parse_mode="Markdown")
        return

    if not isinstance(data, dict):
        await wait_msg.edit_text("❌ Invalid format. JSON object expected.", parse_mode="Markdown")
        return

    restored = 0
    skipped = 0
    errors = 0
    total_restored_bal = 0.0

    for uid_str, udata in data.items():
        try:
            bal = float(udata.get("balance", 0) or 0)
            if bal <= 0:
                skipped += 1
                continue
            uid = int(uid_str)
            existing = await get_user(uid)
            if not existing:
                skipped += 1
                continue
            current_bal = float(existing.get("balance", 0) or 0)
            if current_bal >= bal:
                skipped += 1
                continue
            await update_user_balance(uid, bal)
            restored += 1
            total_restored_bal += bal
        except Exception:
            errors += 1

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
    await wait_msg.edit_text(
        f"✅ *Balance Restore Complete!*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Restored: *{restored}* users\n"
        f"💰 Total balance restored: *{format_balance(total_restored_bal)}*\n"
        f"⏭ Skipped: *{skipped}* (no balance / already higher / not found)\n"
        f"❌ Errors: *{errors}*",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def admin_users_export_callback(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    import json, io, datetime
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    await query.edit_message_text("⏳ *Users data export ho raha hai...*\nPlease wait...", parse_mode="Markdown")

    users = await get_all_users()
    export_data = {}
    for u in users:
        uid = str(u.get('user_id', ''))
        if not uid:
            continue
        export_data[uid] = {
            "id": u.get('user_id'),
            "username": u.get('username') or None,
            "first_name": u.get('first_name') or u.get('name') or 'Unknown',
            "joined": u.get('joined').isoformat() if hasattr(u.get('joined'), 'isoformat') else str(u.get('joined', '')),
            "balance": round(float(u.get('balance', 0) or 0), 2),
            "total_deposit": round(float(u.get('total_deposit', 0) or 0), 2),
            "total_spent": round(float(u.get('total_spent', 0) or 0), 2),
            "referrer_id": u.get('referrer_id') or None,
            "referral_earnings": round(float(u.get('referral_earnings', 0) or 0), 2),
            "is_banned": bool(u.get('is_banned', False)),
            "channel_verified": bool(u.get('channel_verified', False)),
        }

    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
    filename = f"users_backup_{now_str}.json"
    json_bytes = json.dumps(export_data, ensure_ascii=False, indent=2).encode('utf-8')
    file_obj = io.BytesIO(json_bytes)
    file_obj.name = filename

    total_bal = sum(v['balance'] for v in export_data.values() if v['balance'] > 0)
    caption = (
        f"📥 *Users Data Export*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👥 Total users: *{len(export_data)}*\n"
        f"💰 Total wallet balance: *{format_balance(total_bal)}*\n"
        f"🕒 Exported at: `{now_str} UTC`\n\n"
        f"_Yeh file backup ke liye safe rakh lo._"
    )

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
    await context.bot.send_document(
        chat_id=query.from_user.id,
        document=file_obj,
        filename=filename,
        caption=caption,
        parse_mode="Markdown",
        reply_markup=kb
    )
    await query.edit_message_text(
        f"✅ *Export complete!*\n\n{len(export_data)} users ka data file mein bhej diya.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def admin_wallet_balances_callback(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    users = await get_all_users()
    users_with_balance = [u for u in users if float(u.get('balance', 0) or 0) > 0]
    users_with_balance.sort(key=lambda u: float(u.get('balance', 0) or 0), reverse=True)
    total_liability = sum(float(u.get('balance', 0) or 0) for u in users_with_balance)

    if not users_with_balance:
        text = (
            "💳 *Wallet Balances*\n\n"
            "✅ Kisi bhi user ke wallet mein abhi paisa nahi hai."
        )
    else:
        text = (
            f"💳 *Wallet Balances*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 *Total users with balance:* {len(users_with_balance)}\n"
            f"💰 *Total liability:* {format_balance(total_liability)}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
        for i, u in enumerate(users_with_balance, 1):
            uid = u.get('user_id', 'N/A')
            name = u.get('name') or u.get('first_name') or 'Unknown'
            bal = float(u.get('balance', 0) or 0)
            text += f"{i}. {name} | `{uid}` → *{format_balance(bal)}*\n"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
    await query.edit_message_text(text[:4096], reply_markup=kb, parse_mode="Markdown")


async def admin_top_spenders_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    spenders = await get_top_spenders(10)
    if not spenders:
        text = "🏆 *Top Spenders*\n\nAbhi tak kisi ne kuch spend nahi kiya."
    else:
        text = "🏆 *Top 10 Spenders*\n\n"
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
        for i, u in enumerate(spenders):
            uid = u["user_id"]
            name = u.get("first_name") or "User"
            spent = u.get("total_spent", 0)
            bal = u.get("balance", 0)
            medal = medals[i] if i < len(medals) else f"{i+1}."
            text += f"{medal} {name} (`{uid}`)\n    💸 Spent: {format_balance(spent)} | 💰 Bal: {format_balance(bal)}\n\n"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]])
    await query.edit_message_text(text[:4000], reply_markup=kb, parse_mode="Markdown")


async def admin_reset_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    stats = await get_stats()
    text = (
        f"⚠️ *Reset All Stats*\n\n"
        f"Yeh action yeh sab delete/reset karega:\n\n"
        f"• 📜 Saare logs ({stats['total_otp']} OTP + deposits + cancels)\n"
        f"• 📦 Completed/cancelled sessions\n"
        f"• 👥 Har user ka: total deposit, total spent, referral earning, referral count\n\n"
        f"*Yeh nahi hoga:*\n"
        f"• ❌ Users delete nahi honge\n"
        f"• ❌ Current balances zero nahi honge\n"
        f"• ❌ Stock delete nahi hoga\n\n"
        f"Pakka karna chahte ho?"
    )
    await query.edit_message_text(text, reply_markup=reset_stats_confirm_keyboard(), parse_mode="Markdown")


async def admin_reset_stats_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    await reset_all_stats()
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin Panel", callback_data="admin_back")]])
    await query.edit_message_text(
        "✅ *Stats Reset Ho Gaya!*\n\n"
        "Saare logs, sessions history, aur user stats clear ho gaye.\n"
        "Users, balances aur stock safe hain.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def admin_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    mode = await get_mode()
    await query.edit_message_text(
        f"🔁 *Mode Control*\n\nCurrent mode: *{mode.upper()}*\n\nSelect mode:",
        reply_markup=admin_mode_keyboard(mode),
        parse_mode="Markdown"
    )


async def mode_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    mode = "auto" if query.data == "mode_auto" else "manual"
    await set_mode(mode)
    await query.edit_message_text(
        f"✅ Mode set to *{mode.upper()}*",
        reply_markup=admin_mode_keyboard(mode),
        parse_mode="Markdown"
    )


async def admin_manual_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    await query.edit_message_text(
        "✋ *Manual Control*\n\nSelect action:",
        reply_markup=admin_manual_keyboard(),
        parse_mode="Markdown"
    )


async def manual_number_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "manual_number"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_manual")]])
    await query.edit_message_text(
        "📱 *Send Number*\n\nFormat:\n`USER_ID | NUMBER | DEVICE_ID`\n\nDevice ID optional hai (stock se auto-match bhi hoga)\n\nExample:\n`123456789 | +919876543210 | f95190e4fbd9e50a`",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def manual_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "manual_otp"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_manual")]])
    await query.edit_message_text(
        "🔑 *Send OTP*\n\nFormat:\n`USER_ID | OTP MESSAGE`\n\nExample:\n`123456789 | 123456 is your Myntra OTP`",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def ban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.replace("ban_", ""))
    await ban_user(user_id)
    db_user = await get_user(user_id)
    await query.edit_message_text(
        f"✅ User `{user_id}` has been banned.",
        reply_markup=user_actions_keyboard(user_id, True),
        parse_mode="Markdown"
    )


async def unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.replace("unban_", ""))
    await unban_user(user_id)
    await query.edit_message_text(
        f"✅ User `{user_id}` has been unbanned.",
        reply_markup=user_actions_keyboard(user_id, False),
        parse_mode="Markdown"
    )


async def addbal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.replace("addbal_", ""))
    context.user_data["admin_action"] = "add_balance"
    context.user_data["target_user"] = user_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_users")]])
    await query.edit_message_text(
        f"➕ Enter amount to add to user `{user_id}`:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def dedbal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.replace("dedbal_", ""))
    context.user_data["admin_action"] = "ded_balance"
    context.user_data["target_user"] = user_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_users")]])
    await query.edit_message_text(
        f"➖ Enter amount to deduct from user `{user_id}`:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    action = context.user_data.get("admin_action")
    text = update.message.text.strip()

    if action == "remove_stock_number":
        number = text.strip()
        service = context.user_data.get("stock_service", "")
        stock = await get_stock(service if service else None)
        numbers_in_stock = [s["number"] for s in stock]
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        back_cb = f"stock_svc_{service}" if service else "admin_stock"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=back_cb)]])
        if number not in numbers_in_stock:
            await update.message.reply_text(
                f"❌ `{number}` stock mein nahi mila.",
                reply_markup=kb,
                parse_mode="Markdown"
            )
        else:
            await delete_number_from_stock(number)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ `{number}` stock se remove kar diya gaya.",
                reply_markup=kb,
                parse_mode="Markdown"
            )

    elif action == "add_stock":
        service = context.user_data.get("stock_service", "Myntra")
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        added = []
        skipped = []
        for line in lines:
            if "|" not in line:
                skipped.append(f"`{line[:30]}` — missing `|`")
                continue
            parts = line.split("|", 1)
            number = parts[0].strip()
            device_id = parts[1].strip()
            if not number or not device_id:
                skipped.append(f"`{line[:30]}` — empty field")
                continue
            try:
                await add_stock(number, device_id, service)
                added.append(f"`{number}`")
            except Exception as e:
                skipped.append(f"`{number}` — {str(e)[:40]}")

        context.user_data.pop("admin_action", None)
        msg = f"📦 *{service} Stock Update*\n\n✅ Added {len(added)}: {', '.join(added) if added else 'none'}\n"
        if skipped:
            msg += f"⚠️ Skipped {len(skipped)}:\n" + "\n".join(skipped)
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Stock", callback_data=f"stock_svc_{service}")]])
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

    elif action == "approve_deposit":
        try:
            amount = float(text)
            deposit_id = context.user_data.get("deposit_id")
            dep = await approve_deposit(deposit_id, amount)
            if dep:
                from database import compute_topup_bonus, credit_topup_bonus
                settings = await get_settings()
                ref_percent = settings.get("referral_percent", 5)
                db_user = await get_user(dep["user_id"])

                # 💎 Apply top-up bonus slab
                bonus_amt, bonus_pct = await compute_topup_bonus(amount)
                if bonus_amt > 0:
                    await credit_topup_bonus(dep["user_id"], bonus_amt)
                    await add_log("topup_bonus", {
                        "user_id": dep["user_id"], "deposit": amount,
                        "bonus": bonus_amt, "bonus_pct": bonus_pct
                    })

                if db_user and db_user.get("referrer_id"):
                    bonus = amount * ref_percent / 100
                    await add_referral_bonus(db_user["referrer_id"], bonus)
                    await add_log("referral_bonus", {
                        "user_id": db_user["referrer_id"],
                        "from_user": dep["user_id"],
                        "amount": bonus
                    })
                    try:
                        await context.bot.send_message(
                            chat_id=db_user["referrer_id"],
                            text=f"🎁 Referral bonus! You earned {format_balance(bonus)} from a deposit.",
                            reply_markup=main_menu_keyboard()
                        )
                    except:
                        pass

                await add_log("deposit_approved", {"user_id": dep["user_id"], "amount": amount, "bonus": bonus_amt})

                # User notification with bonus highlight
                if bonus_amt > 0:
                    total_credited = amount + bonus_amt
                    user_msg = (
                        f"✅ *Deposit Approved!*\n"
                        f"━━━━━━━━━━━━━━━━━━\n\n"
                        f"💵  Deposit:  *{format_balance(amount)}*\n"
                        f"💎  Bonus ({bonus_pct:g}%):  *+{format_balance(bonus_amt)}*\n"
                        f"━━━━━━━━━━━━━━━━━━\n"
                        f"💰  *Total credited:  {format_balance(total_credited)}*"
                    )
                else:
                    user_msg = f"✅ Deposit of {format_balance(amount)} approved and added to your balance!"
                try:
                    await context.bot.send_message(
                        chat_id=dep["user_id"], text=user_msg,
                        reply_markup=main_menu_keyboard(), parse_mode="Markdown"
                    )
                except:
                    pass

            context.user_data.pop("admin_action", None)
            context.user_data.pop("deposit_id", None)
            admin_msg = f"✅ Deposit approved. {format_balance(amount)} added."
            if dep and bonus_amt > 0:
                admin_msg += f" (+ 💎 {format_balance(bonus_amt)} bonus = {format_balance(amount + bonus_amt)} total)"
            await update.message.reply_text(admin_msg, reply_markup=admin_main_keyboard())
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}\n\nEnter a valid amount (e.g. `50`).", parse_mode="Markdown")

    elif action == "approve_refund":
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError("amount must be positive")
            refund_id = context.user_data.get("refund_id")
            doc = await approve_refund_request(refund_id, amount)
            if not doc:
                await update.message.reply_text("❌ Refund not found ya already processed.")
                context.user_data.pop("admin_action", None)
                context.user_data.pop("refund_id", None)
                return
            await add_log("refund_approved", {
                "user_id": doc["user_id"], "amount": amount, "refund_id": refund_id
            })
            try:
                await context.bot.send_message(
                    chat_id=doc["user_id"],
                    text=(
                        f"✅ *Refund Approved!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"💰 {format_balance(amount)} aapke balance me add ho gaye.\n\n"
                        f"━━━━━━━━━━━━━━━━━━━━"
                    ),
                    reply_markup=main_menu_keyboard(),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            context.user_data.pop("admin_action", None)
            context.user_data.pop("refund_id", None)
            await update.message.reply_text(
                f"✅ Refund approved. {format_balance(amount)} credited to user `{doc['user_id']}`.",
                reply_markup=admin_main_keyboard(),
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Invalid amount: {e}\n\nValid number enter karo (e.g. `5`).",
                parse_mode="Markdown"
            )

    elif action == "reject_refund":
        reason = text.strip() or "No reason provided"
        refund_id = context.user_data.get("refund_id")
        doc = await reject_refund_request(refund_id, reason)
        if not doc:
            await update.message.reply_text("❌ Refund not found ya already processed.")
            context.user_data.pop("admin_action", None)
            context.user_data.pop("refund_id", None)
            return
        await add_log("refund_rejected", {
            "user_id": doc["user_id"], "reason": reason, "refund_id": refund_id
        })
        try:
            await context.bot.send_message(
                chat_id=doc["user_id"],
                text=(
                    f"❌ *Refund Rejected*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📝 Reason: {reason}\n\n"
                    f"Help chahiye toh support se contact karo.\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━"
                ),
                reply_markup=main_menu_keyboard(),
                parse_mode="Markdown"
            )
        except Exception:
            pass
        context.user_data.pop("admin_action", None)
        context.user_data.pop("refund_id", None)
        await update.message.reply_text(
            f"❌ Refund rejected for user `{doc['user_id']}`.",
            reply_markup=admin_main_keyboard(),
            parse_mode="Markdown"
        )

    elif action == "search_user":
        try:
            import re as _re
            cleaned = _re.sub(r'[^\d]', '', text)
            uid = int(cleaned)
            db_user = await get_user(uid)
            if not db_user:
                await update.message.reply_text(f"User {uid} not found.")
                return
            session = await get_session(uid)
            active_order = "None"
            if session:
                num = session.get("number", "N/A")
                dev_id = session.get("device_id", "N/A")
                active_order = f"Number: {num} | Device: {dev_id}"

            join_date = db_user.get("join_date", datetime.datetime.utcnow()).strftime("%d %b %Y")
            uname = db_user.get("username") or ""
            uname_str = f"@{uname}" if uname else "None"
            text_out = (
                f"👤 User Info\n\n"
                f"🆔 User ID: {uid}\n"
                f"👤 Name: {db_user.get('first_name', 'N/A')}\n"
                f"📛 Username: {uname_str}\n"
                f"💰 Balance: {format_balance(db_user.get('balance', 0))}\n"
                f"📦 Active Order: {active_order}\n"
                f"💸 Total Deposited: {format_balance(db_user.get('total_deposit', 0))}\n"
                f"🛒 Total Spent: {format_balance(db_user.get('total_spent', 0))}\n"
                f"🎁 Referral Earning: {format_balance(db_user.get('referral_earning', 0))}\n"
                f"👥 Referrals: {db_user.get('total_referrals', 0)}\n"
                f"🗓 Joined: {join_date}\n"
                f"🚫 Banned: {'Yes' if db_user.get('banned') else 'No'}"
            )
            await update.message.reply_text(
                text_out,
                reply_markup=user_actions_keyboard(uid, db_user.get("banned", False))
            )
            context.user_data.pop("admin_action", None)
        except Exception as e:
            await update.message.reply_text(
                f"Could not find user. Enter a plain numeric ID (e.g. 6928507193). Error: {e}"
            )

    elif action == "add_balance":
        try:
            amount = float(text)
            target = context.user_data.get("target_user")
            await update_user_balance(target, amount)
            context.user_data.pop("admin_action", None)
            context.user_data.pop("target_user", None)
            await update.message.reply_text(
                f"✅ Added {format_balance(amount)} to user `{target}`.",
                parse_mode="Markdown"
            )
        except:
            await update.message.reply_text("❌ Invalid amount.")

    elif action == "ded_balance":
        try:
            amount = float(text)
            target = context.user_data.get("target_user")
            await deduct_balance(target, amount)
            context.user_data.pop("admin_action", None)
            context.user_data.pop("target_user", None)
            await update.message.reply_text(
                f"✅ Deducted {format_balance(amount)} from user `{target}`.",
                parse_mode="Markdown"
            )
        except:
            await update.message.reply_text("❌ Invalid amount.")

    elif action == "add_note":
        target = context.user_data.get("target_user")
        context.user_data.pop("admin_action", None)
        context.user_data.pop("target_user", None)
        if not target:
            await update.message.reply_text("❌ Target user nahi mila.")
            return
        await add_user_note(target, update.effective_user.id, text)
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Notes Dekho", callback_data=f"notes_{target}")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
        ])
        await update.message.reply_text(
            f"✅ Note save ho gaya user `{target}` ke liye!",
            reply_markup=kb,
            parse_mode="Markdown"
        )

    elif action == "broadcast":
        users = await get_all_users()
        success = 0
        fail = 0
        for user in users:
            try:
                await context.bot.send_message(chat_id=user["user_id"], text=text)
                success += 1
            except:
                fail += 1
        context.user_data.pop("admin_action", None)
        await update.message.reply_text(
            f"📢 Broadcast done.\n✅ Sent: {success}\n❌ Failed: {fail}",
            reply_markup=admin_main_keyboard()
        )

    elif action == "set_price":
        try:
            val = float(text)
            await update_settings("otp_price", val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(f"✅ OTP price set to {format_balance(val)}.", reply_markup=admin_main_keyboard())
        except:
            await update.message.reply_text("❌ Invalid value. Enter a number like `5.00`", parse_mode="Markdown")

    elif action == "set_upi":
        new_upi = text.strip()
        # Basic UPI validation: must contain '@' and have non-empty parts
        if "@" not in new_upi or len(new_upi) < 5 or " " in new_upi:
            await update.message.reply_text(
                "❌ Invalid UPI ID. Format hona chahiye `name@bank` (e.g. `9876543210@ybl`).",
                parse_mode="Markdown"
            )
        else:
            await set_upi_id(new_upi)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ UPI ID updated to:\n`{new_upi}`\n\nDeposit screen pe turant naya UPI dikhega.",
                reply_markup=admin_main_keyboard(),
                parse_mode="Markdown"
            )

    elif action == "set_min_deposit":
        try:
            val = float(text)
            if val <= 0:
                raise ValueError("must be positive")
            await set_min_deposit(val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ Minimum deposit set to *₹{val:.0f}*.",
                reply_markup=admin_main_keyboard(),
                parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ Invalid amount. Enter a positive number like `10`, `50`, `100`.", parse_mode="Markdown")

    elif action == "set_service_otp_count":
        service_id = context.user_data.get("svc_otpcount_id", "")
        try:
            count = int(text.strip())
            if count < 1 or count > 10:
                raise ValueError("out of range")
            from database import update_service_otp_count
            await update_service_otp_count(service_id, count)
            context.user_data.pop("admin_action", None)
            context.user_data.pop("svc_otpcount_id", None)
            services = await get_services()
            await update.message.reply_text(
                f"✅ OTP count set to *{count}* per order.",
                reply_markup=admin_services_keyboard(services),
                parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ Invalid value. 1 se 10 ke beech ka number do.")

    elif action == "set_service_otp_digits":
        service_id = context.user_data.get("svc_otpdigits_id", "")
        try:
            parts = [p.strip() for p in text.split(",") if p.strip()]
            digits = []
            for p in parts:
                d = int(p)
                if d < 3 or d > 9:
                    raise ValueError(f"Invalid digit length: {d} (3-9 ke beech hona chahiye)")
                digits.append(d)
            if not digits:
                raise ValueError("Koi valid digit nahi mili")
            digits = sorted(set(digits))
            from database import update_service_otp_digits
            await update_service_otp_digits(service_id, digits)
            context.user_data.pop("admin_action", None)
            context.user_data.pop("svc_otpdigits_id", None)
            services = await get_services()
            digits_str = ", ".join(str(d) for d in digits)
            await update.message.reply_text(
                f"✅ OTP digit lengths set: *{digits_str}*\n\nAb is service ke {digits_str} digit wale OTP accept honge.",
                reply_markup=admin_services_keyboard(services),
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Error: {e}\n\nExample: `4, 5, 6` ya sirf `6` ya `4, 6`",
                parse_mode="Markdown"
            )

    elif action == "add_service_keyword":
        service_id = context.user_data.get("svc_kw_id", "")
        try:
            kw = text.strip().lower()
            if not kw:
                raise ValueError("Keyword empty hai")
            from database import add_service_keyword
            await add_service_keyword(service_id, kw)
            context.user_data.pop("admin_action", None)
            from bson import ObjectId
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            svc = await _database.db.services.find_one({"_id": ObjectId(service_id)})
            kws = svc.get("keywords", []) if svc else []
            rows = []
            for k in kws:
                rows.append([
                    InlineKeyboardButton(f"🔑 {k}", callback_data="noop"),
                    InlineKeyboardButton("❌ Remove", callback_data=f"svc_kw_del_{service_id}|{k}"),
                ])
            rows.append([InlineKeyboardButton("➕ Add Keyword", callback_data=f"svc_kw_add_{service_id}")])
            rows.append([InlineKeyboardButton("🔙 Back", callback_data="admin_services")])
            kw_list = "\n".join(f"  • `{k}`" for k in kws) if kws else "  _No keywords set_"
            svc_name = svc.get("name", "?") if svc else "?"
            await update.message.reply_text(
                f"✅ Keyword `{kw}` add ho gaya!\n\n"
                f"🔑 *{svc_name}* ke keywords:\n{kw_list}",
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}", parse_mode="Markdown")

    elif action == "set_service_price":
        service_id = context.user_data.get("svc_price_id", "")
        try:
            if text.strip().lower() == "default":
                await update_service_price(service_id, None)
                context.user_data.pop("admin_action", None)
                context.user_data.pop("svc_price_id", None)
                services = await get_services()
                await update.message.reply_text("✅ Service price reset to default (global price).", reply_markup=admin_services_keyboard(services))
            else:
                val = float(text)
                await update_service_price(service_id, val)
                context.user_data.pop("admin_action", None)
                context.user_data.pop("svc_price_id", None)
                services = await get_services()
                await update.message.reply_text(f"✅ Service price set to {format_balance(val)}.", reply_markup=admin_services_keyboard(services))
        except:
            await update.message.reply_text("❌ Invalid value. Enter a number like `8.00`", parse_mode="Markdown")

    elif action == "set_referral":
        try:
            val = float(text)
            await update_settings("referral_percent", val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(f"✅ Referral % set to {val}%.", reply_markup=admin_main_keyboard())
        except:
            await update.message.reply_text("❌ Invalid value.")

    elif action == "set_wait":
        try:
            val = int(text)
            await update_settings("wait_time", val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(f"✅ Wait time set to {val} minutes.", reply_markup=admin_main_keyboard())
        except:
            await update.message.reply_text("❌ Invalid value.")

    elif action == "set_cancel":
        try:
            val = int(text)
            await update_settings("cancel_time", val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(f"✅ Cancel time set to {val} minutes.", reply_markup=admin_main_keyboard())
        except:
            await update.message.reply_text("❌ Invalid value.")

    elif action == "set_maintenance_msg":
        try:
            new_msg = text.strip()
            if new_msg.lower() == "default":
                await update_settings("maintenance_message", None)
                context.user_data.pop("admin_action", None)
                await update.message.reply_text(
                    "✅ Maintenance message reset to default.",
                    reply_markup=admin_main_keyboard()
                )
            else:
                if len(new_msg) < 5 or len(new_msg) > 1500:
                    await update.message.reply_text("❌ Message 5-1500 characters ke beech hona chahiye.")
                    return
                await update_settings("maintenance_message", new_msg)
                context.user_data.pop("admin_action", None)
                await update.message.reply_text(
                    f"✅ *Maintenance message updated.*\n\n*Preview:*\n{new_msg}",
                    reply_markup=admin_main_keyboard(),
                    parse_mode="Markdown"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")

    elif action == "set_health_threshold":
        try:
            val = int(text)
            if val < 1 or val > 1440:
                raise ValueError("range")
            await update_settings("health_threshold_min", val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ Silence threshold set to {val} minutes.\nGroup itne min silent ho to alert aayega.",
                reply_markup=admin_main_keyboard()
            )
        except:
            await update.message.reply_text("❌ Invalid value. Enter a number between 1 and 1440.")

    elif action == "set_health_reminder":
        try:
            val = int(text)
            if val < 1 or val > 1440:
                raise ValueError("range")
            await update_settings("health_reminder_min", val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ Reminder gap set to {val} minutes.\nItne min baad dobara alert aayega.",
                reply_markup=admin_main_keyboard()
            )
        except:
            await update.message.reply_text("❌ Invalid value. Enter a number between 1 and 1440.")

    elif action == "set_health_window":
        try:
            val = int(text)
            if val < 5 or val > 10080:
                raise ValueError("range")
            await update_settings("health_bot_window_min", val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ Bot active window set to {val} minutes.\nSirf is window mein active bots ka alert milega.",
                reply_markup=admin_main_keyboard()
            )
        except:
            await update.message.reply_text("❌ Invalid value. Enter a number between 5 and 10080.")

    elif action == "create_promo":
        try:
            parts = [p.strip() for p in text.split("|")]
            if len(parts) != 3:
                raise ValueError("need 3 parts")
            code_str, amount_str, max_str = parts
            amount = float(amount_str)
            max_claims = int(max_str)
            if amount <= 0:
                raise ValueError("amount must be > 0")
            if max_claims < 0:
                raise ValueError("max_claims must be >= 0")
            if not code_str or len(code_str) > 30 or " " in code_str:
                raise ValueError("invalid code")
            from database import create_promo_code, list_promo_codes
            from keyboards import admin_promos_keyboard
            promo = await create_promo_code(code_str, amount, max_claims, update.effective_user.id)
            context.user_data.pop("admin_action", None)
            if promo is None:
                codes = await list_promo_codes()
                await update.message.reply_text(
                    f"❌ Code `{code_str.upper()}` already exists. Different name use kar.",
                    reply_markup=admin_promos_keyboard(codes),
                    parse_mode="Markdown"
                )
            else:
                codes = await list_promo_codes()
                max_disp = "Unlimited" if max_claims == 0 else str(max_claims)
                await update.message.reply_text(
                    f"✅ *Promo Code Created!*\n\n"
                    f"🎁 Code: `{promo['code']}`\n"
                    f"💰 Bonus: ₹{amount:.2f}\n"
                    f"👥 Max Claims: {max_disp}\n\n"
                    f"User isko `🎟 Redeem Promo Code` se claim kar sakta hai.",
                    reply_markup=admin_promos_keyboard(codes),
                    parse_mode="Markdown"
                )
        except Exception:
            await update.message.reply_text(
                "❌ Format galat. Aise bhej:\n\n"
                "`CODE | AMOUNT | MAX_CLAIMS`\n\n"
                "Examples:\n"
                "• `WELCOME50 | 50 | 100`\n"
                "• `DIWALI | 10 | 0`  (0 = unlimited)",
                parse_mode="Markdown"
            )

    elif action == "set_cache_size":
        try:
            from database import (
                set_recent_devices_cache_size,
                MIN_RECENT_DEVICES_CACHE_SIZE, MAX_RECENT_DEVICES_CACHE_SIZE
            )
            val = int(text.strip())
            if val < MIN_RECENT_DEVICES_CACHE_SIZE or val > MAX_RECENT_DEVICES_CACHE_SIZE:
                raise ValueError("range")
            applied = await set_recent_devices_cache_size(val)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ Smart Match cache size set to *{applied}*.\n\n"
                f"Ab group ke last *{applied}* messages ke device_ids yaad rakhe jayenge "
                f"aur buy ke time stock se priority match honge.",
                reply_markup=admin_main_keyboard(), parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text(
                f"❌ Invalid. {MIN_RECENT_DEVICES_CACHE_SIZE} se {MAX_RECENT_DEVICES_CACHE_SIZE} ke "
                f"beech ka pura number bhej (e.g. `25`).",
                parse_mode="Markdown"
            )

    elif action == "set_first_buy_disc":
        try:
            val = float(text)
            if val < 0 or val > 100:
                raise ValueError("0-100 only")
            await update_settings("first_buy_discount", val)
            context.user_data.pop("admin_action", None)
            status = "disabled" if val == 0 else f"{val:g}% off first OTP"
            await update.message.reply_text(
                f"✅ First-Buy Discount: *{status}*",
                reply_markup=admin_main_keyboard(), parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text("❌ Invalid value. Enter a number 0-100 (e.g. `50`).", parse_mode="Markdown")

    elif action == "topup_add_slab":
        try:
            parts = [p.strip() for p in text.split("|")]
            if len(parts) != 3:
                raise ValueError("3 parts chahiye, separated by `|`")
            mn = float(parts[0]); mx = float(parts[1]); pct = float(parts[2])
            if mn < 0 or mx <= mn:
                raise ValueError("min/max invalid (max > min hona chahiye)")
            if pct <= 0 or pct > 100:
                raise ValueError("bonus_pct 0.1–100 ke beech hona chahiye")
            from database import add_topup_slab
            await add_topup_slab(mn, mx, pct)
            context.user_data.pop("admin_action", None)
            await update.message.reply_text(
                f"✅ *Slab added*\n\n"
                f"₹{mn:g}–₹{mx:g}  →  +{pct:g}% bonus",
                reply_markup=admin_main_keyboard(), parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Invalid: {e}\n\n"
                f"Format: `min | max | bonus_pct`\n"
                f"Example: `100 | 499 | 10`",
                parse_mode="Markdown"
            )

    elif action == "flash_set_discount":
        try:
            val = float(text)
            if val < 1 or val > 95:
                raise ValueError("1-95 only")
            context.user_data["flash_discount"] = val
            context.user_data["flash_selected"] = set()
            context.user_data["flash_all_mode"] = False
            context.user_data.pop("admin_action", None)
            await flash_show_select(update, context)
        except Exception:
            await update.message.reply_text(
                "❌ Invalid. 1–95 ke beech ka number bhej (e.g. `30`).",
                parse_mode="Markdown"
            )

    elif action == "flash_set_duration":
        try:
            mins = int(text)
            if mins < 1 or mins > 10080:
                raise ValueError("1-10080 only")
            from database import set_flash_sale
            disc = float(context.user_data.get("flash_discount", 0))
            all_mode = bool(context.user_data.get("flash_all_mode", False))
            selected = list(context.user_data.get("flash_selected", set()))
            await set_flash_sale(disc, selected, all_mode, mins)
            context.user_data.pop("admin_action", None)
            context.user_data.pop("flash_discount", None)
            context.user_data.pop("flash_selected", None)
            context.user_data.pop("flash_all_mode", None)
            scope_str = "🌐 ALL services" if all_mode else f"{len(selected)} services: " + ", ".join(f"`{n}`" for n in selected[:8])
            if not all_mode and len(selected) > 8:
                scope_str += f"  +{len(selected) - 8} more"
            if mins >= 60:
                dur_str = f"{mins // 60}h {mins % 60}m"
            else:
                dur_str = f"{mins}m"
            await update.message.reply_text(
                "🔥 *FLASH SALE STARTED!*\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"💸 Discount: *{disc:.0f}% OFF*\n"
                f"⏳ Duration: *{dur_str}*\n"
                f"📦 Scope: {scope_str}\n\n"
                "_Users ko discounted price automatically dikhega._",
                reply_markup=admin_main_keyboard(), parse_mode="Markdown"
            )
        except Exception:
            await update.message.reply_text(
                "❌ Invalid. 1–10080 minutes ke beech ka number bhej (e.g. `60` for 1 hour).",
                parse_mode="Markdown"
            )

    elif action == "manual_number":
        try:
            parts = text.split("|")
            target_uid = int(parts[0].strip())
            number = parts[1].strip()
            if len(parts) >= 3 and parts[2].strip():
                dev_id = parts[2].strip()
            else:
                stock = await get_stock()
                stock_item = next((s for s in stock if s["number"] == number), None)
                dev_id = stock_item["device_id"] if stock_item else None
            await update_session_number(target_uid, number, dev_id)
            context.user_data.pop("admin_action", None)
            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=f"📱 Your number has been assigned:\n`{number}`\n\nWaiting for OTP...",
                    reply_markup=back_keyboard(),
                    parse_mode="Markdown"
                )
            except:
                pass
            await update.message.reply_text(f"✅ Number `{number}` sent to user `{target_uid}`.", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}\n\nFormat: `USER_ID | NUMBER`", parse_mode="Markdown")

    elif action == "manual_otp":
        try:
            parts = text.split("|", 1)
            target_uid = int(parts[0].strip())
            otp_message = parts[1].strip()

            session = await get_session(target_uid)
            if not session:
                await update.message.reply_text(f"❌ No active session for user `{target_uid}`.", parse_mode="Markdown")
                return

            settings = await get_settings()
            global_price = settings.get("otp_price", 5.0)
            from database import get_service_price
            price = await get_service_price(session.get("service", "Myntra"), global_price)

            await deduct_balance(target_uid, price)
            await update_session_status(target_uid, "delivered")
            await add_log("otp_delivered", {"user_id": target_uid, "service": SERVICE_NAME, "mode": "manual"})

            context.user_data.pop("admin_action", None)

            try:
                await context.bot.send_message(
                    chat_id=target_uid,
                    text=f"✅ *OTP Received!*\n\n{otp_message}",
                    reply_markup=main_menu_keyboard(),
                    parse_mode="Markdown"
                )
            except:
                pass

            await update.message.reply_text(
                f"✅ OTP sent to user `{target_uid}`. Balance deducted.",
                parse_mode="Markdown"
            )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}\n\nFormat: `USER_ID | OTP MESSAGE`", parse_mode="Markdown")

    elif action == "set_otp_group":
        group_id = text.strip().lstrip("-")
        if not group_id.lstrip("-").isdigit():
            group_id = text.strip()
        await set_otp_group_id(text.strip())
        context.user_data.pop("admin_action", None)
        await update.message.reply_text(
            f"✅ OTP Group set to: `{text.strip()}`\n\n"
            f"Make sure the bot is a *member* of that group.",
            reply_markup=admin_main_keyboard(),
            parse_mode="Markdown"
        )

    elif action == "add_service":
        try:
            parts = text.split("|", 1)
            if len(parts) < 2:
                raise ValueError("Format galat hai")
            name = parts[0].strip()
            keywords = [kw.strip().lower() for kw in parts[1].split(",") if kw.strip()]
            if not name or not keywords:
                raise ValueError("Name ya keywords missing")
            success = await add_service(name, keywords)
            context.user_data.pop("admin_action", None)
            if success:
                services = await get_services()
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                await update.message.reply_text(
                    f"✅ Service *{name}* add ho gaya!\nKeywords: `{', '.join(keywords)}`",
                    reply_markup=admin_services_keyboard(services),
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"❌ Service *{name}* already exists ya error aaya.",
                    parse_mode="Markdown"
                )
        except Exception as e:
            await update.message.reply_text(
                f"❌ Error: {e}\n\nFormat: `Service Name | keyword1, keyword2`",
                parse_mode="Markdown"
            )


async def approve_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❌ *Format galat hai!*\n\nSahi format:\n`/approve USER_ID AMOUNT`\n\nExample:\n`/approve 123456789 100`",
            parse_mode="Markdown"
        )
        return
    try:
        target_uid = int(args[0])
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("❌ USER_ID number hona chahiye aur AMOUNT bhi number.", parse_mode="Markdown")
        return
    if amount <= 0:
        await update.message.reply_text("❌ Amount 0 se zyada hona chahiye.", parse_mode="Markdown")
        return
    db_user = await get_user(target_uid)
    if not db_user:
        await update.message.reply_text(f"❌ User `{target_uid}` nahi mila database mein.", parse_mode="Markdown")
        return
    await add_balance_manual(target_uid, amount)
    await add_log("deposit_approved", {"user_id": target_uid, "amount": amount, "method": "manual_approve"})
    new_bal = (db_user.get("balance", 0) or 0) + amount
    try:
        await context.bot.send_message(
            chat_id=target_uid,
            text=f"✅ *Balance Added!*\n\n₹{amount:.2f} aapke account mein add kar diya gaya hai.\n\n💰 New Balance: ₹{new_bal:.2f}",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    except Exception:
        pass
    await update.message.reply_text(
        f"✅ *Done!*\n\nUser `{target_uid}` ko ₹{amount:.2f} add kar diya.\n💰 New Balance: ₹{new_bal:.2f}",
        parse_mode="Markdown"
    )


async def set_otp_group_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    current_group = await get_otp_group_id()
    current_str = f"`{current_group}`" if current_group else "Not set (listens to ALL groups)"
    context.user_data["admin_action"] = "set_otp_group"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_settings")]])
    await query.edit_message_text(
        f"📡 *Set OTP Group*\n\n"
        f"Current: {current_str}\n\n"
        f"Send the *Group ID* (negative number like `-1001234567890`) where OTP messages arrive.\n\n"
        f"💡 How to get Group ID:\n"
        f"1. Add @userinfobot to your OTP group\n"
        f"2. It will show the group ID\n\n"
        f"Or forward any message from that group to @userinfobot.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def admin_services_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    text = (
        "🛠 *Services Manager*\n\n"
        "Yahan se naye OTP services add/remove karo.\n"
        "✅ = Active (OTP detect hoga) | ❌ = Disabled\n\n"
        "Service name par tap karo — toggle ho jaayega.\n"
        "Keywords: service identify karne wale words (comma separated)."
    )
    await query.edit_message_text(text, reply_markup=admin_services_keyboard(services), parse_mode="Markdown")


async def svc_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service_id = query.data.replace("svc_toggle_", "")
    new_state = await toggle_service(service_id)
    state_str = "✅ Active" if new_state else "❌ Disabled"
    await query.answer(f"Service {state_str}", show_alert=True)
    services = await get_services()
    await query.edit_message_reply_markup(reply_markup=admin_services_keyboard(services))


async def svc_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service_id = query.data.replace("svc_delete_", "")
    await delete_service(service_id)
    await query.answer("🗑 Service deleted.", show_alert=True)
    services = await get_services()
    await query.edit_message_reply_markup(reply_markup=admin_services_keyboard(services))


async def svc_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "add_service"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")]])
    await query.edit_message_text(
        "➕ *Add New Service*\n\n"
        "Format:\n`Service Name | keyword1, keyword2`\n\n"
        "Example:\n`Flipkart | flipkart, flipkart.com`\n`Amazon | amazon, amazon.in`\n\n"
        "Keywords: OTP message mein ye words aane chahiye (case-insensitive).",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def svc_setprice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service_id = query.data.replace("svc_price_", "")
    context.user_data["admin_action"] = "set_service_price"
    context.user_data["svc_price_id"] = service_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")]])
    await query.edit_message_text(
        "💵 *Set Service Price*\n\n"
        "Naya price enter karo (e.g. `8.00`):\n\n"
        "_Note: 'default' type karo global price use karne ke liye._",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def svc_otpcount_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info(f"[OTPCOUNT] callback fired by user={query.from_user.id} data={query.data!r}")
    try:
        await query.answer()
    except Exception as e:
        logger.error(f"[OTPCOUNT] query.answer failed: {e}")
    if not is_admin(query.from_user.id):
        logger.warning(f"[OTPCOUNT] non-admin user {query.from_user.id} blocked. ADMIN_IDS={ADMIN_IDS}")
        try:
            await query.answer("❌ Admin only.", show_alert=True)
        except Exception:
            pass
        return
    service_id = query.data.replace("svc_otpcount_", "")
    logger.info(f"[OTPCOUNT] service_id={service_id!r}")
    context.user_data["admin_action"] = "set_service_otp_count"
    context.user_data["svc_otpcount_id"] = service_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")]])
    try:
        await query.edit_message_text(
            "🔢 *Set OTP Count Per Order*\n\n"
            "Kitne OTP ek order mein milne chahiye?\n"
            "(e.g. `1` = single OTP, `2` = 2 OTPs same number pe wait_time ke andar)\n\n"
            "_Note: Paisa sirf pehle OTP pe deduct hoga. Baaki OTP free aayenge agar same window ke andar aate hain. Cancel sirf pehla OTP aane se pehle allowed hai._",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        logger.info("[OTPCOUNT] prompt sent successfully")
    except Exception as e:
        logger.error(f"[OTPCOUNT] edit_message_text failed: {e}")
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text="🔢 *Set OTP Count Per Order*\n\nReply with a number 1-10 (e.g. `2`):",
                reply_markup=kb,
                parse_mode="Markdown"
            )
            logger.info("[OTPCOUNT] fallback send_message sent")
        except Exception as e2:
            logger.error(f"[OTPCOUNT] fallback send_message also failed: {e2}")


async def svc_otpdigits_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin sets allowed OTP digit lengths for a service (e.g. 4, 5, 6)."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service_id = query.data.replace("svc_otpdigits_", "")
    context.user_data["admin_action"] = "set_service_otp_digits"
    context.user_data["svc_otpdigits_id"] = service_id

    # Fetch service name and digit stats
    from bson import ObjectId
    from database import get_otp_digit_stats
    svc_doc = None
    try:
        svc_doc = await __import__('database').db.services.find_one({"_id": ObjectId(service_id)})
    except Exception:
        pass

    stats_lines = ""
    if svc_doc:
        svc_name = svc_doc.get("name", "?")
        current = svc_doc.get("otp_digits", [4, 5, 6])
        current_str = ", ".join(str(d) for d in sorted(current))
        stats = await get_otp_digit_stats(svc_name)
        if stats:
            stats_lines = "\n📊 *Observed OTP digits so far:*\n"
            for s in stats:
                bar = "█" * min(s["count"], 10)
                stats_lines += f"  `{s['digit_len']}` digit — {s['count']}x  {bar}\n"
        else:
            stats_lines = "\n📊 _No data yet — stats build up as OTPs come in._\n"
        header = (
            f"📏 *OTP Digit Length — {svc_name}*\n\n"
            f"Current setting: `{current_str}`\n"
            f"{stats_lines}\n"
        )
    else:
        header = "📏 *OTP Digit Length Set Karo*\n\n"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")]])
    await query.edit_message_text(
        header +
        "Kitne digit wale OTP accept karne hain?\n"
        "Comma se separated type karo:\n\n"
        "`4, 5, 6` → sab accept _(default)_\n"
        "`6` → sirf 6 digit\n"
        "`4, 6` → 4 ya 6 digit\n\n"
        "💡 _Stats dekh ke set karo — jo digit zyada aaye woh daalo_\n\n"
        "Reply karo:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def apply_digit_suggest_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin approves auto-suggested OTP digit fix from mismatch alert."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    data = query.data.replace("apply_digit_suggest_", "")
    try:
        service_name, digits_str = data.rsplit("|", 1)
        digits = [int(d) for d in digits_str.split(",") if d.strip().isdigit()]
        if not digits:
            raise ValueError("No valid digits")
        from database import update_service_otp_digits_by_name
        await update_service_otp_digits_by_name(service_name, digits)
        digits_fmt = ", ".join(str(d) for d in sorted(digits))
        await query.edit_message_text(
            f"✅ *{service_name}* ka OTP digit setting update ho gaya!\n\n"
            f"📏 Ab accepted: *{digits_fmt}* digit\n\n"
            f"_Agli baar se is service ka OTP automatically deliver hoga._",
            parse_mode="Markdown"
        )
        logger.info(f"[DIGIT_APPLY] Admin {query.from_user.id} applied digits {digits} for {service_name}")
    except Exception as e:
        logger.error(f"[DIGIT_APPLY] Failed: {e}")
        await query.edit_message_text(f"❌ Error: {e}")


async def svc_keywords_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show keywords for a service + add/remove buttons."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service_id = query.data.replace("svc_keywords_", "")
    from bson import ObjectId
    from database import add_service_keyword, remove_service_keyword
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    svc = await _database.db.services.find_one({"_id": ObjectId(service_id)})
    if not svc:
        await query.edit_message_text("❌ Service not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_services")]]))
        return

    kws = svc.get("keywords", [])
    context.user_data["svc_kw_id"] = service_id
    context.user_data["svc_kw_name"] = svc.get("name", "?")

    def _kw_keyboard():
        rows = []
        for kw in kws:
            rows.append([
                InlineKeyboardButton(f"🔑 {kw}", callback_data="noop"),
                InlineKeyboardButton("❌ Remove", callback_data=f"svc_kw_del_{service_id}|{kw}"),
            ])
        rows.append([InlineKeyboardButton("➕ Add Keyword", callback_data=f"svc_kw_add_{service_id}")])
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="admin_services")])
        return InlineKeyboardMarkup(rows)

    kw_list = "\n".join(f"  • `{kw}`" for kw in kws) if kws else "  _No keywords set_"
    await query.edit_message_text(
        f"🔑 *Keywords — {svc['name']}*\n\n"
        f"OTP message mein in mein se koi bhi word aane par ye service match hogi:\n\n"
        f"{kw_list}\n\n"
        f"➕ Keyword add karne ke liye button dabao.\n"
        f"❌ Remove karne ke liye keyword ke saath Remove dabao.",
        reply_markup=_kw_keyboard(),
        parse_mode="Markdown"
    )


async def svc_kw_add_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin wants to add a keyword — prompt for input."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    service_id = query.data.replace("svc_kw_add_", "")
    context.user_data["admin_action"] = "add_service_keyword"
    context.user_data["svc_kw_id"] = service_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"svc_keywords_{service_id}")]])
    await query.edit_message_text(
        "➕ *Keyword Add Karo*\n\n"
        "Woh word type karo jo BigBasket/service ke OTP message mein aata hai.\n\n"
        "Examples:\n"
        "`bigbasket` — agar message mein 'bigbasket' aaye\n"
        "`bigbsk` — agar sender BIGBSK ho\n"
        "`bb-cart` — agar sender BB-CART ho\n\n"
        "💡 _Message ka actual text dekh ke type karo_\n\n"
        "Reply karo:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def svc_kw_del_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove a keyword from service."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    data = query.data.replace("svc_kw_del_", "")
    try:
        service_id, keyword = data.split("|", 1)
        from database import remove_service_keyword
        await remove_service_keyword(service_id, keyword)
        # Reload the keywords screen
        from bson import ObjectId
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        svc = await _database.db.services.find_one({"_id": ObjectId(service_id)})
        kws = svc.get("keywords", []) if svc else []
        rows = []
        for kw in kws:
            rows.append([
                InlineKeyboardButton(f"🔑 {kw}", callback_data="noop"),
                InlineKeyboardButton("❌ Remove", callback_data=f"svc_kw_del_{service_id}|{kw}"),
            ])
        rows.append([InlineKeyboardButton("➕ Add Keyword", callback_data=f"svc_kw_add_{service_id}")])
        rows.append([InlineKeyboardButton("🔙 Back", callback_data="admin_services")])
        kw_list = "\n".join(f"  • `{kw}`" for kw in kws) if kws else "  _No keywords set_"
        svc_name = svc.get("name", "?") if svc else "?"
        await query.edit_message_text(
            f"🔑 *Keywords — {svc_name}*\n\n✅ `{keyword}` hataya gaya!\n\n"
            f"Baaki keywords:\n{kw_list}\n\n"
            f"➕ Add / ❌ Remove buttons use karo.",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"[KW_DEL] {e}")
        await query.answer(f"❌ Error: {e}", show_alert=True)


async def admin_promos_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import list_promo_codes
    from keyboards import admin_promos_keyboard
    codes = await list_promo_codes()
    active_count = sum(1 for c in codes if c.get("active", True))
    total_claims = sum(len(c.get("claimed_by", [])) for c in codes)
    text = (
        "🎁 *Promo Codes Manager*\n\n"
        "Yahan se promo codes banao jo users ko ₹ balance bonus dete hain.\n\n"
        f"📊 Total codes: *{len(codes)}*\n"
        f"✅ Active: *{active_count}*\n"
        f"👥 Total claims: *{total_claims}*\n\n"
        "Tap karo kisi code pe details/claimers dekhne ke liye."
    )
    await query.edit_message_text(text, reply_markup=admin_promos_keyboard(codes), parse_mode="Markdown")


async def promo_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["admin_action"] = "create_promo"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_promos")]])
    await query.edit_message_text(
        "➕ *Naya Promo Code Banao*\n\n"
        "Format: `CODE | AMOUNT | MAX_CLAIMS`\n\n"
        "Examples:\n"
        "• `WELCOME50 | 50 | 100` — ₹50 bonus, max 100 users\n"
        "• `DIWALI | 10 | 0` — ₹10 bonus, *unlimited* claims (0 = unlimited)\n\n"
        "Rules:\n"
        "• Code mein space nahi hona chahiye\n"
        "• Code automatic uppercase ho jaayega\n"
        "• Amount = ₹ jo user ke balance mein add hoga\n\n"
        "Reply karo:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def promo_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_promo_code
    from keyboards import admin_promo_actions_keyboard
    code = query.data.replace("promo_view_", "")
    promo = await get_promo_code(code)
    if not promo:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_promos")]])
        await query.edit_message_text("❌ Code nahi mila (delete ho chuka hoga).", reply_markup=kb)
        return
    claimed = len(promo.get("claimed_by", []))
    max_c = int(promo.get("max_claims", 0) or 0)
    max_str = "Unlimited" if max_c == 0 else str(max_c)
    status = "✅ Active" if promo.get("active", True) else "❌ Disabled"
    total_paid = claimed * float(promo.get("amount", 0))
    created = promo.get("created_at")
    created_str = created.strftime("%d %b %Y, %H:%M") if created else "—"
    text = (
        f"🎁 *Promo Code Details*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔤 Code: `{promo['code']}`\n"
        f"💰 Bonus per claim: *₹{float(promo.get('amount', 0)):.2f}*\n"
        f"👥 Claimed: *{claimed}* / {max_str}\n"
        f"💸 Total bonus given: *₹{total_paid:.2f}*\n"
        f"🔘 Status: {status}\n"
        f"📅 Created: {created_str}"
    )
    await query.edit_message_text(
        text,
        reply_markup=admin_promo_actions_keyboard(promo["code"], promo.get("active", True)),
        parse_mode="Markdown"
    )


async def promo_claimers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info(f"[PROMO_CLAIMERS] callback fired by user={query.from_user.id} data={query.data!r}")
    try:
        await query.answer()
    except Exception:
        pass
    if not is_admin(query.from_user.id):
        try:
            await query.answer("❌ Admin only.", show_alert=True)
        except Exception:
            pass
        return
    from database import get_promo_code, get_user
    code = query.data.replace("promo_claimers_", "")
    promo = await get_promo_code(code)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"promo_view_{code}")]])
    if not promo:
        try:
            await query.edit_message_text("❌ Code nahi mila.", reply_markup=kb)
        except Exception as e:
            logger.error(f"[PROMO_CLAIMERS] edit failed (no promo): {e}")
        return
    claimers = promo.get("claimed_by", [])
    # Build PLAIN-TEXT message (no Markdown) — usernames often have underscores which break Markdown
    if not claimers:
        text = f"🎁 Code: {code}\n\nAbhi tak kisi ne yeh code claim nahi kiya."
    else:
        lines = [f"👥 Claimers of {code} — {len(claimers)} total\n"]
        recent = claimers[-50:]
        if len(claimers) > 50:
            lines.append(f"(showing last 50 of {len(claimers)})\n")
        for uid in recent:
            try:
                u = await get_user(uid)
            except Exception:
                u = None
            uname = (u.get("username") if u else None) or ""
            first = (u.get("first_name") if u else None) or ""
            if uname:
                who = f"@{uname}"
            elif first:
                who = first
            else:
                who = "(no username)"
            lines.append(f"• {uid} — {who}")
        text = "\n".join(lines)
    try:
        # Plain text — no parse_mode — safest, never breaks on special chars
        await query.edit_message_text(text, reply_markup=kb)
        logger.info(f"[PROMO_CLAIMERS] sent {len(claimers) if promo else 0} claimers for {code}")
    except Exception as e:
        logger.error(f"[PROMO_CLAIMERS] edit_message_text failed: {e}")
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=text,
                reply_markup=kb
            )
        except Exception as e2:
            logger.error(f"[PROMO_CLAIMERS] fallback send_message failed: {e2}")


async def promo_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    from database import toggle_promo_code
    code = query.data.replace("promo_toggle_", "")
    new_state = await toggle_promo_code(code)
    if new_state is None:
        await query.answer("❌ Code nahi mila", show_alert=True)
        return
    await query.answer(f"✅ Code {'enabled' if new_state else 'disabled'}")
    query.data = f"promo_view_{code}"
    await promo_view_callback(update, context)


async def promo_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer()
        return
    from database import delete_promo_code
    code = query.data.replace("promo_delete_", "")
    await delete_promo_code(code)
    await query.answer(f"✅ {code} delete ho gaya", show_alert=True)
    query.data = "admin_promos"
    await admin_promos_callback(update, context)


async def refund_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    refund_id = query.data.replace("refund_approve_", "")
    refund = await get_refund_request(refund_id)
    if not refund:
        await query.message.reply_text("❌ Refund request not found.")
        return
    if refund.get("status") != "pending":
        await query.message.reply_text(f"⚠️ Already {refund.get('status')}.")
        return
    context.user_data["admin_action"] = "approve_refund"
    context.user_data["refund_id"] = refund_id
    await query.message.reply_text(
        f"💵 *Refund Approve*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"User ID: `{refund.get('user_id')}`\n\n"
        f"Refund amount enter karo (e.g. `5` ya `10`):",
        parse_mode="Markdown"
    )


async def refund_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    refund_id = query.data.replace("refund_reject_", "")
    refund = await get_refund_request(refund_id)
    if not refund:
        await query.message.reply_text("❌ Refund request not found.")
        return
    if refund.get("status") != "pending":
        await query.message.reply_text(f"⚠️ Already {refund.get('status')}.")
        return
    context.user_data["admin_action"] = "reject_refund"
    context.user_data["refund_id"] = refund_id
    await query.message.reply_text(
        f"❌ *Refund Reject*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"User ID: `{refund.get('user_id')}`\n\n"
        f"Reject ka reason enter karo (user ko bhi dikhega):",
        parse_mode="Markdown"
    )


# ============================================================================
# BULK ADMIN OPERATIONS — multi-select keyboards for stock clear/add + svc del
# ============================================================================

import re as _re_bulk


async def bulk_clear_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open multi-select to clear stock for several services at once."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    context.user_data["bulk_clear_selected"] = set()
    summary = await get_stock_summary()
    lines = ["🧹 *Bulk Clear Stock*", "", "Jin services ka stock clear karna hai unko select karo:", ""]
    for s in services:
        cnt = summary.get(s["name"], 0)
        lines.append(f"• {s['name']} — {cnt} in stock")
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=bulk_select_keyboard(services, set(), "clear"),
        parse_mode="Markdown"
    )


async def bulk_clear_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    name = query.data.replace("bulk_clear_tog_", "")
    selected = context.user_data.get("bulk_clear_selected", set())
    if name in selected:
        selected.remove(name)
    else:
        selected.add(name)
    context.user_data["bulk_clear_selected"] = selected
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "clear"))
    except Exception:
        pass


async def bulk_clear_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    selected = {s["name"] for s in services}
    context.user_data["bulk_clear_selected"] = selected
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "clear"))
    except Exception:
        pass


async def bulk_clear_none_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["bulk_clear_selected"] = set()
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, set(), "clear"))
    except Exception:
        pass


async def bulk_clear_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show final confirmation before clearing stock for selected services."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    selected = context.user_data.get("bulk_clear_selected", set())
    if not selected:
        await query.answer("⚠️ Pehle services select karo.", show_alert=True)
        return
    summary = await get_stock_summary()
    total = sum(summary.get(n, 0) for n in selected)
    lines = [
        "⚠️ *Confirm Bulk Stock Clear*",
        "",
        f"Selected: *{len(selected)}* services",
        f"Total numbers to delete: *{total}*",
        "",
        "*Services:*",
    ]
    for n in sorted(selected):
        lines.append(f"• {n} — {summary.get(n, 0)}")
    lines.append("")
    lines.append("⚠️ Yeh undo nahi ho sakta!")
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=bulk_final_confirm_keyboard("clear"),
        parse_mode="Markdown"
    )


async def bulk_clear_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back to selection screen from final confirm."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    selected = context.user_data.get("bulk_clear_selected", set())
    summary = await get_stock_summary()
    lines = ["🧹 *Bulk Clear Stock*", "", "Jin services ka stock clear karna hai unko select karo:", ""]
    for s in services:
        cnt = summary.get(s["name"], 0)
        lines.append(f"• {s['name']} — {cnt} in stock")
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=bulk_select_keyboard(services, selected, "clear"),
        parse_mode="Markdown"
    )


async def bulk_clear_final_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually delete stock for all selected services."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    selected = context.user_data.get("bulk_clear_selected", set())
    if not selected:
        await query.answer("⚠️ Selection empty hai.", show_alert=True)
        return
    results = []
    total_deleted = 0
    for name in sorted(selected):
        try:
            n = await clear_service_stock(name)
            total_deleted += n
            results.append(f"• {name} — {n} deleted")
        except Exception as e:
            results.append(f"• {name} — ❌ {str(e)[:40]}")
    context.user_data["bulk_clear_selected"] = set()
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Stock", callback_data="admin_stock")]])
    await query.edit_message_text(
        f"✅ *Bulk Clear Complete*\n\nTotal deleted: *{total_deleted}* numbers across {len(selected)} services.\n\n" + "\n".join(results),
        reply_markup=kb,
        parse_mode="Markdown"
    )


# ----- BULK ADD STOCK -----

async def bulk_add_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open multi-select to add same numbers to multiple services."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    context.user_data["bulk_add_selected"] = set()
    await query.edit_message_text(
        "📦 *Bulk Add Stock*\n\n"
        "Step 1: Jin services mein numbers add karne hain unko select karo.\n"
        "Step 2: Phir numbers paste karoge — wahi numbers sab selected services mein add ho jayenge.",
        reply_markup=bulk_select_keyboard(services, set(), "add"),
        parse_mode="Markdown"
    )


async def bulk_add_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    name = query.data.replace("bulk_add_tog_", "")
    selected = context.user_data.get("bulk_add_selected", set())
    if name in selected:
        selected.remove(name)
    else:
        selected.add(name)
    context.user_data["bulk_add_selected"] = selected
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "add"))
    except Exception:
        pass


async def bulk_add_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    selected = {s["name"] for s in services}
    context.user_data["bulk_add_selected"] = selected
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "add"))
    except Exception:
        pass


async def bulk_add_none_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["bulk_add_selected"] = set()
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, set(), "add"))
    except Exception:
        pass


async def bulk_add_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """After services chosen, ask for numbers to paste."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    selected = context.user_data.get("bulk_add_selected", set())
    if not selected:
        await query.answer("⚠️ Pehle services select karo.", show_alert=True)
        return
    context.user_data["admin_action"] = "bulk_add_stock"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_stock")]])
    svc_list = ", ".join(sorted(selected))
    await query.edit_message_text(
        f"📦 *Bulk Add Stock*\n\n"
        f"Selected services ({len(selected)}): {svc_list}\n\n"
        f"Ab numbers paste karo, ek line per number, format:\n"
        f"`number | device_id`\n\n"
        f"Example:\n"
        f"`9876543210 | abc123`\n"
        f"`9876543211 | def456`\n\n"
        f"Sare numbers in saari selected services mein add ho jayenge.",
        reply_markup=kb,
        parse_mode="Markdown"
    )


# ----- BULK SERVICE DELETE -----

async def bulk_del_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open multi-select to delete several services at once."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    context.user_data["bulk_del_selected"] = set()
    await query.edit_message_text(
        "🗑 *Bulk Delete Services*\n\n"
        "Jin services ko delete karna hai unko select karo.\n"
        "⚠️ Note: Service delete hone ke baad uska stock orphan ho jayega — pehle clear kar lo.",
        reply_markup=bulk_select_keyboard(services, set(), "del"),
        parse_mode="Markdown"
    )


async def bulk_del_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    name = query.data.replace("bulk_del_tog_", "")
    selected = context.user_data.get("bulk_del_selected", set())
    if name in selected:
        selected.remove(name)
    else:
        selected.add(name)
    context.user_data["bulk_del_selected"] = selected
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "del"))
    except Exception:
        pass


async def bulk_del_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    selected = {s["name"] for s in services}
    context.user_data["bulk_del_selected"] = selected
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "del"))
    except Exception:
        pass


async def bulk_del_none_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["bulk_del_selected"] = set()
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, set(), "del"))
    except Exception:
        pass


async def bulk_del_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show final confirm before bulk service deletion."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    selected = context.user_data.get("bulk_del_selected", set())
    if not selected:
        await query.answer("⚠️ Pehle services select karo.", show_alert=True)
        return
    lines = [
        "⚠️ *Confirm Bulk Service Delete*",
        "",
        f"Yeh *{len(selected)}* services delete ho jayengi:",
        "",
    ]
    for n in sorted(selected):
        lines.append(f"• {n}")
    lines.append("")
    lines.append("⚠️ Yeh undo nahi ho sakta!")
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=bulk_final_confirm_keyboard("del"),
        parse_mode="Markdown"
    )


async def bulk_del_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back to selection screen from final confirm."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    selected = context.user_data.get("bulk_del_selected", set())
    await query.edit_message_text(
        "🗑 *Bulk Delete Services*\n\n"
        "Jin services ko delete karna hai unko select karo.\n"
        "⚠️ Note: Service delete hone ke baad uska stock orphan ho jayega — pehle clear kar lo.",
        reply_markup=bulk_select_keyboard(services, selected, "del"),
        parse_mode="Markdown"
    )


async def bulk_del_final_yes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Actually delete the selected services."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    selected = context.user_data.get("bulk_del_selected", set())
    if not selected:
        await query.answer("⚠️ Selection empty hai.", show_alert=True)
        return
    services = await get_services()
    name_to_id = {s["name"]: str(s["_id"]) for s in services}
    deleted = []
    failed = []
    for name in sorted(selected):
        sid = name_to_id.get(name)
        if not sid:
            failed.append(f"• {name} — not found")
            continue
        try:
            await delete_service(sid)
            deleted.append(f"• {name}")
        except Exception as e:
            failed.append(f"• {name} — ❌ {str(e)[:40]}")
    context.user_data["bulk_del_selected"] = set()
    services_after = await get_services()
    msg = f"✅ *Bulk Service Delete Complete*\n\nDeleted *{len(deleted)}*:\n" + "\n".join(deleted)
    if failed:
        msg += f"\n\nFailed {len(failed)}:\n" + "\n".join(failed)
    await query.edit_message_text(
        msg,
        reply_markup=admin_services_keyboard(services_after),
        parse_mode="Markdown"
    )


# ----- BULK PRICE CHANGE (multi-select) -----

async def bulk_price_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open multi-select to set the same price across multiple services."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    context.user_data["bulk_price_selected"] = set()
    await query.edit_message_text(
        "💵 *Bulk Price Change*\n\n"
        "Step 1: Jin services ka price change karna hai unko select karo.\n"
        "Step 2: Phir naya price daloge — wahi price sab selected services pe set ho jayega.",
        reply_markup=bulk_select_keyboard(services, set(), "price"),
        parse_mode="Markdown"
    )


async def bulk_price_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    name = query.data.replace("bulk_price_tog_", "")
    selected = context.user_data.get("bulk_price_selected", set())
    if name in selected:
        selected.remove(name)
    else:
        selected.add(name)
    context.user_data["bulk_price_selected"] = selected
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "price"))
    except Exception:
        pass


async def bulk_price_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    selected = {s["name"] for s in services}
    context.user_data["bulk_price_selected"] = selected
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "price"))
    except Exception:
        pass


async def bulk_price_none_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["bulk_price_selected"] = set()
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, set(), "price"))
    except Exception:
        pass


async def bulk_price_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """After services chosen, ask for the new price."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    selected = context.user_data.get("bulk_price_selected", set())
    if not selected:
        await query.answer("⚠️ Pehle services select karo.", show_alert=True)
        return
    context.user_data["admin_action"] = "bulk_set_price"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")]])
    svc_list = ", ".join(sorted(selected))
    await query.edit_message_text(
        f"💵 *Bulk Price Change*\n\n"
        f"Selected services ({len(selected)}): {svc_list}\n\n"
        f"Naya price enter karo (e.g. `8.00`):\n\n"
        f"_Note: 'default' type karo to global price use hoga in services pe._",
        reply_markup=kb,
        parse_mode="Markdown"
    )


# ----- BULK DIGIT CHANGE (multi-select) -----

async def bulk_digits_start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open multi-select to set the same OTP digit length across multiple services."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    context.user_data["bulk_digits_selected"] = set()
    await query.edit_message_text(
        "📏 *Bulk OTP Digit Change*\n\n"
        "Step 1: Jin services me digit setting change karni hai unko select karo.\n"
        "Step 2: Phir digit length daloge (jaise `6`) — wahi setting sab selected services pe lag jayegi.",
        reply_markup=bulk_select_keyboard(services, set(), "digits"),
        parse_mode="Markdown"
    )


async def bulk_digits_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    name = query.data.replace("bulk_digits_tog_", "")
    selected = context.user_data.get("bulk_digits_selected", set())
    if name in selected:
        selected.remove(name)
    else:
        selected.add(name)
    context.user_data["bulk_digits_selected"] = selected
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "digits"))
    except Exception:
        pass


async def bulk_digits_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    services = await get_services()
    selected = {s["name"] for s in services}
    context.user_data["bulk_digits_selected"] = selected
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, selected, "digits"))
    except Exception:
        pass


async def bulk_digits_none_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["bulk_digits_selected"] = set()
    services = await get_services()
    try:
        await query.edit_message_reply_markup(reply_markup=bulk_select_keyboard(services, set(), "digits"))
    except Exception:
        pass


async def bulk_digits_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """After services chosen, ask for the digit setting."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    selected = context.user_data.get("bulk_digits_selected", set())
    if not selected:
        await query.answer("⚠️ Pehle services select karo.", show_alert=True)
        return
    context.user_data["admin_action"] = "bulk_set_digits"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")]])
    svc_list = ", ".join(sorted(selected))
    await query.edit_message_text(
        f"📏 *Bulk OTP Digit Change*\n\n"
        f"Selected services ({len(selected)}): {svc_list}\n\n"
        f"Kitne digit wale OTP accept karne hain?\n"
        f"Comma se separated type karo:\n\n"
        f"`6` → sirf 6 digit\n"
        f"`4, 6` → 4 ya 6 digit\n"
        f"`4, 5, 6` → sab accept (default)\n\n"
        f"Reply karo:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


# ----- AUTO-EXTRACT KEYWORDS FROM PASTED SMS -----

def _extract_service_from_sms(text: str):
    """Try to auto-derive (service_name, keywords[]) from a pasted SMS message.
    Returns (name, keywords_list) or (None, None) if extraction fails.
    """
    if not text or len(text) < 10:
        return None, None
    lowered = text.lower()
    keywords = set()

    # 1) Sender header pattern: From: VK-FLPKRT-S, AD-AMAZON-S, BP-BIGBSK-T, etc.
    sender_match = _re_bulk.search(r"\b([A-Z]{2})-([A-Z0-9]{3,8})-([A-Z])\b", text)
    sender_brand = None
    if sender_match:
        sender_brand = sender_match.group(2).lower()
        keywords.add(sender_brand)
        keywords.add(f"{sender_match.group(1).lower()}-{sender_brand}-{sender_match.group(3).lower()}")

    # 2) Find capitalised brand-like words (Flipkart, BigBasket, Myntra, etc.)
    # Skip generic OTP/code/SMS words.
    stop = {
        "OTP", "SMS", "Code", "Login", "Verify", "Verification", "Use", "Your", "This", "From",
        "To", "Do", "Not", "Share", "Anyone", "For", "Account", "Mobile", "Number", "Number",
        "Ref", "Valid", "Min", "Mins", "Hour", "Hours", "Sec", "Time", "One", "Password",
        "Reset", "App", "Confirm", "Order", "Delivery", "OTP", "Hi", "Dear",
    }
    cap_words = _re_bulk.findall(r"\b([A-Z][a-zA-Z]{2,15})\b", text)
    brand = None
    for w in cap_words:
        if w in stop:
            continue
        brand = w
        break

    if brand:
        keywords.add(brand.lower())
        # Also lookup brand inside lowered text — common substring like "flipkart"
        # already added.
        name = brand
    elif sender_brand:
        name = sender_brand.capitalize()
    else:
        return None, None

    # 3) Try to also catch a domain like flipkart.com / amazon.in
    domain_match = _re_bulk.search(r"\b([a-z0-9][a-z0-9\-]{2,})\.(com|in|co|app|io|net|org)\b", lowered)
    if domain_match:
        keywords.add(domain_match.group(1))

    keywords = sorted(k for k in keywords if k and len(k) >= 2)
    if not keywords:
        return None, None
    return name, keywords


# Patch handle_admin_text to also accept bulk_add_stock + auto-extract for add_service.
# We do this by wrapping the function: on import, we patch in the new actions BEFORE
# falling through to the original behaviour.

_orig_handle_admin_text = handle_admin_text


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):  # type: ignore[no-redef]
    if not is_admin(update.effective_user.id):
        return
    action = context.user_data.get("admin_action")
    text = update.message.text.strip() if update.message and update.message.text else ""

    # ---- Bulk set price: same price across many services ----
    if action == "bulk_set_price":
        selected = context.user_data.get("bulk_price_selected", set())
        if not selected:
            await update.message.reply_text("⚠️ Selection lost. Phir se Bulk Price khol.", parse_mode="Markdown")
            context.user_data.pop("admin_action", None)
            return
        services = await get_services()
        name_to_id = {s["name"]: str(s["_id"]) for s in services}
        try:
            if text.strip().lower() == "default":
                new_price = None
                price_label = "default (global)"
            else:
                new_price = float(text)
                if new_price < 0:
                    raise ValueError("Price negative nahi ho sakta")
                price_label = format_balance(new_price)
        except Exception:
            await update.message.reply_text(
                "❌ Invalid value. Number do (e.g. `8.00`) ya `default` likho.",
                parse_mode="Markdown"
            )
            return
        ok, fail = [], []
        for name in sorted(selected):
            sid = name_to_id.get(name)
            if not sid:
                fail.append(f"• {name} — not found")
                continue
            try:
                await update_service_price(sid, new_price)
                ok.append(f"• {name}")
            except Exception as e:
                fail.append(f"• {name} — ❌ {str(e)[:40]}")
        context.user_data.pop("admin_action", None)
        context.user_data["bulk_price_selected"] = set()
        services_after = await get_services()
        msg_lines = [
            f"✅ *Bulk Price Update Done*",
            f"",
            f"New price: *{price_label}*",
            f"Updated: *{len(ok)}*  •  Failed: *{len(fail)}*",
            f"",
        ]
        msg_lines.extend(ok)
        if fail:
            msg_lines.append("")
            msg_lines.append(f"⚠️ Failed:")
            msg_lines.extend(fail)
        await update.message.reply_text(
            "\n".join(msg_lines),
            reply_markup=admin_services_keyboard(services_after),
            parse_mode="Markdown"
        )
        return

    # ---- Bulk set OTP digit length: same setting across many services ----
    if action == "bulk_set_digits":
        selected = context.user_data.get("bulk_digits_selected", set())
        if not selected:
            await update.message.reply_text("⚠️ Selection lost. Phir se Bulk Digits khol.", parse_mode="Markdown")
            context.user_data.pop("admin_action", None)
            return
        try:
            parts = [p.strip() for p in text.split(",") if p.strip()]
            digits = []
            for p in parts:
                d = int(p)
                if d < 3 or d > 9:
                    raise ValueError(f"Invalid digit length: {d} (3-9 ke beech hona chahiye)")
                digits.append(d)
            if not digits:
                raise ValueError("Koi valid digit nahi mili")
            digits = sorted(set(digits))
        except Exception as e:
            await update.message.reply_text(
                f"❌ Error: {e}\n\nExample: `6` ya `4, 6` ya `4, 5, 6`",
                parse_mode="Markdown"
            )
            return
        from database import update_service_otp_digits
        services = await get_services()
        name_to_id = {s["name"]: str(s["_id"]) for s in services}
        ok, fail = [], []
        for name in sorted(selected):
            sid = name_to_id.get(name)
            if not sid:
                fail.append(f"• {name} — not found")
                continue
            try:
                await update_service_otp_digits(sid, digits)
                ok.append(f"• {name}")
            except Exception as e:
                fail.append(f"• {name} — ❌ {str(e)[:40]}")
        context.user_data.pop("admin_action", None)
        context.user_data["bulk_digits_selected"] = set()
        services_after = await get_services()
        digits_str = ", ".join(str(d) for d in digits)
        msg_lines = [
            f"✅ *Bulk Digit Update Done*",
            f"",
            f"New digit setting: *{digits_str}*",
            f"Updated: *{len(ok)}*  •  Failed: *{len(fail)}*",
            f"",
            f"_Ab in services me sirf {digits_str} digit wale OTP accept honge._",
            f"",
        ]
        msg_lines.extend(ok)
        if fail:
            msg_lines.append("")
            msg_lines.append(f"⚠️ Failed:")
            msg_lines.extend(fail)
        await update.message.reply_text(
            "\n".join(msg_lines),
            reply_markup=admin_services_keyboard(services_after),
            parse_mode="Markdown"
        )
        return

    # ---- Bulk add stock: same numbers across many services ----
    if action == "bulk_add_stock":
        selected = context.user_data.get("bulk_add_selected", set())
        if not selected:
            await update.message.reply_text("⚠️ Selection lost. Phir se Bulk Add khol.", parse_mode="Markdown")
            context.user_data.pop("admin_action", None)
            return
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        parsed = []
        skipped = []
        for line in lines:
            if "|" not in line:
                skipped.append(f"`{line[:30]}` — missing `|`")
                continue
            num_part, dev_part = line.split("|", 1)
            number = num_part.strip()
            device_id = dev_part.strip()
            if not number or not device_id:
                skipped.append(f"`{line[:30]}` — empty field")
                continue
            parsed.append((number, device_id))
        per_svc_added = {n: 0 for n in selected}
        per_svc_failed = {n: 0 for n in selected}
        for number, device_id in parsed:
            for svc in selected:
                try:
                    await add_stock(number, device_id, svc)
                    per_svc_added[svc] += 1
                except Exception:
                    per_svc_failed[svc] += 1
        context.user_data.pop("admin_action", None)
        context.user_data["bulk_add_selected"] = set()
        total_ok = sum(per_svc_added.values())
        total_fail = sum(per_svc_failed.values())
        msg_lines = [
            f"📦 *Bulk Add Done*",
            f"",
            f"Numbers parsed: *{len(parsed)}*",
            f"Services: *{len(selected)}*",
            f"Total inserts OK: *{total_ok}*  •  Failed: *{total_fail}*",
            f"",
            f"*Per service:*",
        ]
        for svc in sorted(selected):
            msg_lines.append(f"• {svc} — ✅ {per_svc_added[svc]}  ❌ {per_svc_failed[svc]}")
        if skipped:
            msg_lines.append("")
            msg_lines.append(f"⚠️ Skipped lines ({len(skipped)}):")
            msg_lines.extend(skipped[:10])
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Stock", callback_data="admin_stock")]])
        await update.message.reply_text("\n".join(msg_lines), reply_markup=kb, parse_mode="Markdown")
        return

    # ---- Auto-extract keywords on add_service if admin pastes raw SMS ----
    if action == "add_service" and "|" not in text:
        # No pipe → try auto-extract from SMS
        name, keywords = _extract_service_from_sms(text)
        if name and keywords:
            context.user_data["svc_extract_pending"] = {
                "name": name,
                "keywords": keywords,
            }
            preview = (
                f"🔍 *Auto-Extracted from SMS*\n\n"
                f"*Service Name:* `{name}`\n"
                f"*Keywords:* `{', '.join(keywords)}`\n\n"
                f"Save karna hai ya manually edit karna hai?"
            )
            await update.message.reply_text(
                preview,
                reply_markup=svc_add_extracted_keyboard(),
                parse_mode="Markdown"
            )
            return
        # extraction failed → fall through to original handler which will show format error

    # Fallback: delegate to original handler
    await _orig_handle_admin_text(update, context)


async def svc_extract_save_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the auto-extracted service."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    pending = context.user_data.get("svc_extract_pending")
    if not pending:
        await query.answer("⚠️ Kuch pending nahi hai.", show_alert=True)
        return
    name = pending["name"]
    keywords = pending["keywords"]
    success = await add_service(name, keywords)
    context.user_data.pop("svc_extract_pending", None)
    context.user_data.pop("admin_action", None)
    services = await get_services()
    if success:
        await query.edit_message_text(
            f"✅ Service *{name}* add ho gaya!\nKeywords: `{', '.join(keywords)}`",
            reply_markup=admin_services_keyboard(services),
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text(
            f"❌ Service *{name}* already exists ya error aaya.",
            reply_markup=admin_services_keyboard(services),
            parse_mode="Markdown"
        )


async def svc_extract_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Discard auto-extract, ask admin to type manual format."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data.pop("svc_extract_pending", None)
    context.user_data["admin_action"] = "add_service"
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")]])
    await query.edit_message_text(
        "✏️ *Manual Add Service*\n\n"
        "Format:\n`Service Name | keyword1, keyword2`\n\n"
        "Example:\n`Flipkart | flipkart, flipkart.com`",
        reply_markup=kb,
        parse_mode="Markdown"
    )


# SMS / Gmail Auto-Verify panels REMOVED — manual deposit approval flow only.


# ── Admin User Notes Callbacks ────────────────────────────────────────────────

async def admin_user_notes_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View notes for a user — callback: notes_<user_id>"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.replace("notes_", ""))
    notes = await get_user_notes(user_id)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    lines = [f"📝 *Notes — User* `{user_id}`\n"]
    if notes:
        for i, note in enumerate(notes):
            ts = note.get("created_at")
            ts_str = ts.strftime("%d %b %Y, %H:%M") if ts else "N/A"
            safe_text = note['text'].replace('`', "'").replace('*', '').replace('_', '-')
            lines.append(f"{i+1}. {safe_text}\n   _{ts_str}_")
    else:
        lines.append("_Koi note nahi hai abhi._")

    buttons = []
    for i in range(len(notes)):
        buttons.append([InlineKeyboardButton(f"🗑 Note {i+1} delete karo", callback_data=f"delnote_{user_id}_{i}")])
    buttons.append([InlineKeyboardButton("➕ Note Add Karo", callback_data=f"addnote_{user_id}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])

    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )


async def admin_add_note_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prompt admin to type note — callback: addnote_<user_id>"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    user_id = int(query.data.replace("addnote_", ""))
    context.user_data["admin_action"] = "add_note"
    context.user_data["target_user"] = user_id
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data=f"notes_{user_id}")]])
    await query.edit_message_text(
        f"📝 *Note Add Karo*\n\nUser `{user_id}` ke liye note likho:\n\n"
        f"_(Example: fraud hai, pending refund, VIP user, etc.)_",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def admin_del_note_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a note by index — callback: delnote_<user_id>_<idx>"""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.replace("delnote_", "").rsplit("_", 1)
    user_id = int(parts[0])
    note_idx = int(parts[1])
    success = await delete_user_note(user_id, note_idx)
    notes = await get_user_notes(user_id)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    lines = [f"📝 *Notes — User* `{user_id}`\n"]
    if notes:
        for i, note in enumerate(notes):
            ts = note.get("created_at")
            ts_str = ts.strftime("%d %b %Y, %H:%M") if ts else "N/A"
            safe_text = note['text'].replace('`', "'").replace('*', '').replace('_', '-')
            lines.append(f"{i+1}. {safe_text}\n   _{ts_str}_")
    else:
        lines.append("_Koi note nahi hai abhi._")

    prefix = "✅ Note delete ho gaya!\n\n" if success else "❌ Delete fail.\n\n"
    buttons = []
    for i in range(len(notes)):
        buttons.append([InlineKeyboardButton(f"🗑 Note {i+1} delete karo", callback_data=f"delnote_{user_id}_{i}")])
    buttons.append([InlineKeyboardButton("➕ Note Add Karo", callback_data=f"addnote_{user_id}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])

    await query.edit_message_text(
        prefix + "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )


# ── Last 50 OTPs Callback ─────────────────────────────────────────────────────

async def admin_recent_otps_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last 50 OTP sessions — service, number, user, status, time."""
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    sessions = await get_recent_otp_sessions(50)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not sessions:
        await query.edit_message_text(
            "📋 *Last 50 OTPs*\n\n_Koi OTP session nahi mila abhi tak._",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]),
            parse_mode="Markdown"
        )
        return

    status_icons = {
        "delivered": "✅",
        "cancelled": "❌",
        "expired":   "⏰",
        "waiting":   "⏳",
    }

    lines = ["📋 *Last 50 OTPs*\n"]
    for i, s in enumerate(sessions, 1):
        uid      = s.get("user_id", "?")
        svc      = s.get("service", "?")
        number   = s.get("number", "?")
        status   = s.get("status", "?")
        otp_rcvd = s.get("otp_count_received", 0)
        price    = s.get("price")
        ts       = s.get("created_at")
        ts_str   = ts.strftime("%d/%m %H:%M") if ts else "N/A"
        icon     = status_icons.get(status, "❓")

        price_str = f" ₹{price:.0f}" if price else ""
        lines.append(
            f"{i}. {icon} *{svc}*{price_str}\n"
            f"   👤 `{uid}` | 📱 `{number}`\n"
            f"   🔢 OTP: {otp_rcvd} | 🕐 {ts_str}"
        )

    # Telegram message limit — send first 50 but split if too long
    full_text = "\n\n".join(lines)
    if len(full_text) > 4000:
        full_text = "\n\n".join(lines[:26]) + "\n\n_...aur bhi hain, limit ke liye logs dekho._"

    await query.edit_message_text(
        full_text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh", callback_data="admin_recent_otps")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
        ]),
        parse_mode="Markdown"
    )



async def diag_command(update, context):
    """Admin /diag command — full system status."""
    import config
    user = update.effective_user
    if not user or user.id not in [int(a) for a in config.ADMIN_IDS]:
        return
    from database import get_mode, get_otp_group_id, get_recent_device_ids_db, get_recent_devices_cache_size, get_settings

    mode     = await get_mode()
    otp_gid  = await get_otp_group_id()
    cache_sz = await get_recent_devices_cache_size()
    recent   = await get_recent_device_ids_db()
    settings = await get_settings()

    mode_icon  = "✅" if mode == "auto" else "⚠️"
    group_line = ("`" + str(otp_gid) + "`") if otp_gid else "❌ NOT SET"
    if recent:
        cache_line = "\n".join("  `" + d + "`" for d in recent[:10])
    else:
        cache_line = "❌ Empty — no OTP received yet OR privacy mode ON"

    maint = "🔴 ON" if settings.get("maintenance_mode") else "🟢 OFF"

    lines = [
        "🔍 *Bot Diagnostics*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        "*1. OTP Mode*",
        mode_icon + " Mode: `" + mode + "`",
        "_(Must be `auto` for OTP group reading)_",
        "",
        "*2. OTP Group ID*",
        "📡 " + group_line,
        "",
        "*3. Recent Device IDs Cache* (size=" + str(cache_sz) + ")",
        cache_line,
        "",
        "*4. Maintenance:* " + maint,
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "⚠️ *Privacy Mode* — Agar cache empty hai:",
        "@BotFather → /mybots → Bot Settings",
        "→ Group Privacy → *Turn OFF*",
        "Phir bot ko group se remove kar ke wapas add karo.",
    ]
    msg = "\n".join(lines)
    await update.message.reply_text(msg, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
# 📝 SERVICE REQUEST — ADMIN APPROVE / REJECT
# ══════════════════════════════════════════════════════════════════════════════

async def svc_req_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    request_id = query.data.replace("svc_req_approve_", "")
    from database import get_service_request
    req = await get_service_request(request_id)
    if not req:
        await query.answer("❌ Request not found.", show_alert=True)
        return
    if req.get("status") != "pending":
        await query.answer(f"⚠️ Already {req.get('status')}.", show_alert=True)
        return

    name = req.get("name", "")
    price = req.get("suggested_price", 5.0)
    keywords = req.get("keywords", [])
    kw_str = ", ".join(keywords)

    context.user_data["svc_req_approve_id"] = request_id
    context.user_data["svc_req_approve_name"] = name
    context.user_data["svc_req_approve_price"] = price
    context.user_data["svc_req_approve_keywords"] = keywords
    context.user_data["admin_action"] = "svc_req_edit_price"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✅ Confirm as-is (₹{price:.0f})", callback_data=f"svc_req_confirm_{request_id}")],
        [InlineKeyboardButton("✏️ Edit Price", callback_data=f"svc_req_edit_price_{request_id}"),
         InlineKeyboardButton("🔑 Edit Keywords", callback_data=f"svc_req_edit_kw_{request_id}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_back")],
    ])
    text = (
        f"📝 *Service Request — Approve*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ Name: *{name}*\n"
        f"💰 Price: *₹{price:.0f}*\n"
        f"🔑 Keywords: `{kw_str}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Price/keywords edit karo ya as-is confirm karo:"
    )
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def svc_req_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    request_id = query.data.replace("svc_req_confirm_", "")
    from database import get_service_request, add_service, update_service_request_status

    req = await get_service_request(request_id)
    if not req:
        await query.answer("❌ Request not found.", show_alert=True)
        return

    name = context.user_data.get("svc_req_approve_name", req.get("name", ""))
    price = context.user_data.get("svc_req_approve_price", req.get("suggested_price", 5.0))
    keywords = context.user_data.get("svc_req_approve_keywords", req.get("keywords", []))

    # Add the service
    ok = await add_service(name, keywords, price=price)
    await update_service_request_status(request_id, "approved")

    context.user_data.pop("admin_action", None)
    context.user_data.pop("svc_req_approve_id", None)
    context.user_data.pop("svc_req_approve_name", None)
    context.user_data.pop("svc_req_approve_price", None)
    context.user_data.pop("svc_req_approve_keywords", None)

    kw_str = ", ".join(keywords)
    status = "✅ Added!" if ok else "⚠️ Already exists (not duplicated)"
    await query.edit_message_text(
        f"✅ *Service Request Approved*\n\n"
        f"🏷️ Name: *{name}*\n"
        f"💰 Price: *₹{price:.0f}*\n"
        f"🔑 Keywords: `{kw_str}`\n"
        f"📦 Status: {status}",
        parse_mode="Markdown"
    )

    # Notify user
    user_id = req.get("user_id")
    try:
        from keyboards import main_menu_keyboard
        await update.get_bot().send_message(
            chat_id=user_id,
            text=(
                f"🎉 *Service Request Approved!*\n\n"
                f"🏷️ *{name}* ab available hai!\n"
                f"💰 Price: *₹{price:.0f}*\n\n"
                f"👇 Buy OTP karke try karo!"
            ),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard()
        )
    except Exception as e:
        logger.error(f"Failed to notify user {user_id} of approval: {e}")


async def svc_req_edit_price_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    request_id = query.data.replace("svc_req_edit_price_", "")
    context.user_data["svc_req_approve_id"] = request_id
    context.user_data["admin_action"] = "svc_req_new_price"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        "💰 *Naya price daalo (₹ mein):*\n\nJaise: `8`, `12`, `15`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]])
    )


async def svc_req_edit_kw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    request_id = query.data.replace("svc_req_edit_kw_", "")
    context.user_data["svc_req_approve_id"] = request_id
    context.user_data["admin_action"] = "svc_req_new_keywords"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        "🔑 *Naye keywords daalo (comma se alag):*\n\nJaise: `amazon, amzn, amazon.in`",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]])
    )


async def svc_req_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    request_id = query.data.replace("svc_req_reject_", "")
    from database import get_service_request
    req = await get_service_request(request_id)
    if not req:
        await query.answer("❌ Request not found.", show_alert=True)
        return
    if req.get("status") != "pending":
        await query.answer(f"⚠️ Already {req.get('status')}.", show_alert=True)
        return

    context.user_data["svc_req_reject_id"] = request_id
    context.user_data["svc_req_reject_user"] = req.get("user_id")
    context.user_data["svc_req_reject_name"] = req.get("name", "")
    context.user_data["admin_action"] = "svc_req_reject_reason"

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        f"❌ *Reject Reason likhna:*\n\n"
        f"Service: *{req.get('name')}*\n\n"
        f"_User ko ye message bheja jayega._\n"
        f"Rejection reason type karo:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_back")]])
    )


async def handle_svc_req_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle admin text input for service request approve/reject flows.
    Returns True if handled, False otherwise."""
    action = context.user_data.get("admin_action", "")

    if action == "svc_req_new_price":
        raw = update.message.text.strip().replace("₹", "").strip()
        try:
            price = float(raw)
            if price <= 0 or price > 10000:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Valid price daalo (1-10000):")
            return True

        context.user_data["svc_req_approve_price"] = price
        context.user_data["admin_action"] = "svc_req_edit_price"

        request_id = context.user_data.get("svc_req_approve_id", "")
        name = context.user_data.get("svc_req_approve_name", "")
        keywords = context.user_data.get("svc_req_approve_keywords", [])
        kw_str = ", ".join(keywords)

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Confirm (₹{price:.0f})", callback_data=f"svc_req_confirm_{request_id}")],
            [InlineKeyboardButton("✏️ Edit Price", callback_data=f"svc_req_edit_price_{request_id}"),
             InlineKeyboardButton("🔑 Edit Keywords", callback_data=f"svc_req_edit_kw_{request_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_back")],
        ])
        await update.message.reply_text(
            f"✅ Price updated!\n\n🏷️ *{name}*\n💰 Price: *₹{price:.0f}*\n🔑 Keywords: `{kw_str}`\n\nConfirm karo ya aur edit karo:",
            reply_markup=kb, parse_mode="Markdown"
        )
        return True

    elif action == "svc_req_new_keywords":
        raw = update.message.text.strip()
        keywords = [k.strip().lower() for k in raw.split(",") if k.strip()]
        if not keywords or len(keywords) > 15:
            await update.message.reply_text("❌ 1-15 keywords daalo, comma se alag:")
            return True

        context.user_data["svc_req_approve_keywords"] = keywords
        context.user_data["admin_action"] = "svc_req_edit_price"

        request_id = context.user_data.get("svc_req_approve_id", "")
        name = context.user_data.get("svc_req_approve_name", "")
        price = context.user_data.get("svc_req_approve_price", 5.0)
        kw_str = ", ".join(keywords)

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Confirm (₹{price:.0f})", callback_data=f"svc_req_confirm_{request_id}")],
            [InlineKeyboardButton("✏️ Edit Price", callback_data=f"svc_req_edit_price_{request_id}"),
             InlineKeyboardButton("🔑 Edit Keywords", callback_data=f"svc_req_edit_kw_{request_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="admin_back")],
        ])
        await update.message.reply_text(
            f"✅ Keywords updated!\n\n🏷️ *{name}*\n💰 Price: *₹{price:.0f}*\n🔑 Keywords: `{kw_str}`\n\nConfirm karo ya aur edit karo:",
            reply_markup=kb, parse_mode="Markdown"
        )
        return True

    elif action == "svc_req_reject_reason":
        reason = update.message.text.strip()
        if len(reason) < 3:
            await update.message.reply_text("❌ Thoda zyada detail mein likho:")
            return True

        request_id = context.user_data.get("svc_req_reject_id", "")
        user_id = context.user_data.get("svc_req_reject_user")
        name = context.user_data.get("svc_req_reject_name", "")

        context.user_data.pop("admin_action", None)
        context.user_data.pop("svc_req_reject_id", None)
        context.user_data.pop("svc_req_reject_user", None)
        context.user_data.pop("svc_req_reject_name", None)

        from database import update_service_request_status
        await update_service_request_status(request_id, "rejected")

        await update.message.reply_text(f"✅ Request rejected. User ko notify kar diya.")

        # Notify user
        try:
            from keyboards import main_menu_keyboard
            await update.get_bot().send_message(
                chat_id=user_id,
                text=(
                    f"❌ *Service Request Rejected*\n\n"
                    f"🏷️ Service: *{name}*\n\n"
                    f"📝 *Reason:*\n_{reason}_\n\n"
                    f"Koi aur service request kar sakte ho!"
                ),
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard()
            )
        except Exception as e:
            logger.error(f"Failed to notify user {user_id} of rejection: {e}")
        return True

    return False


# ============================================================================
# Payment Methods Toggle (admin)
# ============================================================================

async def admin_payment_methods_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_settings
    from keyboards import admin_payment_methods_keyboard
    settings = await get_settings()
    aloo_enabled   = settings.get("aloo_enabled",   True)
    zapupi_enabled = settings.get("zapupi_enabled",  False)
    text = (
        f"💳 *Payment Methods*\n\n"
        f"Yahan se payment methods on/off karo.\n\n"
        f"🟡 *Aloo:*   {'✅ ON' if aloo_enabled else '❌ OFF'}\n"
        f"⚡ *ZapUPI:* {'✅ ON' if zapupi_enabled else '❌ OFF'}\n\n"
        f"_Note: Agar dono off hain to deposit band ho jayega._"
    )
    await query.edit_message_text(text, reply_markup=admin_payment_methods_keyboard(aloo_enabled, zapupi_enabled), parse_mode="Markdown")


async def toggle_aloo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_settings, update_settings
    from keyboards import admin_payment_methods_keyboard
    settings = await get_settings()
    aloo_enabled   = settings.get("aloo_enabled",   True)
    zapupi_enabled = settings.get("zapupi_enabled",  False)
    new_val = not aloo_enabled
    await update_settings("aloo_enabled", new_val)
    status = "✅ ON" if new_val else "❌ OFF"
    text = (
        f"💳 *Payment Methods*\n\n"
        f"🟡 Aloo ab *{status}* hai.\n\n"
        f"🟡 *Aloo:*   {'✅ ON' if new_val else '❌ OFF'}\n"
        f"⚡ *ZapUPI:* {'✅ ON' if zapupi_enabled else '❌ OFF'}\n\n"
        f"_Note: Agar dono off hain to deposit band ho jayega._"
    )
    await query.edit_message_text(text, reply_markup=admin_payment_methods_keyboard(new_val, zapupi_enabled), parse_mode="Markdown")


async def toggle_zapupi_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    from database import get_settings, update_settings
    from keyboards import admin_payment_methods_keyboard
    settings = await get_settings()
    aloo_enabled   = settings.get("aloo_enabled",   True)
    zapupi_enabled = settings.get("zapupi_enabled",  False)
    new_val = not zapupi_enabled
    await update_settings("zapupi_enabled", new_val)
    status = "✅ ON" if new_val else "❌ OFF"
    text = (
        f"💳 *Payment Methods*\n\n"
        f"⚡ ZapUPI ab *{status}* hai.\n\n"
        f"🟡 *Aloo:*   {'✅ ON' if aloo_enabled else '❌ OFF'}\n"
        f"⚡ *ZapUPI:* {'✅ ON' if new_val else '❌ OFF'}\n\n"
        f"_Note: Agar dono off hain to deposit band ho jayega._"
    )
    await query.edit_message_text(text, reply_markup=admin_payment_methods_keyboard(aloo_enabled, new_val), parse_mode="Markdown")
