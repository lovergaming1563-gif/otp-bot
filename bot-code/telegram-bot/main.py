import logging
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, TypeHandler, ApplicationHandlerStop
)
from config import BOT_TOKEN, ADMIN_ID, ADMIN_IDS
from database import init_db
from handlers.user_handlers import (
    start, check_join_callback, main_menu_callback, profile_callback,
    refer_callback, support_callback, history_callback,
    history_filter_callback, history_service_filter_callback, buy_otp_callback,
    buy_service_callback, confirm_buy_callback, cancel_order_callback,
    deposit_callback, paid_callback, handle_screenshot, handle_utr_input,
    refund_callback, handle_refund_video, refund_pick_callback,
    service_search_callback, service_page_callback,
    deposit_upi_callback,
    i_paid_handler, i_paid_retry_handler,
    pay_aloo_callback, pay_rocket_callback, rocket_paid_handler,
)
from handlers.admin_handlers import (
    admin_command, admin_back_callback, admin_stats_callback,
    admin_stock_callback, stock_svc_callback, stock_view_callback,
    stock_add_callback, stock_remove_callback,
    stock_clear_all_callback, stock_clear_confirm_callback,
    stock_clear_svc_callback, stock_clear_svc_confirm_callback,
    admin_deposits_callback, dep_approve_callback, dep_reject_callback,
    admin_users_callback, admin_broadcast_callback, admin_logs_callback,
    log_type_callback, admin_settings_callback, set_price_callback,
    set_referral_callback, set_wait_callback, set_cancel_callback,
    set_upi_callback, set_qr_callback, set_min_deposit_callback,
    admin_deposit_stats_callback,
    set_first_buy_disc_callback, set_cache_size_callback,
    admin_sms_status_callback, toggle_sms_verify_callback,
    admin_used_utrs_callback,
    toggle_health_callback, set_health_threshold_callback,
    set_health_reminder_callback, set_health_window_callback,
    toggle_maintenance_callback, set_maintenance_msg_callback,
    admin_export_callback, admin_wallet_balances_callback, admin_users_export_callback, admin_restore_balances_callback, handle_restore_backup_file, admin_mode_callback, mode_set_callback,
    admin_manual_callback, manual_number_callback, manual_otp_callback,
    ban_callback, unban_callback, addbal_callback, dedbal_callback,
    resetbal_callback, handle_admin_text, set_otp_group_callback, remove_group_monitoring_callback, del_group_confirm_callback,
    admin_top_spenders_callback, admin_reset_stats_callback,
    admin_reset_stats_confirm_callback,
    approve_balance_command,
    admin_services_callback, svc_toggle_callback, svc_delete_callback, svc_add_callback,
    svc_setprice_callback, svc_otpcount_callback, svc_otpdigits_callback,
    apply_digit_suggest_callback,
    svc_keywords_callback, svc_kw_add_callback, svc_kw_del_callback,
    admin_promos_callback, promo_create_callback, promo_view_callback,
    promo_claimers_callback, promo_toggle_callback, promo_delete_callback,
    refund_approve_callback, refund_reject_callback,
    admin_alert_bots_callback, alert_toggle_callback, alert_all_toggle_callback,
    admin_flash_sale_callback, flash_create_callback, flash_pick_callback, flash_stop_callback,
    admin_topup_bonus_callback, topup_add_callback, topup_del_callback, topup_clear_callback,
    bulk_clear_start_callback, bulk_clear_toggle_callback, bulk_clear_all_callback,
    bulk_clear_none_callback, bulk_clear_confirm_callback, bulk_clear_back_callback,
    bulk_clear_final_yes_callback,
    bulk_add_start_callback, bulk_add_toggle_callback, bulk_add_all_callback,
    bulk_add_none_callback, bulk_add_confirm_callback,
    bulk_del_start_callback, bulk_del_toggle_callback, bulk_del_all_callback,
    bulk_del_none_callback, bulk_del_confirm_callback, bulk_del_back_callback,
    bulk_del_final_yes_callback,
    bulk_price_start_callback, bulk_price_toggle_callback, bulk_price_all_callback,
    bulk_price_none_callback, bulk_price_confirm_callback,
    bulk_digits_start_callback, bulk_digits_toggle_callback, bulk_digits_all_callback,
    bulk_digits_none_callback, bulk_digits_confirm_callback,
    svc_extract_save_callback, svc_extract_edit_callback,
    admin_user_notes_callback, admin_add_note_callback, admin_del_note_callback,
    admin_recent_otps_callback,
    diag_command,
    toggle_aloo_payment_callback, toggle_rocket_payment_callback,
)
from handlers.user_handlers import redeem_promo_callback
from otp_listener import group_message_listener

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user and update.effective_user.id in ADMIN_IDS:
        if context.user_data.get("admin_action"):
            await handle_admin_text(update, context)
            return

    if context.user_data.get("waiting_for") == "screenshot":
        return

    if context.user_data.get("waiting_for") == "promo_code":
        from database import claim_promo_code
        from keyboards import main_menu_keyboard
        from ui import header, field, card, DIV
        code = update.message.text.strip()
        context.user_data.pop("waiting_for", None)
        result = await claim_promo_code(code, update.effective_user.id)
        if result.get("success"):
            r_code = result['code']
            r_amt = result['amount']
            r_bal = result['balance']
            text = (
                f"{header('PROMO REDEEMED', '🎉', '🎉')}\n\n"
                f"{card([f'🎁  Code:        `{r_code}`', f'💰  Bonus:       *₹{r_amt:.2f}*', f'💵  New Balance: *₹{r_bal:.2f}*'])}\n\n"
                f"{DIV}\n"
                f"🚀  _Maza karo! Naya order place karo_"
            )
            await update.message.reply_text(text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        else:
            from ui import header as _h, DIV as _D
            err_text = (
                f"{_h('PROMO FAILED', '❌', '❌')}\n\n"
                f"{result.get('message', 'Redeem fail hua.')}\n\n"
                f"{_D}"
            )
            await update.message.reply_text(err_text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    if context.user_data.get("waiting_for") == "service_search":
        from database import get_services, get_stock_summary, get_settings
        from keyboards import service_search_results_keyboard, main_menu_keyboard
        from ui import header, card, DIV
        q_text = update.message.text.strip().lower()
        context.user_data.pop("waiting_for", None)
        if not q_text:
            await update.message.reply_text("❌ Empty search. Use /start to begin again.")
            return
        settings = await get_settings()
        mode = settings.get("mode", "auto")
        services = await get_services()
        active = [s for s in services if s.get("active")]
        if mode == "auto":
            summary = await get_stock_summary()
            pool = [(s["name"], summary.get(s["name"], 0)) for s in active if summary.get(s["name"], 0) > 0]
        else:
            pool = [(s["name"], 0) for s in active]
        matches = [(n, c) for (n, c) in pool if q_text in n.lower()]
        if not matches:
            text = (
                f"{header('NO MATCH FOUND', '🔍', '🔍')}\n\n"
                f"⚠️  *\"{q_text}\"* ke liye koi service nahi mili.\n\n"
                f"{card(['💡  *Try:*', '   • Spelling check kar', '   • Partial name use kar', '   • All services dekh ke select kar'])}\n\n"
                f"{DIV}"
            )
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Search Again", callback_data="svc_search")],
                [InlineKeyboardButton("📋 Show All Services", callback_data="buy_otp")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")],
            ])
            await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        else:
            text = (
                f"{header('SEARCH RESULTS', '🔍', '🔍')}\n\n"
                f"⚡  *\"{q_text}\"* ke liye *{len(matches)}* match mile:\n\n"
                f"{DIV}\n"
                f"👇  Service select kar:"
            )
            await update.message.reply_text(
                text,
                reply_markup=service_search_results_keyboard(matches, q_text),
                parse_mode="Markdown"
            )
        return



    if context.user_data.get("waiting_for") == "deposit_amount":
        from config import SUPPORT_USERNAME
        from database import get_upi_id, get_min_deposit, get_settings
        from ui import header, card, DIV
        from handlers.user_handlers import _generate_unique_amount, _make_payment_qr
        from keyboards import payment_method_select_keyboard
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup as _IKM
        import os
        raw = update.message.text.strip().replace("₹", "").replace(",", "").strip()
        try:
            amount = float(raw)
        except ValueError:
            await update.message.reply_text(
                f"{header('INVALID AMOUNT', '❌', '❌')}\n\n"
                f"⚠️  Sirf number type kar.\n\n"
                f"📝  *Examples:*  `50`, `150`, `500`",
                parse_mode="Markdown"
            )
            return
        min_dep = await get_min_deposit()
        if amount < min_dep:
            await update.message.reply_text(
                f"{header('AMOUNT TOO LOW', '❌', '❌')}\n\n"
                f"⚠️  *Minimum deposit:*  ₹{min_dep:.0f}\n"
                f"💰  *You entered:*  ₹{amount:.2f}\n\n"
                f"📝  Try again with ≥ ₹{min_dep:.0f}",
                parse_mode="Markdown"
            )
            return
        # unique_amount (with random paise) is ONLY for ALOO to identify the exact transfer.
        # Rocket uses order_id for uniqueness, so it always gets the exact amount the user typed.
        unique_amount = _generate_unique_amount(amount)   # ALOO only
        exact_amount  = amount                             # Rocket (no paise randomisation)

        context.user_data["deposit_amount"] = unique_amount  # ALOO default
        context.user_data["exact_amount"]   = exact_amount
        context.user_data.pop("waiting_for", None)
        context.user_data.pop("paid_check_count", None)

        # ── Check which payment methods are enabled ──
        settings = await get_settings()
        aloo_on   = settings.get("aloo_payment_enabled",   True)
        rocket_on = settings.get("rocket_payment_enabled", False)
        both_on   = aloo_on and rocket_on

        if both_on:
            # Show selection — user sees the original amount they typed
            sel_text = (
                f"{header('SELECT PAYMENT METHOD', '💳', '💳')}\n\n"
                f"{card([f'💰  *Amount:*  ₹{exact_amount:.0f}', '📲  Payment method choose karo'])}\n\n"
                f"{DIV}\n"
                f"👇  Kaunse method se pay karna hai?"
            )
            await update.message.reply_text(
                sel_text,
                reply_markup=payment_method_select_keyboard(
                    aloo_amount=unique_amount,
                    rocket_amount=exact_amount,
                    aloo_enabled=aloo_on,
                    rocket_enabled=rocket_on,
                ),
                parse_mode="Markdown"
            )
        elif rocket_on and not aloo_on:
            # Only Rocket — use exact amount (no paise)
            from config import ZAP_KEY
            import time as _time
            import asyncio as _asyncio
            from handlers.user_handlers import _zap_create_order
            if not ZAP_KEY:
                await update.message.reply_text(
                    "⚠️ *Rocket payment configured nahi hai.*\nAdmin se `ZAP_KEY` set karne ko kaho.",
                    parse_mode="Markdown"
                )
                return
            context.user_data["deposit_amount"] = exact_amount
            order_id = f"dep_{update.effective_user.id}_{int(exact_amount * 100)}_{int(_time.time())}"
            context.user_data["rocket_order_id"] = order_id
            context.user_data["payment_method"]  = "rocket"
            wait_msg = await update.message.reply_text("⏳ *Rocket payment link bana raha hai...*", parse_mode="Markdown")
            result = await _asyncio.to_thread(_zap_create_order, ZAP_KEY, order_id, exact_amount)
            if result.get("status") != "success":
                err_msg = result.get("message", "Order create karne mein error aaya.")
                await wait_msg.edit_text(
                    f"❌ *Rocket payment start nahi ho sakti.*\n\n_{err_msg}_",
                    parse_mode="Markdown"
                )
                return
            payment_url = result.get("payment_url", "")
            pay_kb = _IKM([
                [InlineKeyboardButton("🔗 Pay Now — Rocket", url=payment_url)],
                [InlineKeyboardButton("✅ Maine Pay Kar Diya", callback_data=f"rocket_paid_{order_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="main_menu")],
            ])
            payment_text = (
                f"{header(f'PAY ₹{exact_amount:.0f}', '🚀', '🚀')}\n\n"
                f"{card(['🚀  *Payment Method:*  Rocket', f'💰  *Amount:*  ₹{exact_amount:.0f}', '📲  Neeche link pe tap karke pay karo'])}\n\n"
                f"{DIV}\n"
                f"⚠️  *Exactly ₹{exact_amount:.0f} hi bhejo.*\n"
                f"👇  Payment ke baad *'✅ Maine Pay Kar Diya'* button dabao."
            )
            await wait_msg.edit_text(payment_text, reply_markup=pay_kb, parse_mode="Markdown")
        else:
            # ALOO flow (default — aloo_on=True or neither set)
            context.user_data["payment_method"] = "aloo"
            upi_id_dyn = await get_upi_id()
            upi_line = f"🏦  *UPI ID:*  `{upi_id_dyn}`" if upi_id_dyn else "🏦  *UPI ID:*  _(contact support)_"
            qr_buf = _make_payment_qr(upi_id_dyn, unique_amount)
            pay_kb = _IKM([
                [InlineKeyboardButton("✅ Maine Pay Kar Diya", callback_data=f"i_paid_{unique_amount}")],
                [InlineKeyboardButton("❌ Cancel",            callback_data="main_menu")],
            ])
            payment_text = (
                f"{header(f'PAY ₹{unique_amount:.2f}', '💳', '💳')}\n\n"
                f"{card([f'💰  *Exact Amount:*  ₹{unique_amount:.2f}', upi_line, '📲  Kisi bhi UPI app se payment karo'])}\n\n"
                f"{DIV}\n"
                f"⚠️  *Exactly ₹{unique_amount:.2f} hi bhejo* — ye unique amount sirf aapke liye hai.\n"
                f"👇  Payment ke baad *'✅ Maine Pay Kar Diya'* button dabao."
            )
            if qr_buf:
                try:
                    await update.message.reply_photo(photo=qr_buf, caption=payment_text, reply_markup=pay_kb, parse_mode="Markdown")
                except Exception:
                    await update.message.reply_text(payment_text, reply_markup=pay_kb, parse_mode="Markdown")
            else:
                await update.message.reply_text(payment_text, reply_markup=pay_kb, parse_mode="Markdown")
        return
    await update.message.reply_text("Use the menu buttons to navigate.")


async def group_health_check(context):
    """Every 5 min: check if OTP group / forwarder bots have gone silent. Alert admins."""
    from database import (
        get_silent_groups, get_silent_bots, mark_activity_alerted,
        get_otp_group_id, get_all_group_activity, record_group_activity,
        get_settings,
    )
    import datetime as _dt
    s = await get_settings()
    if not s.get("health_enabled", True):
        logger.info("[HEALTH] disabled in settings — skipping check")
        return
    THRESHOLD = int(s.get("health_threshold_min", 10))
    REMINDER = int(s.get("health_reminder_min", 4))
    BOT_WINDOW = int(s.get("health_bot_window_min", 60))
    logger.info(f"[HEALTH] periodic check running (threshold={THRESHOLD}m reminder={REMINDER}m window={BOT_WINDOW}m)")
    try:
        # Bootstrap: if otp_group_id configured but no group-level doc exists yet,
        # create one so the silence timer starts ticking from now
        otp_gid = await get_otp_group_id()
        if otp_gid:
            try:
                gid_int = int(otp_gid)
                docs = await get_all_group_activity()
                has_group_doc = any(d.get("group_id") == gid_int and d.get("sender_id") == 0 for d in docs)
                if not has_group_doc:
                    await record_group_activity(gid_int, 0, "BOOTSTRAP")
                    logger.info(f"[HEALTH] bootstrapped activity doc for group {gid_int}")
            except Exception as e:
                logger.warning(f"[HEALTH] bootstrap failed: {e}")

        silent_groups = await get_silent_groups(THRESHOLD, REMINDER)
        silent_bots = await get_silent_bots(THRESHOLD, BOT_WINDOW, REMINDER)
        logger.info(f"[HEALTH] silent_groups={len(silent_groups)} silent_bots={len(silent_bots)} admins={len(ADMIN_IDS)}")
        if not silent_groups and not silent_bots:
            return
        now = _dt.datetime.utcnow()
        all_docs = await get_all_group_activity()

        def fmt_name(doc):
            name = doc.get("sender_name", "Unknown") or "Unknown"
            if name.startswith("user_") or name in ("Unknown", "BOOTSTRAP", "GROUP"):
                return "(no username)"
            # Escape underscores so Markdown doesn't treat them as italic markers
            safe = name.replace("_", "\_")
            return f"@{safe}"

        def fmt_dur(mins):
            if mins < 1:
                return "abhi (<1 min)"
            if mins < 60:
                return f"{mins} min"
            h = mins // 60
            m = mins % 60
            return f"{h}h {m}m" if m else f"{h}h"

        # Identify affected groups (whether dead or just having silent bots)
        affected_group_ids = set()
        for g in silent_groups:
            affected_group_ids.add(g["group_id"])
        for b in silent_bots:
            affected_group_ids.add(b["group_id"])

        lines = ["🚨 *OTP Group Health Alert*", "━━━━━━━━━━━━━━━━━━━━"]

        for gid in affected_group_ids:
            group_doc = next((g for g in all_docs if g.get("group_id") == gid and g.get("sender_id") == 0), None)
            is_group_dead = any(g["group_id"] == gid for g in silent_groups)

            if is_group_dead and group_doc:
                grp_mins = int((now - group_doc["last_message_at"]).total_seconds() / 60)
                lines.append(f"\n🔴 *GROUP DEAD* — `{gid}`")
                lines.append(f"Group mein *{fmt_dur(grp_mins)}* se koi msg nahi aaya.")
            else:
                # Group active hai but kuch bots silent
                grp_mins = int((now - group_doc["last_message_at"]).total_seconds() / 60) if group_doc else 0
                lines.append(f"\n⚠️ *PARTIAL OUTAGE* — `{gid}`")
                lines.append(f"Group active hai (last msg {fmt_dur(grp_mins)} pehle), lekin kuch bots silent hain.")

            # Per-bot status table — ONLY monitored bots (alert_enabled=True)
            # User asked: "sirf usi ka bheje or sab ka nahi"
            monitored_bots = [d for d in all_docs
                              if d.get("group_id") == gid
                              and d.get("sender_id") != 0
                              and d.get("alert_enabled")]
            if monitored_bots:
                monitored_bots.sort(key=lambda d: d.get("last_message_at") or now, reverse=True)
                lines.append(f"\n🤖 *Monitored bots status:*")
                live_count = 0
                dead_count = 0
                for i, b in enumerate(monitored_bots, 1):
                    mins = int((now - b["last_message_at"]).total_seconds() / 60)
                    if mins < THRESHOLD:
                        status = "🟢 LIVE"
                        live_count += 1
                    elif mins < BOT_WINDOW:
                        status = "🟡 SLOW"
                        dead_count += 1
                    else:
                        status = "🔴 DEAD"
                        dead_count += 1
                    bid = b.get("sender_id")
                    name = fmt_name(b)
                    lines.append(f"{i}. {status} • ID `{bid}` • {name}")
                    lines.append(f"     ↳ last msg: *{fmt_dur(mins)}* pehle ({b.get('msg_count', 0)} total)")
                lines.append(f"\n📊 Summary: 🟢 {live_count} live • 🔴 {dead_count} silent")
                lines.append("_(Naye forwarder bots auto-track + auto-alert hote hain.)_")
                lines.append("_Noisy bot disable karna ho? /admin -> Settings -> Per-Bot Alert Toggle_")
            else:
                lines.append("\n_(Koi bot monitor nahi kiya hua. Add karo:)_")
                lines.append("_/admin -> Settings -> Per-Bot Alert Toggle_")

        lines.append(f"\n━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"_Reminder har {REMINDER} min baad aayega jab tak silent bot wapas msg na bheje._")
        msg = "\n".join(lines)
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=aid, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"[HEALTH] DM to {aid} failed: {e}")
        for g in silent_groups:
            await mark_activity_alerted(g["group_id"], 0)
        for b in silent_bots:
            await mark_activity_alerted(b["group_id"], b["sender_id"])
    except Exception as e:
        logger.error(f"[HEALTH] check failed: {e}")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/health — admin command to view current group/bot activity status."""
    if update.effective_user.id not in ADMIN_IDS:
        return
    from database import get_all_group_activity
    import datetime as _dt
    docs = await get_all_group_activity()
    if not docs:
        await update.message.reply_text(
            "📡 *Group Health*\n\nKoi tracked activity nahi. OTP group set kar aur message aane do.",
            parse_mode="Markdown"
        )
        return
    now = _dt.datetime.utcnow()
    groups = [d for d in docs if d.get("sender_id") == 0]
    bots = [d for d in docs if d.get("sender_id") != 0]
    lines = ["📡 *Group Activity Status*", "━━━━━━━━━━━━━━━━━━━━"]
    if groups:
        lines.append("\n*Groups:*")
        for g in groups:
            mins = int((now - g["last_message_at"]).total_seconds() / 60)
            status = "🟢" if mins < 10 else ("🟡" if mins < 30 else "🔴")
            lines.append(f"{status} `{g['group_id']}` — last msg *{mins} min* ago • {g.get('msg_count', 0)} msgs")
    if bots:
        lines.append("\n*Forwarder Bots:*")
        for b in bots[:20]:
            mins = int((now - b["last_message_at"]).total_seconds() / 60)
            status = "🟢" if mins < 10 else ("🟡" if mins < 60 else "🔴")
            name = b.get("sender_name", "Unknown")
            name_str = f"@{name}" if not name.startswith("user_") else name
            lines.append(f"{status} {name_str} — *{mins} min* ago • {b.get('msg_count', 0)} msgs")
        if len(bots) > 20:
            lines.append(f"\n_...{len(bots) - 20} more bots not shown_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def send_daily_report(context):
    from database import get_daily_revenue, get_stats
    from utils import format_balance
    try:
        data = await get_daily_revenue()
        stats = await get_stats()
        today = __import__("datetime").datetime.utcnow()
        date_str = today.strftime("%d %b %Y")
        msg = (
            f"📊 *Daily Report — {date_str}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💸 Aaj ki Earnings: {format_balance(data['deposit_total'])}\n"
            f"📤 OTPs Delivered Today: {data['otp_count']}\n"
            f"👥 Naye Users Today: {data['new_users']}\n"
            f"⏳ Active Sessions: {data['active_sessions']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 Total OTPs (Ever): {stats['total_otp']}\n"
            f"👤 Total Users: {stats['total_users']}\n"
            f"✅ Total Deposits: {stats['total_deposits']}"
        )
        for aid in ADMIN_IDS:
            try:
                await context.bot.send_message(chat_id=aid, text=msg, parse_mode="Markdown")
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Daily report error: {e}")


async def post_init(application: Application):
    logger.info("[BOOT] post_init: connecting to MongoDB...")
    try:
        await init_db()
        logger.info("[BOOT] ✅ Database initialized successfully.")
    except Exception as e:
        logger.warning(f"[BOOT] ⚠️ DB init warning: {e}")
        logger.warning("[BOOT] ACTION REQUIRED: Go to MongoDB Atlas → Network Access → Add IP 0.0.0.0/0")
    logger.info("[BOOT] ✅ Bot is now LIVE and accepting updates.")

    import datetime as _dt
    job_queue = application.job_queue
    job_queue.run_daily(
        send_daily_report,
        time=_dt.time(hour=3, minute=30, second=0),
        name="daily_report"
    )
    if job_queue is None:
        logger.error("[BOOT] ❌ JobQueue is None! Install python-telegram-bot[job-queue]. Health monitor DISABLED.")
    else:
        job_queue.run_repeating(
            group_health_check,
            interval=300,   # every 5 minutes
            first=60,       # first check 1 min after boot
            name="group_health_check"
        )
        logger.info(f"[BOOT] ✅ Group health monitor scheduled (every 5 min, threshold 10 min). Admins: {ADMIN_IDS}")


async def maintenance_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Block all non-admin users when maintenance mode is ON."""
    if not update.effective_user:
        return
    uid = update.effective_user.id
    if uid in ADMIN_IDS:
        return  # Admins always pass
    try:
        from database import get_settings
        s = await get_settings()
        if not s.get("maintenance_mode", False):
            return
        msg = s.get("maintenance_message") or (
            "🛠 *Bot Under Maintenance*\n\n"
            "Hum thodi der mein wapas aayenge. Aapka balance aur order safe hai.\n\n"
            "Thanks for your patience! 🙏"
        )
        try:
            if update.callback_query:
                short = msg.replace("*", "").replace("`", "")[:200]
                await update.callback_query.answer(short, show_alert=True)
            elif update.message:
                await update.message.reply_text(msg, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"[MAINT] reply failed: {e}")
        raise ApplicationHandlerStop
    except ApplicationHandlerStop:
        raise
    except Exception as e:
        logger.error(f"[MAINT] gate failed: {e}")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(post_init)
        .build()
    )

    # Maintenance gate — runs FIRST in group=-1, blocks non-admins when ON
    app.add_handler(TypeHandler(Update, maintenance_gate), group=-1)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("approve", approve_balance_command))
    app.add_handler(CommandHandler("health", health_command))
    app.add_handler(CommandHandler("diag", diag_command))

    app.add_handler(CallbackQueryHandler(check_join_callback, pattern="^check_join$"))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(profile_callback, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(refer_callback, pattern="^refer$"))
    app.add_handler(CallbackQueryHandler(support_callback, pattern="^support$"))
    app.add_handler(CallbackQueryHandler(history_callback, pattern="^history$"))
    app.add_handler(CallbackQueryHandler(buy_otp_callback, pattern="^buy_otp$"))
    app.add_handler(CallbackQueryHandler(buy_service_callback, pattern="^buy_service_"))
    app.add_handler(CallbackQueryHandler(confirm_buy_callback, pattern="^confirm_buy_"))
    app.add_handler(CallbackQueryHandler(cancel_order_callback, pattern="^cancel_order$"))
    app.add_handler(CallbackQueryHandler(deposit_callback, pattern="^deposit$"))
    app.add_handler(CallbackQueryHandler(i_paid_handler,       pattern="^i_paid(_[0-9.]+)?$"))
    app.add_handler(CallbackQueryHandler(i_paid_retry_handler, pattern="^i_paid_retry$"))

    app.add_handler(CallbackQueryHandler(admin_back_callback, pattern="^admin_back$"))
    app.add_handler(CallbackQueryHandler(admin_stats_callback, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_stock_callback, pattern="^admin_stock$"))
    app.add_handler(CallbackQueryHandler(stock_svc_callback, pattern="^stock_svc_"))
    app.add_handler(CallbackQueryHandler(stock_view_callback, pattern="^stock_view_"))
    app.add_handler(CallbackQueryHandler(stock_add_callback, pattern="^stock_add_"))
    app.add_handler(CallbackQueryHandler(stock_remove_callback, pattern="^stock_remove_"))
    app.add_handler(CallbackQueryHandler(stock_clear_all_callback, pattern="^stock_clear_all$"))
    app.add_handler(CallbackQueryHandler(stock_clear_confirm_callback, pattern="^stock_clear_confirm$"))
    app.add_handler(CallbackQueryHandler(stock_clear_svc_confirm_callback, pattern="^stock_clear_svc_confirm_"))
    app.add_handler(CallbackQueryHandler(stock_clear_svc_callback, pattern="^stock_clear_svc_"))
    app.add_handler(CallbackQueryHandler(admin_deposits_callback, pattern="^admin_deposits$"))
    app.add_handler(CallbackQueryHandler(dep_approve_callback, pattern="^dep_approve_"))
    app.add_handler(CallbackQueryHandler(dep_reject_callback, pattern="^dep_reject_"))
    app.add_handler(CallbackQueryHandler(admin_users_callback, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast_callback, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_logs_callback, pattern="^admin_logs$"))
    app.add_handler(CallbackQueryHandler(log_type_callback, pattern="^log_"))
    app.add_handler(CallbackQueryHandler(admin_settings_callback, pattern="^admin_settings$"))
    app.add_handler(CallbackQueryHandler(set_price_callback, pattern="^set_price$"))
    app.add_handler(CallbackQueryHandler(set_referral_callback, pattern="^set_referral$"))
    app.add_handler(CallbackQueryHandler(set_wait_callback, pattern="^set_wait$"))
    app.add_handler(CallbackQueryHandler(set_cancel_callback, pattern="^set_cancel$"))
    app.add_handler(CallbackQueryHandler(set_upi_callback, pattern="^set_upi$"))
    app.add_handler(CallbackQueryHandler(set_qr_callback, pattern="^set_qr$"))
    app.add_handler(CallbackQueryHandler(set_min_deposit_callback, pattern="^set_min_deposit$"))
    app.add_handler(CallbackQueryHandler(admin_deposit_stats_callback, pattern="^admin_deposit_stats$"))
    app.add_handler(CallbackQueryHandler(admin_sms_status_callback, pattern="^admin_sms_status$"))
    app.add_handler(CallbackQueryHandler(toggle_sms_verify_callback, pattern="^toggle_sms_verify$"))
    app.add_handler(CallbackQueryHandler(admin_used_utrs_callback, pattern="^admin_used_utrs$"))
    app.add_handler(CallbackQueryHandler(set_first_buy_disc_callback, pattern="^set_first_buy_disc$"))
    app.add_handler(CallbackQueryHandler(set_cache_size_callback, pattern="^set_cache_size$"))
    app.add_handler(CallbackQueryHandler(history_filter_callback, pattern="^hist_filter_"))
    app.add_handler(CallbackQueryHandler(history_service_filter_callback, pattern="^hist_svc_"))
    app.add_handler(CallbackQueryHandler(admin_export_callback, pattern="^admin_export$"))
    app.add_handler(CallbackQueryHandler(admin_wallet_balances_callback, pattern="^admin_wallet_balances$"))
    app.add_handler(CallbackQueryHandler(admin_users_export_callback, pattern="^admin_users_export$"))
    app.add_handler(CallbackQueryHandler(admin_restore_balances_callback, pattern="^admin_restore_balances$"))
    app.add_handler(MessageHandler(filters.Document.FileExtension("json") & filters.ChatType.PRIVATE, handle_restore_backup_file))
    app.add_handler(CallbackQueryHandler(admin_mode_callback, pattern="^admin_mode$"))
    app.add_handler(CallbackQueryHandler(mode_set_callback, pattern="^mode_"))
    app.add_handler(CallbackQueryHandler(admin_manual_callback, pattern="^admin_manual$"))
    app.add_handler(CallbackQueryHandler(manual_number_callback, pattern="^manual_number$"))
    app.add_handler(CallbackQueryHandler(manual_otp_callback, pattern="^manual_otp$"))
    app.add_handler(CallbackQueryHandler(ban_callback, pattern="^ban_"))
    app.add_handler(CallbackQueryHandler(unban_callback, pattern="^unban_"))
    app.add_handler(CallbackQueryHandler(addbal_callback, pattern="^addbal_"))
    app.add_handler(CallbackQueryHandler(dedbal_callback, pattern="^dedbal_"))
    app.add_handler(CallbackQueryHandler(resetbal_callback, pattern="^resetbal_"))
    app.add_handler(CallbackQueryHandler(set_otp_group_callback, pattern="^set_otp_group$"))
    app.add_handler(CallbackQueryHandler(remove_group_monitoring_callback, pattern="^remove_group_monitoring$"))
    app.add_handler(CallbackQueryHandler(del_group_confirm_callback, pattern="^del_group_-?\\d+$"))
    app.add_handler(CallbackQueryHandler(toggle_health_callback, pattern="^toggle_health$"))
    app.add_handler(CallbackQueryHandler(set_health_threshold_callback, pattern="^set_health_threshold$"))
    app.add_handler(CallbackQueryHandler(set_health_reminder_callback, pattern="^set_health_reminder$"))
    app.add_handler(CallbackQueryHandler(set_health_window_callback, pattern="^set_health_window$"))
    app.add_handler(CallbackQueryHandler(toggle_maintenance_callback, pattern="^toggle_maintenance$"))
    app.add_handler(CallbackQueryHandler(set_maintenance_msg_callback, pattern="^set_maintenance_msg$"))
    app.add_handler(CallbackQueryHandler(admin_top_spenders_callback, pattern="^admin_top_spenders$"))
    app.add_handler(CallbackQueryHandler(admin_reset_stats_callback, pattern="^admin_reset_stats$"))
    app.add_handler(CallbackQueryHandler(admin_reset_stats_confirm_callback, pattern="^admin_reset_stats_confirm$"))
    app.add_handler(CallbackQueryHandler(admin_services_callback, pattern="^admin_services$"))
    app.add_handler(CallbackQueryHandler(svc_toggle_callback, pattern="^svc_toggle_"))
    app.add_handler(CallbackQueryHandler(svc_delete_callback, pattern="^svc_delete_"))
    app.add_handler(CallbackQueryHandler(svc_add_callback, pattern="^svc_add$"))
    app.add_handler(CallbackQueryHandler(svc_setprice_callback, pattern="^svc_price_"))
    app.add_handler(CallbackQueryHandler(svc_otpcount_callback, pattern="^svc_otpcount_"))
    app.add_handler(CallbackQueryHandler(svc_otpdigits_callback, pattern="^svc_otpdigits_"))
    app.add_handler(CallbackQueryHandler(apply_digit_suggest_callback, pattern="^apply_digit_suggest_"))
    app.add_handler(CallbackQueryHandler(svc_keywords_callback, pattern="^svc_keywords_"))
    app.add_handler(CallbackQueryHandler(svc_kw_add_callback, pattern="^svc_kw_add_"))
    app.add_handler(CallbackQueryHandler(svc_kw_del_callback, pattern="^svc_kw_del_"))
    # ----- Bulk Stock Clear (multi-select) -----
    app.add_handler(CallbackQueryHandler(bulk_clear_start_callback,     pattern="^bulk_clear_start$"))
    app.add_handler(CallbackQueryHandler(bulk_clear_all_callback,       pattern="^bulk_clear_all$"))
    app.add_handler(CallbackQueryHandler(bulk_clear_none_callback,      pattern="^bulk_clear_none$"))
    app.add_handler(CallbackQueryHandler(bulk_clear_confirm_callback,   pattern="^bulk_clear_confirm$"))
    app.add_handler(CallbackQueryHandler(bulk_clear_back_callback,      pattern="^bulk_clear_back$"))
    app.add_handler(CallbackQueryHandler(bulk_clear_final_yes_callback, pattern="^bulk_clear_final_yes$"))
    app.add_handler(CallbackQueryHandler(bulk_clear_toggle_callback,    pattern="^bulk_clear_tog_"))
    # ----- Bulk Stock Add (multi-select) -----
    app.add_handler(CallbackQueryHandler(bulk_add_start_callback,   pattern="^bulk_add_start$"))
    app.add_handler(CallbackQueryHandler(bulk_add_all_callback,     pattern="^bulk_add_all$"))
    app.add_handler(CallbackQueryHandler(bulk_add_none_callback,    pattern="^bulk_add_none$"))
    app.add_handler(CallbackQueryHandler(bulk_add_confirm_callback, pattern="^bulk_add_confirm$"))
    app.add_handler(CallbackQueryHandler(bulk_add_toggle_callback,  pattern="^bulk_add_tog_"))
    # ----- Bulk Service Delete (multi-select) -----
    app.add_handler(CallbackQueryHandler(bulk_del_start_callback,     pattern="^svc_bulk_del_start$"))
    app.add_handler(CallbackQueryHandler(bulk_del_all_callback,       pattern="^bulk_del_all$"))
    app.add_handler(CallbackQueryHandler(bulk_del_none_callback,      pattern="^bulk_del_none$"))
    app.add_handler(CallbackQueryHandler(bulk_del_confirm_callback,   pattern="^bulk_del_confirm$"))
    app.add_handler(CallbackQueryHandler(bulk_del_back_callback,      pattern="^bulk_del_back$"))
    app.add_handler(CallbackQueryHandler(bulk_del_final_yes_callback, pattern="^bulk_del_final_yes$"))
    app.add_handler(CallbackQueryHandler(bulk_del_toggle_callback,    pattern="^bulk_del_tog_"))
    # ----- Bulk Price Change (multi-select) -----
    app.add_handler(CallbackQueryHandler(bulk_price_start_callback,   pattern="^bulk_price_start$"))
    app.add_handler(CallbackQueryHandler(bulk_price_all_callback,     pattern="^bulk_price_all$"))
    app.add_handler(CallbackQueryHandler(bulk_price_none_callback,    pattern="^bulk_price_none$"))
    app.add_handler(CallbackQueryHandler(bulk_price_confirm_callback, pattern="^bulk_price_confirm$"))
    app.add_handler(CallbackQueryHandler(bulk_price_toggle_callback,  pattern="^bulk_price_tog_"))
    # ----- Bulk Digit Change (multi-select) -----
    app.add_handler(CallbackQueryHandler(bulk_digits_start_callback,   pattern="^bulk_digits_start$"))
    app.add_handler(CallbackQueryHandler(bulk_digits_all_callback,     pattern="^bulk_digits_all$"))
    app.add_handler(CallbackQueryHandler(bulk_digits_none_callback,    pattern="^bulk_digits_none$"))
    app.add_handler(CallbackQueryHandler(bulk_digits_confirm_callback, pattern="^bulk_digits_confirm$"))
    app.add_handler(CallbackQueryHandler(bulk_digits_toggle_callback,  pattern="^bulk_digits_tog_"))
    # ----- Auto-extract keyword save/edit -----
    app.add_handler(CallbackQueryHandler(svc_extract_save_callback, pattern="^svc_extract_save$"))
    app.add_handler(CallbackQueryHandler(svc_extract_edit_callback, pattern="^svc_extract_edit$"))

    # Safety net: any unmatched bulk_* / svc_extract_* / svc_bulk_* callback
    # gets a clear alert instead of silently spinning forever.
    async def _bulk_unmatched(update, context):
        q = update.callback_query
        try:
            await q.answer(
                f"⚠️ Bulk handler missing for: {q.data}\nBot restart ya redeploy zaruri hai.",
                show_alert=True
            )
        except Exception:
            pass
    app.add_handler(CallbackQueryHandler(_bulk_unmatched, pattern="^(bulk_|svc_bulk_|svc_extract_)"))

    app.add_handler(CallbackQueryHandler(admin_promos_callback, pattern="^admin_promos$"))
    app.add_handler(CallbackQueryHandler(promo_create_callback, pattern="^promo_create$"))
    app.add_handler(CallbackQueryHandler(promo_view_callback, pattern="^promo_view_"))
    app.add_handler(CallbackQueryHandler(promo_claimers_callback, pattern="^promo_claimers_"))
    app.add_handler(CallbackQueryHandler(promo_toggle_callback, pattern="^promo_toggle_"))
    app.add_handler(CallbackQueryHandler(promo_delete_callback, pattern="^promo_delete_"))
    app.add_handler(CallbackQueryHandler(redeem_promo_callback, pattern="^redeem_promo$"))

    app.add_handler(CallbackQueryHandler(admin_user_notes_callback, pattern="^notes_"))
    app.add_handler(CallbackQueryHandler(admin_add_note_callback, pattern="^addnote_"))
    app.add_handler(CallbackQueryHandler(admin_del_note_callback, pattern="^delnote_"))

    app.add_handler(CallbackQueryHandler(admin_recent_otps_callback, pattern="^admin_recent_otps$"))
    app.add_handler(CallbackQueryHandler(deposit_upi_callback, pattern="^deposit_upi$"))

    # Rocket / ALOO payment method selection
    app.add_handler(CallbackQueryHandler(pay_aloo_callback,    pattern="^pay_aloo_"))
    app.add_handler(CallbackQueryHandler(pay_rocket_callback,  pattern="^pay_rocket_"))
    app.add_handler(CallbackQueryHandler(rocket_paid_handler,  pattern="^rocket_paid_"))

    # Admin payment method toggles
    app.add_handler(CallbackQueryHandler(toggle_aloo_payment_callback,   pattern="^toggle_aloo_payment$"))
    app.add_handler(CallbackQueryHandler(toggle_rocket_payment_callback, pattern="^toggle_rocket_payment$"))

    app.add_handler(CallbackQueryHandler(refund_callback, pattern="^refund$"))
    app.add_handler(CallbackQueryHandler(refund_pick_callback, pattern="^refund_pick_"))

    # Per-bot alert toggle (admin)
    app.add_handler(CallbackQueryHandler(admin_alert_bots_callback, pattern="^admin_alert_bots$"))
    app.add_handler(CallbackQueryHandler(alert_toggle_callback, pattern="^alert_toggle_"))
    app.add_handler(CallbackQueryHandler(alert_all_toggle_callback, pattern="^alert_all_(on|off)$"))

    # Flash sale (admin)
    app.add_handler(CallbackQueryHandler(admin_flash_sale_callback, pattern="^admin_flash_sale$"))
    app.add_handler(CallbackQueryHandler(flash_create_callback, pattern="^flash_create$"))
    app.add_handler(CallbackQueryHandler(flash_stop_callback, pattern="^flash_stop$"))
    app.add_handler(CallbackQueryHandler(flash_pick_callback, pattern="^flash_pick_"))

    # Top-up bonus (admin)
    app.add_handler(CallbackQueryHandler(admin_topup_bonus_callback, pattern="^admin_topup_bonus$"))
    app.add_handler(CallbackQueryHandler(topup_add_callback, pattern="^topup_add$"))
    app.add_handler(CallbackQueryHandler(topup_del_callback, pattern="^topup_del_"))
    app.add_handler(CallbackQueryHandler(topup_clear_callback, pattern="^topup_clear$"))

    # Service search & pagination shortcuts (for when service list grows large)
    app.add_handler(CallbackQueryHandler(service_search_callback, pattern="^svc_search$"))
    app.add_handler(CallbackQueryHandler(service_page_callback, pattern="^svc_page_"))
    # No-op for the "📄 page X" indicator button
    app.add_handler(CallbackQueryHandler(lambda u, c: u.callback_query.answer(), pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(refund_approve_callback, pattern="^refund_approve_"))
    app.add_handler(CallbackQueryHandler(refund_reject_callback, pattern="^refund_reject_"))

    app.add_handler(MessageHandler(
        (filters.VIDEO | filters.VIDEO_NOTE | filters.Document.VIDEO) & filters.ChatType.PRIVATE & ~filters.COMMAND,
        handle_refund_video
    ))

    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_screenshot))

    app.add_handler(MessageHandler(
        (filters.TEXT | filters.Caption(None)) & ~filters.COMMAND & filters.ChatType.GROUPS,
        group_message_listener
    ))

    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_text
    ))

    logger.info("[BOOT] 🚀 Bot starting — polling mode...")
    logger.info("[BOOT] Features active: multi-OTP, first-buy-discount, history-filters, favorites, blacklist, refunds")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
