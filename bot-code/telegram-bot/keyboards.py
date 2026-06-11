from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import CHANNELS


def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("🛒  Buy OTP", callback_data="buy_otp")],
        [InlineKeyboardButton("💰  Deposit",   callback_data="deposit"),
         InlineKeyboardButton("👤  Profile",   callback_data="profile")],
        [InlineKeyboardButton("🎁  Refer & Earn", callback_data="refer"),
         InlineKeyboardButton("📋  History",   callback_data="history")],
        [InlineKeyboardButton("🎟  Redeem Promo Code", callback_data="redeem_promo")],
        [InlineKeyboardButton("🔄  Refund Request", callback_data="refund")],
        [InlineKeyboardButton("🔧  Service Request", callback_data="service_request")],
        [InlineKeyboardButton("💬  Support",   callback_data="support")],
    ]
    return InlineKeyboardMarkup(keyboard)


def force_join_keyboard():
    keyboard = []
    for i, ch in enumerate(CHANNELS, 1):
        url = ch.get("url", "")
        if url:
            keyboard.append([InlineKeyboardButton(f"📢  Join Channel {i}", url=url)])
    keyboard.append([InlineKeyboardButton("✅  I've Joined — Check Now", callback_data="check_join")])
    return InlineKeyboardMarkup(keyboard)


