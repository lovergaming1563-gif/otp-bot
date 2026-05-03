import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")

# Module-level cache of recent device_ids from OTP group (newest first).
# Refreshed every 5s by recent_device_ids_loop. Read by buy handler.
recent_device_ids: list = []


def get_recent_device_ids() -> list:
    """Return current snapshot of recent device_ids (newest first)."""
    return list(recent_device_ids)


async def main():
    if not SESSION_STRING or not API_ID or not API_HASH:
        logger.warning("Userbot disabled — API_ID, API_HASH or SESSION_STRING not set.")
        return

    try:
        from pyrogram import Client, filters
        from pyrogram.types import Message
    except ImportError:
        logger.error("pyrogram not installed — userbot disabled.")
        return

    from database import (
        get_session_by_device, update_session_status,
        deduct_balance, delete_number_from_stock, add_log,
        get_mode, get_settings, get_otp_group_id, init_db,
        get_all_active_sessions, save_pending_otp,
        get_pending_otp, clear_pending_otp, get_service_price,
        set_recent_device_ids, get_recent_device_ids_db,
        add_recent_device_id
    )
    from otp_listener import (
        detect_message_service, extract_otp_code,
        extract_device_id, build_clean_otp_message,
        clean_sms_for_history
    )
    from database import get_service_otp_digits as _get_otp_digits
    from config import BOT_TOKEN, SERVICE_NAME
    from keyboards import main_menu_keyboard
    from telegram import Bot

    await init_db()

    app = Client(
        "userbot",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=SESSION_STRING,
    )

    async def _userbot_alert_admin(bot, msg_text: str):
        """Send a plain alert to all admins via bot (no context object in userbot)."""
        from config import ADMIN_IDS
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        from otp_listener import _extract_sender_from_text
        wider_otp = extract_otp_code(msg_text, allowed_digits=[3, 4, 5, 6, 7, 8])
        if not wider_otp:
            return
        sender = _extract_sender_from_text(msg_text)
        snippet = msg_text[:300].replace("`", "'")
        sender_line = f"\n📡  Sender detected: `{sender}`" if sender else ""
        msg = (
            f"🚨 *[Userbot] Unknown OTP — No service keyword matched!*\n"
            f"{sender_line}\n"
            f"🔢  OTP found: `{wider_otp}`\n\n"
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
                await bot.send_message(chat_id=admin_id, text=msg, reply_markup=kb, parse_mode="Markdown")
            except Exception as e:
                logger.warning(f"[USERBOT][UNKNOWN_OTP] alert failed for {admin_id}: {e}")

    async def process_otp(text: str):
        mode = await get_mode()
        if mode != "auto":
            return

        from database import get_services as _get_services
        text_lower = text.lower()

        # ── STEP 1: Extract device_id ──
        device_id = extract_device_id(text)

        # ── STEP 2: Find session by device_id → get the user-bought service ──
        session = None
        if device_id:
            session = await get_session_by_device(device_id)
            logger.info(f"[USERBOT] device_id={device_id!r} → session found={session is not None}")

        if not session:
            if device_id:
                # device_id present but no session — keep it in pending; a future
                # buy with the same device_id will pick it up (with full validation).
                logger.warning(f"[USERBOT] device_id ({device_id}) matched no session — saving to pending queue")
                # Save with a wider OTP digit window so pending_otp_checker can re-derive
                wider_otp = extract_otp_code(text, allowed_digits=[3, 4, 5, 6, 7, 8])
                if wider_otp:
                    await save_pending_otp(text, wider_otp)
                return

            # No device_id at all — fallback: find a service via keyword, then deliver
            # only if exactly 1 no-device session is waiting for that service.
            services = await _get_services()
            matched_service = None
            for s in services:
                if not s.get("active"):
                    continue
                kws = [kw.lower() for kw in s.get("keywords", [])]
                if any(kw in text_lower for kw in kws):
                    matched_service = s["name"]
                    break
            if not matched_service:
                logger.info("[USERBOT] no device_id and no service keyword matched — skip")
                return

            active = await get_all_active_sessions()
            waiting = [s for s in active if s.get("status") == "waiting" and not s.get("device_id")
                       and s.get("service") == matched_service]
            if len(waiting) != 1:
                logger.info(f"[USERBOT] No device_id, {len(waiting)} sessions for {matched_service} — saving pending")
                wider_otp = extract_otp_code(text, allowed_digits=[3, 4, 5, 6, 7, 8])
                if wider_otp:
                    await save_pending_otp(text, wider_otp)
                return
            session = waiting[0]
            logger.info(f"[USERBOT] No device_id fallback → user {session['user_id']} for {matched_service}")

        if session.get("status") != "waiting":
            return

        user_id = session["user_id"]
        number = session.get("number")
        service_name = session.get("service", "Myntra")

        # ── STEP 3: Verify the SESSION's service keyword is in the message ──
        services = await _get_services()
        session_service = next((s for s in services if s.get("name") == service_name), None)
        if not session_service:
            logger.warning(f"[USERBOT] session service '{service_name}' not found — skip")
            return
        svc_keywords = [kw.lower() for kw in session_service.get("keywords", [])]
        if not any(kw in text_lower for kw in svc_keywords):
            logger.info(f"[USERBOT] device_id matched user {user_id} ({service_name}) but no '{service_name}' keyword (tried={svc_keywords}) — skip")
            return
        logger.info(f"[USERBOT] keyword matched for service='{service_name}'")

        # ── STEP 4: Extract OTP using THAT service's digit setting ──
        allowed_digits = await _get_otp_digits(service_name)
        otp_code = extract_otp_code(text, allowed_digits=allowed_digits)
        if not otp_code:
            logger.info(f"[USERBOT] [{service_name}] keyword matched but no {allowed_digits}-digit OTP — skip")
            return
        logger.info(f"[USERBOT] service={service_name} otp={otp_code} device_id={device_id!r}")

        settings = await get_settings()
        global_price = settings.get("otp_price", 5.0)
        price = session.get("price")
        if price is None:
            price = await get_service_price(service_name, global_price)

        from database import consume_otp_slot, finalize_session_delivered, mark_first_buy_used
        updated = await consume_otp_slot(user_id, otp_code)
        if not updated:
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

        await add_log("otp_delivered", {
            "user_id": user_id,
            "service": service_name,
            "mode": "auto_userbot",
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
        bot = Bot(token=BOT_TOKEN)
        try:
            await bot.send_message(
                chat_id=user_id,
                text=delivery_msg,
                reply_markup=main_menu_keyboard(),
                parse_mode="Markdown"
            )
            logger.info(f"Userbot delivered OTP to user {user_id} | OTP: {otp_code}")
        except Exception as e:
            logger.error(f"Userbot failed to deliver OTP to {user_id}: {e}")

    @app.on_message(filters.all)
    async def on_any_message(client, message: Message):
        try:
            chat_type = getattr(message.chat, "type", None)
            chat_id = str(message.chat.id)
            chat_title = getattr(message.chat, "title", chat_id)
            text = message.text or message.caption

            msg_type = "text" if message.text else "photo" if message.photo else "document" if message.document else "sticker" if message.sticker else "other"
            logger.info(f"[USERBOT] [{chat_type}] '{chat_title}' (id={chat_id}) | type={msg_type} | from_bot={getattr(getattr(message, 'from_user', None), 'is_bot', '?')} | text={repr(text[:120]) if text else 'NO TEXT'}")

            chat_type_str = str(chat_type).lower()
            if not any(k in chat_type_str for k in ("group", "supergroup", "channel")):
                logger.info(f"[USERBOT] Skipped — not a group/channel (type={chat_type})")
                return

            logger.info(f"[USERBOT] Step1: group check passed")

            # ── SMS group routing ────────────────────────────────────────
            # Bot API can't read other bots' messages, so the SMS forwarder
            # (a 3rd-party bot) is invisible to the main bot. Userbot CAN see
            # it, so we feed those messages into the SMS verifier cache.
            try:
                from sms_verifier import SMS_GROUP_ID as _SMS_GID, verifier as _sms
                if _SMS_GID and chat_id == str(_SMS_GID):
                    if text:
                        result = _sms.add_from_message(text)
                        logger.info(f"[USERBOT][SMS] processed group message: {result}")
                        # Cross-process share: write parsed credit SMS to DB so
                        # the main bot (separate Python process) can find it.
                        if result.get("status") == "cached":
                            try:
                                from database import sms_cache_set
                                await sms_cache_set(result["utr"], result["amount"])
                                logger.info(f"[USERBOT][SMS] DB cache wrote UTR={result['utr']}")
                            except Exception as _de:
                                logger.warning(f"[USERBOT][SMS] DB cache write failed: {_de}")
                    return
            except Exception as _se:
                logger.warning(f"[USERBOT][SMS] routing failed: {_se}")

            otp_group_id = await get_otp_group_id()
            logger.info(f"[USERBOT] Step2: otp_group_id={otp_group_id}, chat_id={chat_id}")

            if otp_group_id and chat_id != str(otp_group_id):
                logger.info(f"[USERBOT] Ignored — not OTP group (expected {otp_group_id}, got {chat_id})")
                return

            # ── Health tracking (runs BEFORE text/mode checks) ──────────────
            # Userbot sees ALL messages including from other bots (Bot API can't),
            # so this is the ONLY reliable source for group + per-bot health.
            try:
                sender = getattr(message, "from_user", None) or getattr(message, "sender_chat", None)
                if sender:
                    sid = getattr(sender, "id", 0) or 0
                    sname = (
                        getattr(sender, "username", None)
                        or getattr(sender, "first_name", None)
                        or getattr(sender, "title", None)
                        or f"user_{sid}"
                    )
                    from database import record_group_activity
                    await record_group_activity(int(chat_id), int(sid), str(sname))
                    logger.info(f"[USERBOT][HEALTH] tracked msg from {sname} ({sid}) in group {chat_id}")
            except Exception as _he:
                logger.warning(f"[USERBOT][HEALTH] record activity failed: {_he}")

            if not text:
                logger.info(f"[USERBOT] Skipped — no text")
                return

            # Update recent device_ids cache (in DB so main bot process can read it).
            # Cache size is admin-configurable from Settings panel; helper handles
            # normalization (lowercase), dedupe, prepend, and trim to configured size.
            did = extract_device_id(text)
            if did:
                try:
                    await add_recent_device_id(did)
                    cached = await get_recent_device_ids_db()
                    logger.info(f"[USERBOT] Cache updated: device_id={did} | total cached={len(cached)}")
                except Exception as e:
                    logger.error(f"[USERBOT] cache update failed: {e}")

            logger.info(f"[USERBOT] Step3: text present, calling get_mode")
            mode = await get_mode()
            logger.info(f"[USERBOT] Step4: Mode={mode} | calling process_otp")

            await process_otp(text)
        except BaseException as e:
            logger.error(f"[USERBOT] handler error ({type(e).__name__}): {e}", exc_info=True)

    async def pending_otp_checker():
        """Every 4 seconds: re-try pending OTPs with strict device_id matching."""
        bot = Bot(token=BOT_TOKEN)
        while True:
            await asyncio.sleep(4)
            try:
                pending = await get_pending_otp()
                if not pending:
                    continue
                text = pending["text"]
                pending_device_id = extract_device_id(text)
                text_lower = text.lower()

                if pending_device_id:
                    session = await get_session_by_device(pending_device_id)
                    if not session:
                        logger.info(f"[PENDING] device_id ({pending_device_id}) still no session — waiting")
                        continue
                else:
                    all_waiting = await get_all_active_sessions()
                    no_device = [s for s in all_waiting if s.get("status") == "waiting" and not s.get("device_id")]
                    if len(no_device) != 1:
                        continue
                    session = no_device[0]

                user_id = session["user_id"]
                number = session.get("number")
                service_name = session.get("service", "Myntra")

                # Verify the SESSION's service keyword is in the message
                from database import get_services as _get_services
                services_now = await _get_services()
                session_service = next((s for s in services_now if s.get("name") == service_name), None)
                if not session_service:
                    logger.warning(f"[PENDING] session service '{service_name}' not found — drop pending")
                    await clear_pending_otp(pending["_id"])
                    continue
                svc_keywords = [kw.lower() for kw in session_service.get("keywords", [])]
                if not any(kw in text_lower for kw in svc_keywords):
                    logger.info(f"[PENDING] device_id matched user {user_id} ({service_name}) but no '{service_name}' keyword — drop pending")
                    await clear_pending_otp(pending["_id"])
                    continue

                # Re-extract OTP using the session-service's allowed digits
                allowed_digits = await _get_otp_digits(service_name)
                otp_code = extract_otp_code(text, allowed_digits=allowed_digits)
                if not otp_code:
                    logger.info(f"[PENDING] [{service_name}] no {allowed_digits}-digit OTP in pending text — drop")
                    await clear_pending_otp(pending["_id"])
                    continue

                settings = await get_settings()
                global_price = settings.get("otp_price", 5.0)
                price = session.get("price")
                if price is None:
                    price = await get_service_price(service_name, global_price)

                from database import consume_otp_slot, finalize_session_delivered, mark_first_buy_used
                updated = await consume_otp_slot(user_id, otp_code)
                if not updated:
                    continue
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

                await clear_pending_otp(pending["_id"])
                await add_log("otp_delivered", {
                    "user_id": user_id,
                    "service": service_name,
                    "mode": "auto_pending",
                    "otp_code": otp_code,
                    "sms_text": clean_sms_for_history(text),
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
                await bot.send_message(
                    chat_id=user_id,
                    text=delivery_msg,
                    reply_markup=main_menu_keyboard(),
                    parse_mode="Markdown"
                )
                logger.info(f"[USERBOT] Pending OTP delivered to user {user_id} | OTP: {otp_code}")
            except Exception as e:
                logger.error(f"[USERBOT] pending_otp_checker error: {e}")

    logger.info("Userbot starting...")
    await app.start()
    logger.info("Userbot connected — listening to group messages (including bots)!")
    asyncio.create_task(pending_otp_checker())
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    asyncio.run(main())