def service_select_keyboard(services_with_stock: list, favorites: list = None,
                             show_search: bool = True, page: int = 0, per_page: int = 8,
                             flash_discounts: dict = None):
    """services_with_stock: list of (service_name, count) tuples.
    favorites: list of service names to highlight at top with ⭐.
    flash_discounts: dict[service_name -> discount %]. Adds 🔥X% OFF badge.
    Auto-paginates and shows search button when service count >= 6."""
    keyboard = []
    favorites = favorites or []
    flash_discounts = flash_discounts or {}
    fav_set = {f for f in favorites if any(n == f for n, _ in services_with_stock)}

    def _label(stock_emoji: str, name: str, count: int, fav: bool = False) -> str:
        prefix = "⭐" if fav else stock_emoji
        disc = flash_discounts.get(name, 0)
        if disc > 0:
            # Compact label so it fits Telegram button width
            return f"{prefix} {name} • {count}  🔥{disc:g}% OFF"
        return f"{prefix} {name}  •  {count} avail"

    total = len(services_with_stock)
    # Show search prominently if many services
    if show_search and total >= 6:
        keyboard.append([InlineKeyboardButton("🔍  Search Service (Type karke dhundo)", callback_data="svc_search")])

    # Favorites first (always visible, not paginated)
    if fav_set:
        for fav in favorites:
            for name, count in services_with_stock:
                if name == fav:
                    keyboard.append([
                        InlineKeyboardButton(_label("", name, count, fav=True),
                                              callback_data=f"buy_service_{name}")
                    ])
                    break

    # Non-favorites — paginated
    non_fav = [(n, c) for n, c in services_with_stock if n not in fav_set]
    start = page * per_page
    end = start + per_page
    page_items = non_fav[start:end]
    for name, count in page_items:
        stock_emoji = "🟢" if count > 5 else ("🟡" if count > 0 else "🔴")
        keyboard.append([
            InlineKeyboardButton(_label(stock_emoji, name, count),
                                  callback_data=f"buy_service_{name}")
        ])

    # Pagination row
    has_prev = page > 0
    has_next = end < len(non_fav)
    if has_prev or has_next:
        nav = []
        if has_prev:
            nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"svc_page_{page - 1}"))
        nav.append(InlineKeyboardButton(f"📄 {page + 1}", callback_data="noop"))
        if has_next:
            nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"svc_page_{page + 1}"))
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("🔙  Back to Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def service_search_results_keyboard(matches: list, query_text: str = ""):
    """Show matching services from a search query."""
    keyboard = []
    for name, count in matches[:15]:
        stock_emoji = "🟢" if count > 5 else ("🟡" if count > 0 else "🔴")
        keyboard.append([
            InlineKeyboardButton(f"{stock_emoji} {name}  •  {count} avail",
                                  callback_data=f"buy_service_{name}")
        ])
    keyboard.append([InlineKeyboardButton("🔍 Search Again", callback_data="svc_search")])
    keyboard.append([InlineKeyboardButton("📋 Show All Services", callback_data="buy_otp")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def buy_otp_keyboard(service: str = ""):
    keyboard = [
        [InlineKeyboardButton("✅  Confirm & Buy", callback_data=f"confirm_buy_{service}")],
        [InlineKeyboardButton("🔙  Back", callback_data="buy_otp")],
    ]
    return InlineKeyboardMarkup(keyboard)


def waiting_keyboard():
    keyboard = [
        [InlineKeyboardButton("❌  Cancel Order", callback_data="cancel_order")],
    ]
    return InlineKeyboardMarkup(keyboard)


def deposit_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔙  Back to Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def back_keyboard():
    keyboard = [
        [InlineKeyboardButton("🔙  Back to Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📦 Stock",        callback_data="admin_stock"),
         InlineKeyboardButton("💰 Deposits",     callback_data="admin_deposits")],
        [InlineKeyboardButton("👥 Users",        callback_data="admin_users"),
         InlineKeyboardButton("📊 Stats",        callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast",    callback_data="admin_broadcast"),
         InlineKeyboardButton("📜 Logs",         callback_data="admin_logs")],
        [InlineKeyboardButton("⚙️ Settings",     callback_data="admin_settings"),
         InlineKeyboardButton("🧾 Export",       callback_data="admin_export")],
        [InlineKeyboardButton("🔁 Mode Control", callback_data="admin_mode"),
         InlineKeyboardButton("✋ Manual",       callback_data="admin_manual")],
        [InlineKeyboardButton("🏆 Top Spenders", callback_data="admin_top_spenders"),
         InlineKeyboardButton("🗑 Reset Stats",  callback_data="admin_reset_stats")],
        [InlineKeyboardButton("🛠 Services",     callback_data="admin_services"),
         InlineKeyboardButton("🎁 Promo Codes",  callback_data="admin_promos")],
        [InlineKeyboardButton("🔥 Flash Sale",   callback_data="admin_flash_sale"),
         InlineKeyboardButton("💎 Top-up Bonus", callback_data="admin_topup_bonus")],
        [InlineKeyboardButton("💰 Deposit Stats", callback_data="admin_deposit_stats"),
         InlineKeyboardButton("💳 Wallet Balances", callback_data="admin_wallet_balances")],
        [InlineKeyboardButton("📥 Users Export", callback_data="admin_users_export"),
         InlineKeyboardButton("📤 Restore Balances", callback_data="admin_restore_balances")],
        [InlineKeyboardButton("📋 Last 50 OTPs", callback_data="admin_recent_otps")],
    ]
    return InlineKeyboardMarkup(keyboard)


def topup_bonus_keyboard(slabs: list):
    """slabs: list of {min, max, bonus_pct}, sorted ascending by min."""
    rows = []
    for i, s in enumerate(slabs):
        mn = float(s.get("min", 0))
        mx = float(s.get("max", 0))
        pct = float(s.get("bonus_pct", 0))
        label = f"₹{mn:g}–₹{mx:g}  →  +{pct:g}%"
        rows.append([
            InlineKeyboardButton(label, callback_data="noop"),
            InlineKeyboardButton("🗑", callback_data=f"topup_del_{i}"),
        ])
    rows.append([InlineKeyboardButton("➕ Add Slab", callback_data="topup_add")])
    if slabs:
        rows.append([InlineKeyboardButton("🗑 Clear All Slabs", callback_data="topup_clear")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
    return InlineKeyboardMarkup(rows)


def flash_sale_panel_keyboard(active: bool):
    rows = []
    if active:
        rows.append([InlineKeyboardButton("🛑 Stop Flash Sale", callback_data="flash_stop")])
        rows.append([InlineKeyboardButton("✏️ Edit (Restart)", callback_data="flash_create")])
    else:
        rows.append([InlineKeyboardButton("🆕 Create Flash Sale", callback_data="flash_create")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
    return InlineKeyboardMarkup(rows)


def flash_select_keyboard(services: list, selected: set, all_mode: bool):
    """Multi-select keyboard for picking services for flash sale.
    Tap toggles. ☑ = selected, ☐ = not. 'All' overrides individual selection."""
    rows = []
    all_emoji = "☑" if all_mode else "☐"
    rows.append([InlineKeyboardButton(f"{all_emoji}  🌐 ALL Services", callback_data="flash_pick_all")])
    rows.append([InlineKeyboardButton("───────────", callback_data="noop")])
    for s in services:
        name = s["name"]
        if all_mode:
            emoji = "✅"
        else:
            emoji = "☑" if name in selected else "☐"
        active = s.get("active", True)
        suffix = "" if active else "  (off)"
        rows.append([InlineKeyboardButton(f"{emoji}  {name}{suffix}", callback_data=f"flash_pick_{name}")])
    count = "ALL" if all_mode else str(len(selected))
    rows.append([InlineKeyboardButton(f"✅ Confirm ({count} selected) →", callback_data="flash_pick_confirm")])
    rows.append([InlineKeyboardButton("🔙 Cancel", callback_data="admin_flash_sale")])
    return InlineKeyboardMarkup(rows)


def admin_promos_keyboard(codes: list):
    keyboard = []
    for p in codes:
        code = p["code"]
        amt = p.get("amount", 0)
        claimed = len(p.get("claimed_by", []))
        max_c = int(p.get("max_claims", 0) or 0)
        max_str = "∞" if max_c == 0 else str(max_c)
        status = "✅" if p.get("active", True) else "❌"
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {code} • ₹{amt:.0f} • {claimed}/{max_str}",
                callback_data=f"promo_view_{code}"
            )
        ])
    keyboard.append([InlineKeyboardButton("➕ Naya Promo Code", callback_data="promo_create")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
    return InlineKeyboardMarkup(keyboard)


def admin_promo_actions_keyboard(code: str, active: bool):
    toggle_label = "⏸ Disable" if active else "▶️ Enable"
    keyboard = [
        [InlineKeyboardButton("👥 Claimers Dekho", callback_data=f"promo_claimers_{code}")],
        [InlineKeyboardButton(toggle_label, callback_data=f"promo_toggle_{code}"),
         InlineKeyboardButton("🗑 Delete", callback_data=f"promo_delete_{code}")],
        [InlineKeyboardButton("🔙 Back to List", callback_data="admin_promos")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_services_keyboard(services: list, page: int = 0, per_page: int = 10):
    keyboard = []
    total = len(services)
    start = page * per_page
    end = start + per_page
    page_services = services[start:end]
    for s in page_services:
        sid = str(s["_id"])
        status = "✅" if s.get("active") else "❌"
        price = s.get("price")
        price_str = f"₹{price}" if price is not None else "def"
        otp_count = s.get("otp_count", 1) or 1
        digits = s.get("otp_digits", [4, 5, 6])
        digits_str = "/".join(str(d) for d in sorted(digits))
        # Row 1: full-width name button (so full name is visible)
        keyboard.append([
            InlineKeyboardButton(
                f"{status} {s['name']}  ({price_str}, {otp_count}x, {digits_str}d)",
                callback_data=f"svc_toggle_{sid}"
            ),
        ])
        # Row 2: action buttons
        keyboard.append([
            InlineKeyboardButton("💵 Price", callback_data=f"svc_price_{sid}"),
            InlineKeyboardButton("🔢 Count", callback_data=f"svc_otpcount_{sid}"),
            InlineKeyboardButton("📏 Digits", callback_data=f"svc_otpdigits_{sid}"),
            InlineKeyboardButton("🔑 Keys", callback_data=f"svc_keywords_{sid}"),
            InlineKeyboardButton("🗑", callback_data=f"svc_delete_{sid}"),
        ])
    has_prev = page > 0
    has_next = end < total
    if has_prev or has_next:
        total_pages = (total + per_page - 1) // per_page
        nav = []
        if has_prev:
            nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"admin_svc_page_{page - 1}"))
        nav.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
        if has_next:
            nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"admin_svc_page_{page + 1}"))
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("➕ Add Service", callback_data="svc_add")])
    keyboard.append([InlineKeyboardButton("🗑 Bulk Delete Services", callback_data="svc_bulk_del_start")])
    keyboard.append([
        InlineKeyboardButton("💵 Bulk Price",  callback_data="bulk_price_start"),
        InlineKeyboardButton("📏 Bulk Digits", callback_data="bulk_digits_start"),
    ])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
    return InlineKeyboardMarkup(keyboard)


def bulk_select_keyboard(services: list, selected: set, action: str):
    """Generic multi-select checkbox keyboard for services.
    action: 'clear' | 'add' | 'del' | 'price' | 'digits' — controls callback prefixes and confirm button label.
    """
    keyboard = []
    for s in services:
        name = s["name"]
        checked = "☑" if name in selected else "☐"
        keyboard.append([
            InlineKeyboardButton(f"{checked} {name}", callback_data=f"bulk_{action}_tog_{name}")
        ])
    keyboard.append([
        InlineKeyboardButton("✅ Select All", callback_data=f"bulk_{action}_all"),
        InlineKeyboardButton("⬜ Clear All", callback_data=f"bulk_{action}_none"),
    ])
    if action == "clear":
        confirm_label = f"🧹 Clear Stock ({len(selected)})"
        back_cb = "admin_stock"
    elif action == "add":
        confirm_label = f"➡️ Next: Paste Numbers ({len(selected)})"
        back_cb = "admin_stock"
    elif action == "price":
        confirm_label = f"➡️ Next: Set Price ({len(selected)})"
        back_cb = "admin_services"
    elif action == "digits":
        confirm_label = f"➡️ Next: Set Digits ({len(selected)})"
        back_cb = "admin_services"
    else:
        confirm_label = f"🗑 Delete Services ({len(selected)})"
        back_cb = "admin_services"
    keyboard.append([InlineKeyboardButton(confirm_label, callback_data=f"bulk_{action}_confirm")])
    keyboard.append([InlineKeyboardButton("🔙 Cancel", callback_data=back_cb)])
    return InlineKeyboardMarkup(keyboard)


def bulk_final_confirm_keyboard(action: str):
    """Final yes/no confirm before destructive action."""
    if action == "clear":
        yes_cb = "bulk_clear_final_yes"
        cancel_cb = "bulk_clear_back"
    else:
        yes_cb = "bulk_del_final_yes"
        cancel_cb = "bulk_del_back"
    keyboard = [[
        InlineKeyboardButton("✅ Haan, Confirm", callback_data=yes_cb),
        InlineKeyboardButton("❌ Cancel", callback_data=cancel_cb),
    ]]
    return InlineKeyboardMarkup(keyboard)


def svc_add_extracted_keyboard():
    """Shown after auto-extracting from pasted SMS — admin can save or edit."""
    keyboard = [
        [InlineKeyboardButton("✅ Save", callback_data="svc_extract_save")],
        [InlineKeyboardButton("✏️ Edit Manually", callback_data="svc_extract_edit")],
        [InlineKeyboardButton("🔙 Cancel", callback_data="admin_services")],
    ]
    return InlineKeyboardMarkup(keyboard)


def reset_stats_confirm_keyboard():
    keyboard = [
        [InlineKeyboardButton("✅ Haan, Reset Karo", callback_data="admin_reset_stats_confirm"),
         InlineKeyboardButton("❌ Cancel",            callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_stock_keyboard(services: list = None, summary: dict = None):
    """Shows per-service stock buttons if services provided, else generic."""
    keyboard = []
    if services:
        for s in services:
            name = s["name"]
            count = (summary or {}).get(name, 0)
            status = "✅" if s.get("active") else "❌"
            keyboard.append([
                InlineKeyboardButton(
                    f"{status} {name}  —  {count} in stock",
                    callback_data=f"stock_svc_{name}"
                )
            ])
    keyboard.append([
        InlineKeyboardButton("📦 Bulk Add (Multi)", callback_data="bulk_add_start"),
        InlineKeyboardButton("🧹 Bulk Clear (Multi)", callback_data="bulk_clear_start"),
    ])
    keyboard.append([InlineKeyboardButton("🧹 Clear All Stock", callback_data="stock_clear_all")])
    keyboard.append([
        InlineKeyboardButton("🗑 Smart Remove", callback_data="smart_remove"),
        InlineKeyboardButton("📊 Sold OTPs", callback_data="admin_sold_otp"),
    ])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="admin_back")])
    return InlineKeyboardMarkup(keyboard)


def admin_stock_manage_keyboard(service: str):
    keyboard = [
        [InlineKeyboardButton("➕ Add Numbers",       callback_data=f"stock_add_{service}"),
         InlineKeyboardButton("📋 View Stock",        callback_data=f"stock_view_{service}")],
        [InlineKeyboardButton("🗑 Remove One Number", callback_data=f"stock_remove_{service}")],
        [InlineKeyboardButton(f"🧹 Clear All {service} Stock", callback_data=f"stock_clear_svc_{service}")],
        [InlineKeyboardButton("🔙 Back to Stock",     callback_data="admin_stock")],
    ]
    return InlineKeyboardMarkup(keyboard)


def stock_clear_confirm_keyboard(service: str = ""):
    """If service provided → per-service clear confirm, else → global clear."""
    if service:
        confirm_cb = f"stock_clear_svc_confirm_{service}"
        cancel_cb  = f"stock_svc_{service}"
    else:
        confirm_cb = "stock_clear_confirm"
        cancel_cb  = "admin_stock"
    keyboard = [
        [InlineKeyboardButton("✅ Haan, Delete Karo", callback_data=confirm_cb),
         InlineKeyboardButton("❌ Cancel",             callback_data=cancel_cb)],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_refund_keyboard(refund_id: str):
    keyboard = [
        [InlineKeyboardButton("✅ Approve Refund", callback_data=f"refund_approve_{refund_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"refund_reject_{refund_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_deposit_approve_keyboard(deposit_id: str):
    keyboard = [
        [InlineKeyboardButton("✅ Approve", callback_data=f"dep_approve_{deposit_id}"),
         InlineKeyboardButton("❌ Reject",  callback_data=f"dep_reject_{deposit_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_logs_keyboard():
    keyboard = [
        [InlineKeyboardButton("📤 OTP Logs",      callback_data="log_otp"),
         InlineKeyboardButton("💰 Deposit Logs",  callback_data="log_deposit")],
        [InlineKeyboardButton("❌ Cancel Logs",   callback_data="log_cancel"),
         InlineKeyboardButton("🎁 Referral Logs", callback_data="log_referral")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def payment_method_select_keyboard(aloo_amount: float, rocket_amount: float, aloo_enabled: bool = True, rocket_enabled: bool = False):
    """User selects payment method when both are active.
    aloo_amount  — amount with random paise (for ALOO uniqueness)
    rocket_amount — exact amount the user typed (Rocket uses order_id for uniqueness)
    """
    keyboard = []
    if rocket_enabled:
        keyboard.append([InlineKeyboardButton("🚀  Rocket", callback_data=f"pay_rocket_{rocket_amount}")])
    if aloo_enabled:
        keyboard.append([InlineKeyboardButton("💳  ALOO", callback_data=f"pay_aloo_{aloo_amount}")])
    keyboard.append([InlineKeyboardButton("❌  Cancel", callback_data="main_menu")])
    return InlineKeyboardMarkup(keyboard)


def admin_settings_keyboard(health_enabled: bool = True, maintenance_enabled: bool = False, aloo_enabled: bool = True, rocket_enabled: bool = False):
    health_label = "🟢 Health Monitor: ON" if health_enabled else "🔴 Health Monitor: OFF"
    maint_label = "🛠 Maintenance: ON 🔴" if maintenance_enabled else "🛠 Maintenance: OFF 🟢"
    keyboard = [
        [InlineKeyboardButton("💵 OTP Price",   callback_data="set_price"),
         InlineKeyboardButton("🎁 Referral %",  callback_data="set_referral")],
        [InlineKeyboardButton("⏱ Wait Time",   callback_data="set_wait"),
         InlineKeyboardButton("⏳ Cancel Time", callback_data="set_cancel")],
        [InlineKeyboardButton("🏦 UPI ID",      callback_data="set_upi"),
         InlineKeyboardButton("🖼 QR Code",     callback_data="set_qr")],
        [InlineKeyboardButton("💵 Min Deposit", callback_data="set_min_deposit")],
        [InlineKeyboardButton("🆕 First-Buy Discount %", callback_data="set_first_buy_disc")],
        [InlineKeyboardButton("🧠 Smart Match Cache Size", callback_data="set_cache_size")],
        [InlineKeyboardButton("📱 SMS Auto-Verify Status", callback_data="admin_sms_status")],
        [InlineKeyboardButton("📜 Used UTRs (last 50)",   callback_data="admin_used_utrs")],
        [InlineKeyboardButton("📡 Set OTP Group", callback_data="set_otp_group")],
        [InlineKeyboardButton(maint_label, callback_data="toggle_maintenance"),
         InlineKeyboardButton("📝 Edit Maint Msg", callback_data="set_maintenance_msg")],
        [InlineKeyboardButton(health_label, callback_data="toggle_health")],
        [InlineKeyboardButton("⏰ Silence Threshold", callback_data="set_health_threshold"),
         InlineKeyboardButton("🔔 Reminder Gap", callback_data="set_health_reminder")],
        [InlineKeyboardButton("🤖 Bot Active Window", callback_data="set_health_window")],
        [InlineKeyboardButton("🔔 Per-Bot Alert Toggle", callback_data="admin_alert_bots")],
        [InlineKeyboardButton("🗑 Remove Group from Monitoring", callback_data="remove_group_monitoring")],
        [InlineKeyboardButton("━━━ Payment Methods ━━━", callback_data="noop")],
        [InlineKeyboardButton(f"{'🟢' if aloo_enabled else '🔴'} ALOO: {'ON' if aloo_enabled else 'OFF'}", callback_data="toggle_aloo_payment"),
         InlineKeyboardButton(f"{'🟢' if rocket_enabled else '🔴'} Rocket: {'ON' if rocket_enabled else 'OFF'}", callback_data="toggle_rocket_payment")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def history_filter_keyboard(active: str = "all"):
    def mk(label, cb, key):
        return InlineKeyboardButton(("• " + label + " •") if active == key else label, callback_data=cb)
    keyboard = [
        [mk("All", "hist_filter_all", "all"),
         mk("7d", "hist_filter_7d", "7d"),
         mk("30d", "hist_filter_30d", "30d")],
        [InlineKeyboardButton("📦 By Service", callback_data="hist_filter_svc")],
        [InlineKeyboardButton("🔙  Back to Menu", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(keyboard)


def history_service_picker_keyboard(services: list):
    keyboard = []
    for name in services:
        keyboard.append([InlineKeyboardButton(name, callback_data=f"hist_svc_{name}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="history")])
    return InlineKeyboardMarkup(keyboard)


def admin_mode_keyboard(current_mode: str):
    auto_mark   = "✅ " if current_mode == "auto"   else ""
    manual_mark = "✅ " if current_mode == "manual" else ""
    keyboard = [
        [InlineKeyboardButton(f"{auto_mark}🤖 AUTO MODE",   callback_data="mode_auto"),
         InlineKeyboardButton(f"{manual_mark}✋ MANUAL MODE", callback_data="mode_manual")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def admin_manual_keyboard():
    keyboard = [
        [InlineKeyboardButton("📱 Send Number", callback_data="manual_number"),
         InlineKeyboardButton("🔑 Send OTP",    callback_data="manual_otp")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def user_actions_keyboard(user_id: int, banned: bool):
    ban_text = "🔓 Unban" if banned else "🚫 Ban"
    ban_cb   = f"unban_{user_id}" if banned else f"ban_{user_id}"
    keyboard = [
        [InlineKeyboardButton("➕ Add Balance",    callback_data=f"addbal_{user_id}"),
         InlineKeyboardButton("➖ Deduct Balance", callback_data=f"dedbal_{user_id}")],
        [InlineKeyboardButton("🔄 Reset Balance → 0", callback_data=f"resetbal_{user_id}")],
        [InlineKeyboardButton(ban_text, callback_data=ban_cb),
         InlineKeyboardButton("📝 Notes", callback_data=f"notes_{user_id}")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)


def smart_remove_service_keyboard(services: list, selected: set, remove_type: str):
    """Multi-select keyboard for services in Smart Remove."""
    rows = []
    for s in services:
        name = s["name"]
        check = "☑" if name in selected else "☐"
        rows.append([InlineKeyboardButton(f"{check} {name}", callback_data=f"sr_svc_tog_{name}")])
    rows.append([
        InlineKeyboardButton("✅ Select All", callback_data="sr_svc_all"),
        InlineKeyboardButton("⬜ Clear All",  callback_data="sr_svc_none"),
    ])
    label = f"🗑 Remove from {len(selected)} service(s)" if selected else "⚠️ Select at least 1"
    rows.append([InlineKeyboardButton(label, callback_data="sr_svc_confirm")])
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="smart_remove")])
    return InlineKeyboardMarkup(rows)


def sold_otp_list_keyboard(summary: list):
    """Service list with sold OTP counts."""
    rows = []
    for item in summary:
        svc = item["service"]
        cnt = item["count"]
        rows.append([InlineKeyboardButton(
            f"🟢 {svc}  •  {cnt} sold",
            callback_data=f"sold_svc_{svc}"
        )])
    rows.append([InlineKeyboardButton("🔙 Back to Stock", callback_data="admin_stock")])
    return InlineKeyboardMarkup(rows)

