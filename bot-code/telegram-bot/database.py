from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGODB_URL
import datetime
import re

client = None
db = None

# Recent device_ids cache — admin-configurable size (1..200), default 10.
DEFAULT_RECENT_DEVICES_CACHE_SIZE = 10
MIN_RECENT_DEVICES_CACHE_SIZE = 1
MAX_RECENT_DEVICES_CACHE_SIZE = 200

# ─────────────────────────────────────────────────────────────────────
# 🚀 Hot-read cache: settings / services / flash_sale rarely change,
# so we cache them in-process for a few seconds. This eliminates
# 3-5 redundant MongoDB roundtrips per button press (Atlas RTT ≈ 60ms).
# Writes call _cache_bump(key) to invalidate immediately.
# ─────────────────────────────────────────────────────────────────────
import time as _time
_CACHE_TTL = 30.0  # seconds
_cache_version = {"settings": 0, "services": 0, "flash": 0, "stock": 0}
_cache_settings = {"v": -1, "ts": 0.0, "data": None}
_cache_services = {"v": -1, "ts": 0.0, "data": None}
_cache_flash    = {"v": -1, "ts": 0.0, "data": None}
_cache_stock    = {"v": -1, "ts": 0.0, "data": None}
_STOCK_CACHE_TTL = 8.0  # stock changes more often, shorter TTL

def _cache_bump(key: str):
    _cache_version[key] = _cache_version.get(key, 0) + 1

def _cache_get(slot: dict, key: str):
    now = _time.monotonic()
    if slot["v"] == _cache_version[key] and (now - slot["ts"]) < _CACHE_TTL:
        return True, slot["data"]
    return False, None

def _cache_set(slot: dict, key: str, data):
    slot["v"] = _cache_version[key]
    slot["ts"] = _time.monotonic()
    slot["data"] = data


async def init_db():
    global client, db
    import certifi
    client = AsyncIOMotorClient(
        MONGODB_URL,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=30000,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000,
    )
    db = client["otpbot"]
    try:
        await db.command("ping")
        print("MongoDB connected successfully!")
    except Exception as e:
        print(f"MongoDB connection warning: {e}")
        print("IMPORTANT: Please whitelist IP 0.0.0.0/0 in MongoDB Atlas Network Access!")

    try:
        await db.users.create_index("user_id", unique=True)
        # Drop old single-field unique index if it exists (service-agnostic)
        try:
            await db.stock.drop_index("number_1")
        except Exception:
            pass
        # Compound unique: same number CAN exist in different services
        await db.stock.create_index([("number", 1), ("service", 1)], unique=True)
        await db.sessions.create_index("user_id")
        await db.sessions.create_index("device_id")
        await db.deposits.create_index("user_id")
        await db.logs.create_index("type")
        await db.pending_otps.create_index("created_at", expireAfterSeconds=600)
        await db.services.create_index("name", unique=True)
        # 🚀 Speed: compound index for user history & top-services aggregation
        await db.logs.create_index([("user_id", 1), ("type", 1), ("created_at", -1)])
        # 🚀 Speed: stock_summary + atomic_get queries hit "service" all the time
        await db.stock.create_index("service")
        await db.verified_utrs.create_index("utr", unique=True)
        await db.verified_utrs.create_index("created_at", expireAfterSeconds=30 * 24 * 60 * 60)
        # 📱 SMS cache shared between userbot process & main bot process.
        # TTL = 10 min (matches sms_verifier.CACHE_TTL_SECONDS).
        await db.sms_cache.create_index("utr", unique=True)
        await db.sms_cache.create_index("ts", expireAfterSeconds=600)
        # 🔔 One-time migration: enable alerts for existing per-bot docs that
        # were tracked before auto-enable existed (alert_enabled field absent).
        try:
            mig = await db.group_activity.update_many(
                {"sender_id": {"$ne": 0}, "alert_enabled": {"$exists": False}},
                {"$set": {"alert_enabled": True}},
            )
            if mig.modified_count:
                print(f"[MIGRATE] Enabled alerts for {mig.modified_count} existing forwarder bot(s).")
        except Exception as _me:
            print(f"[MIGRATE] alert auto-enable warning: {_me}")
        print("DB indexes created.")
    except Exception as e:
        print(f"Index creation warning (likely IP not whitelisted in Atlas): {e}")

    await _seed_default_services()


def get_db():
    return db


# ─────────────────────────────────────────────────────────────────────
# 📱 SMS cache (cross-process): userbot writes parsed credit SMS here,
# main bot reads during deposit verification. TTL index auto-prunes
# entries older than 10 min (see init_db).
# ─────────────────────────────────────────────────────────────────────
async def sms_cache_set(utr: str, amount: float):
    utr = (utr or "").strip()
    if not utr:
        return
    try:
        await db.sms_cache.update_one(
            {"utr": utr},
            {"$set": {"utr": utr, "amount": float(amount),
                      "ts": datetime.datetime.utcnow()}},
            upsert=True,
        )
    except Exception as e:
        print(f"[sms_cache_set] warning: {e}")


async def sms_cache_get(utr: str):
    utr = (utr or "").strip()
    if not utr:
        return None
    try:
        doc = await db.sms_cache.find_one({"utr": utr})
        if not doc:
            return None
        # Manual TTL guard in case the Mongo TTL sweeper hasn't run yet
        ts = doc.get("ts")
        if isinstance(ts, datetime.datetime):
            age = (datetime.datetime.utcnow() - ts).total_seconds()
            if age > 600:
                return None
        return {"amount": float(doc.get("amount", 0)), "ts": ts}
    except Exception as e:
        print(f"[sms_cache_get] warning: {e}")
        return None


async def get_user(user_id: int):
    return await db.users.find_one({"user_id": user_id})


async def create_user(user_id: int, username: str, first_name: str, referrer_id: int = None):
    user = {
        "user_id": user_id,
        "username": username,
        "first_name": first_name,
        "balance": 0.0,
        "total_deposit": 0.0,
        "total_spent": 0.0,
        "referral_earning": 0.0,
        "referrer_id": referrer_id,
        "total_referrals": 0,
        "banned": False,
        "join_date": datetime.datetime.utcnow(),
        "active_session": None,
    }
    await db.users.insert_one(user)
    if referrer_id:
        await db.users.update_one({"user_id": referrer_id}, {"$inc": {"total_referrals": 1}})
    return user


async def update_user_balance(user_id: int, amount: float):
    await db.users.update_one({"user_id": user_id}, {"$inc": {"balance": amount}})


async def deduct_balance(user_id: int, amount: float):
    await db.users.update_one({"user_id": user_id}, {"$inc": {"balance": -amount, "total_spent": amount}})


async def get_all_users():
    return await db.users.find({}).to_list(None)


async def get_stock(service: str = None):
    query = {"status": "available"}
    if service:
        query["service"] = service
    return await db.stock.find(query).to_list(None)


async def get_stock_summary() -> dict:
    """Returns {service_name: available_count} for all services. Cached for 8s."""
    now = _time.monotonic()
    if _cache_stock["v"] == _cache_version["stock"] and (now - _cache_stock["ts"]) < _STOCK_CACHE_TTL:
        return _cache_stock["data"]
    pipeline = [
        {"$match": {"status": "available"}},
        {"$group": {"_id": "$service", "count": {"$sum": 1}}}
    ]
    result = await db.stock.aggregate(pipeline).to_list(None)
    data = {r["_id"] or "Unknown": r["count"] for r in result}
    _cache_stock["v"] = _cache_version["stock"]
    _cache_stock["ts"] = now
    _cache_stock["data"] = data
    return data


async def add_stock(number: str, device_id: str, service: str = "Myntra"):
    # Normalize device_id to lowercase — group messages typically lowercase hex,
    # so this guarantees consistent matching with cache + session lookups.
    norm_did = (device_id or "").strip().lower()
    doc = {
        "number": number,
        "device_id": norm_did,
        "service": service,
        "status": "available",
        "added_at": datetime.datetime.utcnow(),
    }
    await db.stock.insert_one(doc)
    _cache_bump("stock")


async def get_available_number(service: str = None):
    query = {"status": "available"}
    if service:
        query["service"] = service
    return await db.stock.find_one(query, sort=[("added_at", 1)])


async def assign_number(number: str):
    await db.stock.update_one({"number": number}, {"$set": {"status": "in_use"}})


async def atomic_get_and_assign_number(service: str = None, exclude_device_ids: list = None):
    """Atomically find an available number AND mark it in_use in one DB operation.
    Skips numbers whose device_id is in exclude_device_ids.
    Returns the document if found, else None. Prevents race conditions."""
    import datetime
    query = {"status": "available"}
    if service:
        query["service"] = service
    if exclude_device_ids:
        query["device_id"] = {"$nin": list(exclude_device_ids)}
    doc = await db.stock.find_one_and_update(
        query,
        {"$set": {"status": "in_use", "assigned_at": datetime.datetime.utcnow()}},
        sort=[("added_at", 1)],
        return_document=True,
    )
    return doc


async def get_recent_devices_cache_size() -> int:
    """Returns admin-configured cache size (default 10, clamped 1..200)."""
    s = await get_settings()
    val = s.get("recent_devices_cache_size", DEFAULT_RECENT_DEVICES_CACHE_SIZE)
    try:
        n = int(val)
    except Exception:
        n = DEFAULT_RECENT_DEVICES_CACHE_SIZE
    if n < MIN_RECENT_DEVICES_CACHE_SIZE:
        n = MIN_RECENT_DEVICES_CACHE_SIZE
    if n > MAX_RECENT_DEVICES_CACHE_SIZE:
        n = MAX_RECENT_DEVICES_CACHE_SIZE
    return n


async def set_recent_devices_cache_size(size: int):
    """Set the cache size and immediately trim existing cache to fit."""
    n = int(size)
    if n < MIN_RECENT_DEVICES_CACHE_SIZE:
        n = MIN_RECENT_DEVICES_CACHE_SIZE
    if n > MAX_RECENT_DEVICES_CACHE_SIZE:
        n = MAX_RECENT_DEVICES_CACHE_SIZE
    await update_settings("recent_devices_cache_size", n)
    # Trim existing cache to new size right away.
    current = await get_recent_device_ids_db()
    if current and len(current) > n:
        norm = [str(x).strip().lower() for x in current if x]
        await db.settings.update_one(
            {"_id": "recent_device_ids"},
            {"$set": {"ids": norm[:n]}},
            upsert=True,
        )
    return n


async def set_recent_device_ids(device_ids: list, max_size: int = None):
    """Persist recent device_ids cache (newest first). Normalizes to lowercase + dedupe.
    If max_size omitted, uses admin-configured size."""
    if max_size is None:
        max_size = await get_recent_devices_cache_size()
    seen = set()
    normalized = []
    for d in device_ids or []:
        if not d:
            continue
        nd = str(d).strip().lower()
        if nd and nd not in seen:
            seen.add(nd)
            normalized.append(nd)
    await db.settings.update_one(
        {"_id": "recent_device_ids"},
        {"$set": {"ids": normalized[:max_size]}},
        upsert=True,
    )


async def add_recent_device_id(device_id: str):
    """Prepend a single device_id to the recent cache (newest first, dedupe, trim).
    All-in-one helper called from userbot — uses admin-configured cache size."""
    if not device_id:
        return
    nd = str(device_id).strip().lower()
    if not nd:
        return
    max_size = await get_recent_devices_cache_size()
    current = await get_recent_device_ids_db()
    norm_current = [str(x).strip().lower() for x in (current or []) if x]
    new_list = [nd] + [x for x in norm_current if x != nd]
    await db.settings.update_one(
        {"_id": "recent_device_ids"},
        {"$set": {"ids": new_list[:max_size]}},
        upsert=True,
    )


async def get_recent_device_ids_db() -> list:
    """Read recent device_ids cache from DB."""
    doc = await db.settings.find_one({"_id": "recent_device_ids"})
    if doc and isinstance(doc.get("ids"), list):
        return doc["ids"]
    return []


async def atomic_assign_by_device_priority(service: str, device_ids: list, exclude_device_ids: list = None):
    """Try to assign an available number whose device_id matches one of the
    given device_ids (newest-first priority). Atomic single query.
    Skips device_ids in exclude_device_ids (used to avoid re-assigning a device
    the same user just cancelled).
    Case-INSENSITIVE match — handles legacy stock entries with mixed case.
    Returns the doc if matched, else None (caller should fallback).
    """
    if not device_ids:
        return None
    excluded = {(e or "").strip().lower() for e in (exclude_device_ids or [])}
    for did in device_ids:
        if not did:
            continue
        nd = str(did).strip().lower()
        if not nd or nd in excluded:
            continue
        # Case-insensitive exact match; works whether stock device_id is lower or mixed case.
        pattern = re.compile(f"^{re.escape(nd)}$", re.IGNORECASE)
        doc = await db.stock.find_one_and_update(
            {"status": "available", "service": service, "device_id": pattern},
            {"$set": {"status": "in_use", "assigned_at": datetime.datetime.utcnow()}},
            sort=[("added_at", 1)],
            return_document=True,
        )
        if doc:
            return doc
    return None


async def add_user_blacklisted_device(user_id: int, device_id: str):
    """Append a device_id to this user's blacklist (skipped on next buys until
    a successful OTP delivery clears the list)."""
    if not device_id:
        return
    await db.users.update_one(
        {"user_id": user_id},
        {"$addToSet": {"blacklisted_device_ids": device_id}}
    )


async def get_user_blacklisted_devices(user_id: int) -> list:
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        return []
    return user.get("blacklisted_device_ids", []) or []


async def clear_user_blacklisted_devices(user_id: int):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"blacklisted_device_ids": []}}
    )


async def return_number_to_stock(number: str, service: str = None):
    """Return the IN_USE doc for this number back to available.
    Filters by status=in_use to avoid touching duplicate docs (same number under
    multiple services). Optionally filters by service for extra precision."""
    query = {"number": number, "status": "in_use"}
    if service:
        query["service"] = service
    result = await db.stock.update_one(
        query,
        {"$set": {"status": "available", "added_at": datetime.datetime.utcnow()}}
    )
    _cache_bump("stock")
    if result.matched_count == 0:
        import logging
        logging.getLogger(__name__).warning(f"return_number_to_stock: no in_use doc for number='{number}' service='{service}'")


async def delete_number_from_stock(number: str, service: str = None):
    """Delete the IN_USE doc for this number. service filter avoids deleting
    the wrong duplicate when same number exists under multiple services."""
    query = {"number": number, "status": "in_use"}
    if service:
        query["service"] = service
    result = await db.stock.delete_one(query)
    _cache_bump("stock")
    if result.deleted_count == 0:
        import logging
        logging.getLogger(__name__).warning(f"delete_number_from_stock: no in_use doc for number='{number}' service='{service}' — falling back to plain match")
        await db.stock.delete_one({"number": number, "service": service} if service else {"number": number})


async def remove_stock_item(number: str):
    await db.stock.delete_one({"number": number})


async def clear_all_stock():
    result = await db.stock.delete_many({"status": "available"})
    return result.deleted_count


async def clear_service_stock(service: str):
    """Delete all available stock for a specific service."""
    result = await db.stock.delete_many({"status": "available", "service": service})
    return result.deleted_count


async def reset_user_balance(user_id: int):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"balance": 0.0, "total_deposit": 0.0, "referral_earning": 0.0}}
    )


async def create_session(user_id: int, device_id: str, number: str, service: str = "Myntra", price: float = None):
    """Create session. Returns None (and rolls back number) if session already exists — prevents 2 numbers."""
    import datetime
    # Guard: if user already has a waiting session, do NOT create another
    existing = await db.sessions.find_one({"user_id": user_id, "status": "waiting"})
    if existing:
        # Roll back: return the number to stock so it's not stuck as in_use
        if number:
            await db.stock.update_one(
                {"number": number, "status": "in_use"},
                {"$set": {"status": "available", "added_at": datetime.datetime.utcnow()}}
            )
            _cache_bump("stock")
        import logging
        logging.getLogger(__name__).warning(f"create_session BLOCKED: user {user_id} already has waiting session — number {number} returned to stock")
        return None
    otp_total = await get_service_otp_count(service)
    session = {
        "user_id": user_id,
        "device_id": device_id,
        "number": number,
        "service": service,
        "status": "waiting",
        "start_time": datetime.datetime.utcnow(),
        "mode": "auto",
        "otp_count_total": otp_total,
        "otp_count_received": 0,
        "delivered_otps": [],
    }
    if price is not None:
        session["price"] = float(price)
    result = await db.sessions.insert_one(session)
    await db.users.update_one({"user_id": user_id}, {"$set": {"active_session": str(result.inserted_id)}})
    return session


async def create_manual_session(user_id: int, service: str = "Myntra", price: float = None):
    import datetime
    session = {
        "user_id": user_id,
        "device_id": None,
        "number": None,
        "service": service,
        "status": "waiting",
        "start_time": datetime.datetime.utcnow(),
        "mode": "manual",
    }
    if price is not None:
        session["price"] = float(price)
    result = await db.sessions.insert_one(session)
    await db.users.update_one({"user_id": user_id}, {"$set": {"active_session": str(result.inserted_id)}})
    return session


async def get_session(user_id: int):
    return await db.sessions.find_one({"user_id": user_id, "status": "waiting"})


async def acquire_order_lock(user_id: int) -> bool:
    """Atomically set ordering=True only if not already set. Returns True if lock acquired."""
    result = await db.users.update_one(
        {"user_id": user_id, "ordering": {"$ne": True}},
        {"$set": {"ordering": True}}
    )
    return result.modified_count == 1


async def release_order_lock(user_id: int):
    """Release the ordering lock."""
    await db.users.update_one({"user_id": user_id}, {"$unset": {"ordering": ""}})


async def update_session_status(user_id: int, status: str) -> bool:
    result = await db.sessions.update_one({"user_id": user_id, "status": "waiting"}, {"$set": {"status": status}})
    if result.modified_count == 0:
        return False
    if status in ("delivered", "cancelled", "expired"):
        await db.users.update_one({"user_id": user_id}, {"$set": {"active_session": None}})
    return True


async def consume_otp_slot(user_id: int, otp_code: str = None) -> dict | None:
    """Atomically increment otp_count_received on the user's WAITING session,
    only if received < total AND otp_code not already delivered (prevents duplicates).
    Returns updated session doc, or None if no slot available / already delivered."""
    query = {
        "user_id": user_id,
        "status": "waiting",
        "$expr": {"$lt": [
            {"$ifNull": ["$otp_count_received", 0]},
            {"$ifNull": ["$otp_count_total", 1]},
        ]},
    }
    # If OTP code provided, reject if it was already delivered in this session
    if otp_code:
        query["delivered_otps"] = {"$not": {"$elemMatch": {"$eq": otp_code}}}

    update = {"$inc": {"otp_count_received": 1}}
    if otp_code:
        update["$addToSet"] = {"delivered_otps": otp_code}

    doc = await db.sessions.find_one_and_update(
        query,
        update,
        return_document=True,
    )
    return doc


async def finalize_session_delivered(user_id: int):
    """Mark the WAITING session as delivered (used when otp_count_total reached)."""
    await db.sessions.update_one(
        {"user_id": user_id, "status": "waiting"},
        {"$set": {"status": "delivered"}}
    )
    await db.users.update_one({"user_id": user_id}, {"$set": {"active_session": None}})


async def create_deposit(user_id: int, screenshot_file_id: str, amount=None):
    deposit = {
        "user_id": user_id,
        "screenshot_file_id": screenshot_file_id,
        "status": "pending",
        "amount": amount,
        "created_at": datetime.datetime.utcnow(),
    }
    result = await db.deposits.insert_one(deposit)
    return str(result.inserted_id)


async def get_deposit(deposit_id: str):
    from bson import ObjectId
    return await db.deposits.find_one({"_id": ObjectId(deposit_id)})


async def get_pending_deposits():
    return await db.deposits.find({"status": "pending"}).to_list(None)


async def approve_deposit(deposit_id: str, amount: float):
    from bson import ObjectId
    result = await db.deposits.find_one_and_update(
        {"_id": ObjectId(deposit_id), "status": "pending"},
        {"$set": {"status": "approved", "amount": amount}},
        return_document=True
    )
    if result:
        await db.users.update_one(
            {"user_id": result["user_id"]},
            {"$inc": {"balance": amount, "total_deposit": amount}}
        )
        return result
    return None


async def reject_deposit(deposit_id: str):
    from bson import ObjectId
    result = await db.deposits.find_one_and_update(
        {"_id": ObjectId(deposit_id), "status": "pending"},
        {"$set": {"status": "rejected"}},
        return_document=True
    )
    return result  # None if already approved/rejected


async def add_balance_manual(user_id: int, amount: float):
    await db.users.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount, "total_deposit": amount}}
    )


async def add_referral_bonus(referrer_id: int, amount: float):
    await db.users.update_one(
        {"user_id": referrer_id},
        {"$inc": {"balance": amount, "referral_earning": amount}}
    )


async def add_log(log_type: str, data: dict):
    data["type"] = log_type
    data["created_at"] = datetime.datetime.utcnow()
    await db.logs.insert_one(data)


async def get_logs(log_type: str, limit: int = 50):
    return await db.logs.find({"type": log_type}).sort("created_at", -1).limit(limit).to_list(None)


async def get_recent_used_utrs(limit: int = 50):
    """Last N UTRs that were auto-credited (newest first). Used in admin panel."""
    return await db.verified_utrs.find({}).sort("created_at", -1).limit(limit).to_list(None)


async def get_all_active_sessions():
    return await db.sessions.find({"status": "waiting"}).to_list(None)


async def save_pending_otp(text: str, otp_code: str):
    """Store an incoming OTP when no session is waiting yet (will auto-expire in 10 min)."""
    await db.pending_otps.delete_many({})
    await db.pending_otps.insert_one({
        "text": text,
        "otp_code": otp_code,
        "created_at": datetime.datetime.utcnow(),
    })


async def get_pending_otp():
    """Return the most recent pending OTP if any."""
    return await db.pending_otps.find_one(sort=[("created_at", -1)])


async def clear_pending_otp(otp_id):
    """Remove a pending OTP after it has been delivered."""
    from bson import ObjectId
    await db.pending_otps.delete_one({"_id": otp_id})


async def get_stats():
    total_users = await db.users.count_documents({})
    total_deposits = await db.deposits.count_documents({"status": "approved"})
    total_otp = await db.logs.count_documents({"type": "otp_delivered"})
    active_sessions = await db.sessions.count_documents({"status": "waiting"})
    return {
        "total_users": total_users,
        "total_deposits": total_deposits,
        "total_otp": total_otp,
        "active_sessions": active_sessions,
    }


async def get_settings():
    hit, cached = _cache_get(_cache_settings, "settings")
    if hit:
        return cached
    settings = await db.settings.find_one({"_id": "global"})
    if not settings:
        from config import DEFAULT_OTP_PRICE, DEFAULT_REFERRAL_PERCENT, DEFAULT_WAIT_TIME, DEFAULT_CANCEL_TIME
        settings = {
            "_id": "global",
            "otp_price": DEFAULT_OTP_PRICE,
            "referral_percent": DEFAULT_REFERRAL_PERCENT,
            "wait_time": DEFAULT_WAIT_TIME,
            "cancel_time": DEFAULT_CANCEL_TIME,
            "mode": "auto",
        }
        await db.settings.insert_one(settings)
    _cache_set(_cache_settings, "settings", settings)
    return settings


async def update_settings(key: str, value):
    await db.settings.update_one({"_id": "global"}, {"$set": {key: value}}, upsert=True)
    _cache_bump("settings")


async def get_mode():
    s = await get_settings()
    return s.get("mode", "auto")


async def set_mode(mode: str):
    await update_settings("mode", mode)


async def get_user_history(user_id: int):
    delivered = await db.logs.find({"type": "otp_delivered", "user_id": user_id}).sort("created_at", -1).limit(20).to_list(None)
    cancelled = await db.logs.find({"type": "cancelled", "user_id": user_id}).sort("created_at", -1).limit(20).to_list(None)
    return delivered, cancelled


async def get_user_history_filtered(user_id: int, days: int = None, service: str = None, limit: int = 30):
    """Filter delivered + cancelled logs by date range and/or service."""
    import datetime
    base = {"user_id": user_id}
    if days:
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days)
        base["created_at"] = {"$gte": cutoff}
    if service:
        base["service"] = service
    delivered_q = dict(base, type="otp_delivered")
    cancelled_q = dict(base, type="cancelled")
    delivered = await db.logs.find(delivered_q).sort("created_at", -1).limit(limit).to_list(None)
    cancelled = await db.logs.find(cancelled_q).sort("created_at", -1).limit(limit).to_list(None)
    return delivered, cancelled


async def get_user_top_services(user_id: int, limit: int = 3) -> list:
    """Return list of service names ordered by user's delivered-OTP count desc."""
    pipeline = [
        {"$match": {"type": "otp_delivered", "user_id": user_id, "service": {"$ne": None}}},
        {"$group": {"_id": "$service", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": limit},
    ]
    rows = await db.logs.aggregate(pipeline).to_list(None)
    return [r["_id"] for r in rows if r.get("_id")]


async def user_has_first_buy_used(user_id: int) -> bool:
    user = await db.users.find_one({"user_id": user_id})
    return bool(user and user.get("first_buy_used"))


async def mark_first_buy_used(user_id: int):
    await db.users.update_one({"user_id": user_id}, {"$set": {"first_buy_used": True}})


async def ban_user(user_id: int):
    await db.users.update_one({"user_id": user_id}, {"$set": {"banned": True}})


async def unban_user(user_id: int):
    await db.users.update_one({"user_id": user_id}, {"$set": {"banned": False}})


async def get_session_by_device(device_id: str, service: str = None):
    """Find a waiting session by device_id (case-insensitive)."""
    if not device_id:
        return None
    nd = str(device_id).strip()
    pattern = re.compile(f"^{re.escape(nd)}$", re.IGNORECASE)
    query = {"device_id": pattern, "status": "waiting"}
    if service:
        query["service"] = service
    return await db.sessions.find_one(query)


async def update_session_number(user_id: int, number: str, device_id: str = None):
    update = {"number": number}
    if device_id:
        update["device_id"] = device_id
    await db.sessions.update_one({"user_id": user_id, "status": "waiting"}, {"$set": update})


async def get_otp_group_id() -> str | None:
    settings = await get_settings()
    return settings.get("otp_group_id", None)


async def set_otp_group_id(group_id: str):
    await update_settings("otp_group_id", group_id)


async def get_top_spenders(limit: int = 10):
    return await db.users.find(
        {"total_spent": {"$gt": 0}},
        sort=[("total_spent", -1)]
    ).limit(limit).to_list(None)


async def get_daily_revenue():
    today = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    logs = await db.logs.find({
        "type": "otp_delivered",
        "created_at": {"$gte": today}
    }).to_list(None)
    otp_count = len(logs)

    dep_logs = await db.logs.find({
        "type": "deposit_approved",
        "created_at": {"$gte": today}
    }).to_list(None)
    deposit_total = sum(d.get("amount", 0) for d in dep_logs)

    new_users = await db.users.count_documents({"join_date": {"$gte": today}})
    active_sessions = await db.sessions.count_documents({"status": "waiting"})

    return {
        "otp_count": otp_count,
        "deposit_total": deposit_total,
        "new_users": new_users,
        "active_sessions": active_sessions,
    }


async def reset_all_stats():
    await db.logs.delete_many({})
    await db.sessions.delete_many({"status": {"$in": ["delivered", "cancelled", "expired"]}})
    await db.users.update_many({}, {"$set": {
        "total_deposit": 0.0,
        "total_spent": 0.0,
        "referral_earning": 0.0,
        "total_referrals": 0,
    }})
    await db.deposits.delete_many({"status": {"$in": ["approved", "rejected"]}})


async def _seed_default_services():
    await db.services.update_one(
        {"name": "Myntra"},
        {"$setOnInsert": {"name": "Myntra", "keywords": ["myntra", "myntra.com"], "active": True, "price": None}},
        upsert=True
    )


async def get_services():
    hit, cached = _cache_get(_cache_services, "services")
    if hit:
        return cached
    data = await db.services.find({}).to_list(None)
    _cache_set(_cache_services, "services", data)
    return data


async def get_active_service_keywords() -> list[str]:
    services = await db.services.find({"active": True}).to_list(None)
    keywords = []
    for s in services:
        keywords.extend(s.get("keywords", []))
    return keywords


async def add_service(name: str, keywords: list, price: float = None, otp_digits: list = None) -> bool:
    try:
        if otp_digits is None:
            otp_digits = [4, 5, 6]
        await db.services.insert_one({
            "name": name,
            "keywords": keywords,
            "active": True,
            "price": price,
            "otp_digits": otp_digits,
        })
        _cache_bump("services")
        return True
    except Exception:
        return False


async def get_service_otp_digits(service_name: str) -> list:
    """Return allowed OTP digit lengths for a service. Default [4, 5, 6]."""
    svc = await db.services.find_one({"name": service_name})
    if svc and svc.get("otp_digits"):
        return [int(d) for d in svc["otp_digits"]]
    return [4, 5, 6]


async def update_service_otp_digits(service_id: str, digits: list) -> bool:
    """Set allowed OTP digit lengths for a service."""
    from bson import ObjectId
    try:
        await db.services.update_one(
            {"_id": ObjectId(service_id)},
            {"$set": {"otp_digits": sorted(set(int(d) for d in digits))}}
        )
        _cache_bump("services")
        return True
    except Exception:
        return False


async def update_service_otp_digits_by_name(service_name: str, digits: list) -> bool:
    """Set allowed OTP digit lengths for a service using its name."""
    try:
        await db.services.update_one(
            {"name": service_name},
            {"$set": {"otp_digits": sorted(set(int(d) for d in digits))}}
        )
        _cache_bump("services")
        return True
    except Exception:
        return False


async def add_service_keyword(service_id: str, keyword: str) -> bool:
    """Add a keyword to a service (case-insensitive, trimmed)."""
    from bson import ObjectId
    kw = keyword.strip().lower()
    if not kw:
        return False
    try:
        await db.services.update_one(
            {"_id": ObjectId(service_id)},
            {"$addToSet": {"keywords": kw}}
        )
        _cache_bump("services")
        return True
    except Exception:
        return False


async def remove_service_keyword(service_id: str, keyword: str) -> bool:
    """Remove a keyword from a service."""
    from bson import ObjectId
    kw = keyword.strip()
    if not kw:
        return False
    try:
        await db.services.update_one(
            {"_id": ObjectId(service_id)},
            {"$pull": {"keywords": {"$regex": f"^{re.escape(kw)}$", "$options": "i"}}}
        )
        _cache_bump("services")
        return True
    except Exception:
        return False


async def record_otp_digit_usage(service_name: str, digit_len: int):
    """Record that an OTP of digit_len digits was observed for this service."""
    try:
        await db.otp_digit_stats.update_one(
            {"service": service_name, "digit_len": digit_len},
            {
                "$inc": {"count": 1},
                "$set": {"last_seen": datetime.datetime.utcnow()},
            },
            upsert=True
        )
    except Exception:
        pass


async def get_otp_digit_stats(service_name: str) -> list:
    """Return list of {digit_len, count, last_seen} for a service, sorted by count desc."""
    try:
        data = await db.otp_digit_stats.find({"service": service_name}).to_list(None)
        return sorted(data, key=lambda x: x.get("count", 0), reverse=True)
    except Exception:
        return []


async def get_service_price(service_name: str, fallback: float = 5.0) -> float:
    """Return per-service price if set, else fallback to global price.
    Auto-applies active flash-sale discount if applicable."""
    svc = await db.services.find_one({"name": service_name})
    if svc and svc.get("price") is not None:
        base = float(svc["price"])
    else:
        base = float(fallback)
    discount = await get_flash_discount_for_service(service_name)
    if discount > 0:
        base = round(base * (1.0 - discount / 100.0), 2)
        if base < 0.01:
            base = 0.01
    return base


# ─────────────────────────────────────────────────────────────
# 🔥 FLASH SALE
# ─────────────────────────────────────────────────────────────

async def get_flash_sale():
    """Return active flash sale doc, or None if expired/inactive.
    Auto-deactivates expired sales. Cached for _CACHE_TTL seconds."""
    hit, cached = _cache_get(_cache_flash, "flash")
    if hit:
        # Re-validate expiry without a DB hit
        if cached is None:
            return None
        ends_at = cached.get("ends_at")
        if not ends_at or ends_at > datetime.datetime.utcnow():
            return cached
        # Expired — fall through to refresh + deactivate
    doc = await db.settings.find_one({"_id": "flash_sale"})
    if not doc or not doc.get("active"):
        _cache_set(_cache_flash, "flash", None)
        return None
    ends_at = doc.get("ends_at")
    if ends_at and ends_at <= datetime.datetime.utcnow():
        await db.settings.update_one(
            {"_id": "flash_sale"},
            {"$set": {"active": False}}
        )
        _cache_set(_cache_flash, "flash", None)
        return None
    _cache_set(_cache_flash, "flash", doc)
    return doc


async def set_flash_sale(discount_pct: float, service_names: list, all_services: bool, duration_min: int):
    now = datetime.datetime.utcnow()
    ends_at = now + datetime.timedelta(minutes=int(duration_min))
    await db.settings.update_one(
        {"_id": "flash_sale"},
        {"$set": {
            "active": True,
            "discount_percent": float(discount_pct),
            "service_names": list(service_names),
            "all_services": bool(all_services),
            "starts_at": now,
            "ends_at": ends_at,
        }},
        upsert=True
    )

    _cache_bump("flash")

async def stop_flash_sale():
    await db.settings.update_one(
        {"_id": "flash_sale"},
        {"$set": {"active": False}},
        upsert=True
    )


# ─────────────────────────────────────────────────────────────
# 💎 WALLET TOP-UP BONUS (slab-based)
# ─────────────────────────────────────────────────────────────

async def get_topup_slabs() -> list:
    """Return list of slabs sorted by min ascending.
    Each slab: {min: float, max: float, bonus_pct: float}"""
    doc = await db.settings.find_one({"_id": "topup_bonus"})
    if not doc:
        return []
    slabs = doc.get("slabs") or []
    return sorted(slabs, key=lambda s: float(s.get("min", 0)))


async def add_topup_slab(min_amt: float, max_amt: float, bonus_pct: float):
    slab = {"min": float(min_amt), "max": float(max_amt), "bonus_pct": float(bonus_pct)}
    await db.settings.update_one(
        {"_id": "topup_bonus"},
        {"$push": {"slabs": slab}},
        upsert=True
    )


async def delete_topup_slab(index: int):
    """Delete slab at given index (0-based, sorted by min asc)."""
    slabs = await get_topup_slabs()
    if index < 0 or index >= len(slabs):
        return False
    new_slabs = [s for i, s in enumerate(slabs) if i != index]
    await db.settings.update_one(
        {"_id": "topup_bonus"},
        {"$set": {"slabs": new_slabs}},
        upsert=True
    )
    return True


async def clear_topup_slabs():
    await db.settings.update_one(
        {"_id": "topup_bonus"},
        {"$set": {"slabs": []}},
        upsert=True
    )


async def compute_topup_bonus(amount: float) -> tuple:
    """Returns (bonus_amount, bonus_pct) for a given deposit amount.
    Picks the highest-min slab where min <= amount <= max."""
    slabs = await get_topup_slabs()
    matched = None
    for s in slabs:
        mn = float(s.get("min", 0))
        mx = float(s.get("max", 0))
        if amount >= mn and amount <= mx:
            matched = s  # keep iterating; sorted asc so last match = highest band
    if not matched:
        return (0.0, 0.0)
    pct = float(matched.get("bonus_pct", 0))
    return (round(amount * pct / 100.0, 2), pct)


async def credit_topup_bonus(user_id: int, bonus: float):
    """Credit bonus to balance only — does NOT affect total_deposit (so stats stay clean)."""
    if bonus <= 0:
        return
    await db.users.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": float(bonus), "total_topup_bonus": float(bonus)}}
    )


async def get_flash_discount_for_service(service_name: str) -> float:
    """Returns discount percentage (0–100) for a service if a flash sale covers it."""
    fs = await get_flash_sale()
    if not fs:
        return 0.0
    if fs.get("all_services"):
        return float(fs.get("discount_percent", 0))
    if service_name in (fs.get("service_names") or []):
        return float(fs.get("discount_percent", 0))
    return 0.0


async def update_service_price(service_id: str, price: float):
    from bson import ObjectId
    await db.services.update_one({"_id": ObjectId(service_id)}, {"$set": {"price": price}})
    _cache_bump("services")


async def update_service_otp_count(service_id: str, count: int):
    from bson import ObjectId
    await db.services.update_one({"_id": ObjectId(service_id)}, {"$set": {"otp_count": int(count)}})
    _cache_bump("services")


async def get_service_otp_count(service_name: str) -> int:
    """Returns configured otp_count for service (default 1)."""
    svc = await db.services.find_one({"name": service_name})
    if not svc:
        return 1
    val = svc.get("otp_count", 1)
    try:
        v = int(val)
        return v if v >= 1 else 1
    except Exception:
        return 1


async def toggle_service(service_id: str) -> bool | None:
    from bson import ObjectId
    doc = await db.services.find_one({"_id": ObjectId(service_id)})
    if not doc:
        return None
    new_state = not doc.get("active", True)
    await db.services.update_one({"_id": ObjectId(service_id)}, {"$set": {"active": new_state}})
    return new_state


async def delete_service(service_id: str):
    from bson import ObjectId
    await db.services.delete_one({"_id": ObjectId(service_id)})


async def create_refund_request(user_id: int, video_file_id: str, log_id: str, order_info: dict | None = None):
    doc = {
        "user_id": user_id,
        "video_file_id": video_file_id,
        "log_id": log_id,
        "status": "pending",
        "order_info": order_info or {},
        "amount": None,
        "reason": None,
        "created_at": datetime.datetime.utcnow(),
    }
    result = await db.refunds.insert_one(doc)
    return str(result.inserted_id)


async def get_refundable_deliveries(user_id: int, limit: int = 10):
    """Returns delivered logs (with number) that have no pending/approved refund yet."""
    logs = await db.logs.find(
        {"type": "otp_delivered", "user_id": user_id, "number": {"$ne": None, "$exists": True}}
    ).sort("created_at", -1).limit(limit * 2).to_list(None)

    if not logs:
        return []

    log_ids = [str(l["_id"]) for l in logs]
    blocked = await db.refunds.find(
        {"log_id": {"$in": log_ids}, "status": {"$in": ["pending", "approved"]}}
    ).to_list(None)
    blocked_ids = {r["log_id"] for r in blocked}

    refundable = [l for l in logs if str(l["_id"]) not in blocked_ids]
    return refundable[:limit]


async def get_log_by_id(log_id: str):
    from bson import ObjectId
    try:
        return await db.logs.find_one({"_id": ObjectId(log_id)})
    except Exception:
        return None


async def is_log_refunded(log_id: str) -> bool:
    doc = await db.refunds.find_one(
        {"log_id": log_id, "status": {"$in": ["pending", "approved"]}}
    )
    return doc is not None


async def get_refund_request(refund_id: str):
    from bson import ObjectId
    try:
        return await db.refunds.find_one({"_id": ObjectId(refund_id)})
    except Exception:
        return None


async def approve_refund_request(refund_id: str, amount: float):
    from bson import ObjectId
    doc = await db.refunds.find_one_and_update(
        {"_id": ObjectId(refund_id), "status": "pending"},
        {"$set": {"status": "approved", "amount": float(amount),
                  "processed_at": datetime.datetime.utcnow()}},
        return_document=True
    )
    if doc:
        await db.users.update_one(
            {"user_id": doc["user_id"]},
            {"$inc": {"balance": float(amount)}}
        )
    return doc


async def reject_refund_request(refund_id: str, reason: str):
    from bson import ObjectId
    return await db.refunds.find_one_and_update(
        {"_id": ObjectId(refund_id), "status": "pending"},
        {"$set": {"status": "rejected", "reason": reason,
                  "processed_at": datetime.datetime.utcnow()}},
        return_document=True
    )


async def get_last_delivered_log(user_id: int):
    return await db.logs.find_one(
        {"type": "otp_delivered", "user_id": user_id},
        sort=[("created_at", -1)]
    )


async def has_pending_refund(user_id: int) -> bool:
    doc = await db.refunds.find_one({"user_id": user_id, "status": "pending"})
    return doc is not None


# ───────────────────────── PROMO CODES ─────────────────────────

async def create_promo_code(code: str, amount: float, max_claims: int, created_by: int):
    code = code.upper().strip()
    existing = await db.promo_codes.find_one({"code": code})
    if existing:
        return None
    doc = {
        "code": code,
        "amount": float(amount),
        "max_claims": int(max_claims),
        "claimed_by": [],
        "created_by": int(created_by),
        "created_at": datetime.datetime.utcnow(),
        "active": True,
    }
    res = await db.promo_codes.insert_one(doc)
    doc["_id"] = res.inserted_id
    return doc


async def get_promo_code(code: str):
    return await db.promo_codes.find_one({"code": code.upper().strip()})


async def list_promo_codes():
    return await db.promo_codes.find({}, sort=[("created_at", -1)]).to_list(None)


async def delete_promo_code(code: str):
    await db.promo_codes.delete_one({"code": code.upper().strip()})


async def toggle_promo_code(code: str):
    code = code.upper().strip()
    promo = await db.promo_codes.find_one({"code": code})
    if not promo:
        return None
    new_active = not promo.get("active", True)
    await db.promo_codes.update_one({"code": code}, {"$set": {"active": new_active}})
    return new_active


async def get_maintenance():
    s = await get_settings()
    return {
        "enabled": s.get("maintenance_mode", False),
        "message": s.get("maintenance_message") or (
            "🛠 *Bot Under Maintenance*\n\n"
            "Hum thodi der mein wapas aayenge. Aapka balance aur order safe hai.\n\n"
            "Thanks for your patience! 🙏"
        ),
    }


async def set_maintenance(enabled: bool, message: str = None):
    await update_settings("maintenance_mode", bool(enabled))
    if message is not None:
        await update_settings("maintenance_message", message)


async def record_group_activity(group_id: int, sender_id: int, sender_name: str):
    """Track every msg in OTP group: 1 group-level doc (sender_id=0) + 1 per-bot doc."""
    now = datetime.datetime.utcnow()
    await db.group_activity.update_one(
        {"group_id": int(group_id), "sender_id": 0},
        {
            "$set": {"last_message_at": now, "last_alerted_at": None, "sender_name": "GROUP"},
            "$inc": {"msg_count": 1},
            "$setOnInsert": {"group_id": int(group_id), "sender_id": 0, "first_seen_at": now},
        },
        upsert=True,
    )
    if sender_id and int(sender_id) != 0:
        await db.group_activity.update_one(
            {"group_id": int(group_id), "sender_id": int(sender_id)},
            {
                "$set": {
                    "last_message_at": now,
                    "last_alerted_at": None,
                    "sender_name": sender_name or "Unknown",
                },
                "$inc": {"msg_count": 1},
                # 🔔 Auto-enable alerts for new bots — admin can opt-out per-bot
                # from Settings → Per-Bot Alert Toggle. This way silence never
                # goes unnoticed by default.
                "$setOnInsert": {
                    "group_id": int(group_id),
                    "sender_id": int(sender_id),
                    "first_seen_at": now,
                    "alert_enabled": True,
                },
            },
            upsert=True,
        )


async def get_silent_groups(threshold_min: int, reminder_min: int):
    """Group-level docs (sender_id=0) silent > threshold AND not alerted recently."""
    now = datetime.datetime.utcnow()
    threshold = now - datetime.timedelta(minutes=threshold_min)
    reminder_cutoff = now - datetime.timedelta(minutes=reminder_min)
    return await db.group_activity.find({
        "sender_id": 0,
        "last_message_at": {"$lt": threshold},
        "$or": [
            {"last_alerted_at": None},
            {"last_alerted_at": {"$lt": reminder_cutoff}},
        ],
    }).to_list(None)


async def get_silent_bots(threshold_min: int, recent_window_min: int, reminder_min: int):
    """Per-sender docs silent > threshold. Reminders fire forever (no upper window cap)
    so the admin keeps getting pinged every reminder_min until the bot is back OR
    alerts are disabled for that bot via the Per-Bot Alert Toggle.

    recent_window_min is kept in the signature for back-compat but is no longer used
    as an upper bound — that was masking long-dead bots from alerts."""
    now = datetime.datetime.utcnow()
    threshold = now - datetime.timedelta(minutes=threshold_min)
    reminder_cutoff = now - datetime.timedelta(minutes=reminder_min)
    return await db.group_activity.find({
        "sender_id": {"$ne": 0},
        "alert_enabled": True,
        "last_message_at": {"$lt": threshold},
        "$or": [
            {"last_alerted_at": None},
            {"last_alerted_at": {"$lt": reminder_cutoff}},
        ],
    }).to_list(None)


async def get_tracked_bots(group_id: int = None):
    """Return all known bot/sender docs (sender_id != 0), optionally filtered by group."""
    q = {"sender_id": {"$ne": 0}}
    if group_id is not None:
        q["group_id"] = int(group_id)
    return await db.group_activity.find(q).sort("last_message_at", -1).to_list(None)


async def set_bot_alert_enabled(group_id: int, sender_id: int, enabled: bool):
    """Toggle alert_enabled for a specific bot in a specific group."""
    await db.group_activity.update_one(
        {"group_id": int(group_id), "sender_id": int(sender_id)},
        {"$set": {"alert_enabled": bool(enabled)}}
    )


async def set_all_bots_alert_enabled(group_id: int, enabled: bool):
    """Bulk toggle: enable/disable alerts for ALL bots in a group."""
    await db.group_activity.update_many(
        {"group_id": int(group_id), "sender_id": {"$ne": 0}},
        {"$set": {"alert_enabled": bool(enabled)}}
    )


async def mark_activity_alerted(group_id: int, sender_id: int):
    await db.group_activity.update_one(
        {"group_id": int(group_id), "sender_id": int(sender_id)},
        {"$set": {"last_alerted_at": datetime.datetime.utcnow()}},
    )


async def get_all_group_activity():
    """Return all tracked group activity docs (for /health command)."""
    return await db.group_activity.find({}, sort=[("last_message_at", -1)]).to_list(None)


async def claim_promo_code(code: str, user_id: int):
    code = code.upper().strip()
    promo = await db.promo_codes.find_one({"code": code})
    if not promo:
        return {"success": False, "message": "❌ Promo code invalid hai. Check karke dobara try kar."}
    if not promo.get("active", True):
        return {"success": False, "message": "❌ Yeh promo code abhi disabled hai."}
    if user_id in promo.get("claimed_by", []):
        return {"success": False, "message": "❌ Tu pehle hi yeh code claim kar chuka hai."}
    max_claims = int(promo.get("max_claims", 0) or 0)
    claimed_count = len(promo.get("claimed_by", []))
    if max_claims > 0 and claimed_count >= max_claims:
        return {"success": False, "message": "❌ Yeh code full ho chuka hai (claim limit reached)."}

    filter_q = {
        "code": code,
        "active": True,
        "claimed_by": {"$ne": user_id},
    }
    if max_claims > 0:
        filter_q["$expr"] = {"$lt": [{"$size": "$claimed_by"}, max_claims]}

    result = await db.promo_codes.update_one(filter_q, {"$push": {"claimed_by": user_id}})
    if result.modified_count == 0:
        return {"success": False, "message": "❌ Claim fail hua. Code abhi-abhi full ho gaya ya already claimed."}

    amount = float(promo["amount"])
    await db.users.update_one({"user_id": user_id}, {"$inc": {"balance": amount}})
    user = await db.users.find_one({"user_id": user_id})
    return {
        "success": True,
        "amount": amount,
        "balance": (user.get("balance", 0) if user else amount),
        "code": code,
    }


# ============================================================
# Gmail-based deposit auto-verification helpers
# ============================================================

async def is_utr_used(utr: str) -> bool:
    """Return True if this UTR was already credited to any user."""
    if not utr:
        return False
    doc = await db.verified_utrs.find_one({"utr": utr.strip()})
    return doc is not None


async def mark_utr_used(utr: str, user_id: int, amount: float, deposit_id: str = None):
    """Atomically claim a UTR. Returns True on success, False if duplicate."""
    try:
        await db.verified_utrs.insert_one({
            "utr": utr.strip(),
            "user_id": user_id,
            "amount": float(amount),
            "deposit_id": deposit_id,
            "created_at": datetime.datetime.utcnow(),
        })
        return True
    except Exception:
        return False


async def auto_approve_deposit_with_utr(user_id: int, amount: float, utr: str,
                                        gmail_subject: str = "") -> str | None:
    """Create an already-approved deposit, claim the UTR, credit the balance.

    Returns deposit_id on success, None if the UTR is already used or the
    insert race-loses to another concurrent attempt.
    """
    utr = (utr or "").strip()
    # 1. Try to claim the UTR first — duplicate insert -> bail.
    claimed = await mark_utr_used(utr, user_id, float(amount))
    if not claimed:
        return None
    # 2. Create the deposit row already in 'approved' state.
    dep = {
        "user_id": user_id,
        "screenshot_file_id": None,
        "status": "approved",
        "amount": float(amount),
        "utr": utr,
        "gmail_subject": gmail_subject[:140] if gmail_subject else "",
        "auto_verified": True,
        "created_at": datetime.datetime.utcnow(),
    }
    result = await db.deposits.insert_one(dep)
    deposit_id = str(result.inserted_id)
    # 3. Back-fill deposit_id on the UTR row.
    try:
        await db.verified_utrs.update_one(
            {"utr": utr},
            {"$set": {"deposit_id": deposit_id}}
        )
    except Exception:
        pass
    # 4. Credit user balance.
    await db.users.update_one(
        {"user_id": user_id},
        {"$inc": {"balance": float(amount), "total_deposit": float(amount)}}
    )
    return deposit_id


# ============================================================================
# Admin-configurable settings (UPI ID, Min Deposit) + Deposit Stats
# ============================================================================

async def get_upi_id() -> str:
    """Return UPI ID — DB setting first, env fallback."""
    s = await get_settings()
    val = (s.get("upi_id") or "").strip()
    if val:
        return val
    import os
    return (os.getenv("UPI_ID", "") or "").strip()


async def set_upi_id(value: str) -> None:
    await update_settings("upi_id", (value or "").strip())


async def get_min_deposit() -> float:
    """Minimum deposit amount allowed for users."""
    s = await get_settings()
    try:
        v = float(s.get("min_deposit", 10))
        return v if v > 0 else 10.0
    except Exception:
        return 10.0


async def set_min_deposit(value: float) -> None:
    await update_settings("min_deposit", float(value))


async def get_deposit_stats():
    """Comprehensive deposit stats for admin dashboard."""
    import datetime
    now = datetime.datetime.utcnow()
    today = now - datetime.timedelta(days=1)
    week  = now - datetime.timedelta(days=7)
    month = now - datetime.timedelta(days=30)

    async def _sum(match: dict) -> float:
        cur = db.deposits.aggregate([
            {"$match": match},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}}}
        ])
        async for d in cur:
            return float(d.get("total") or 0)
        return 0.0

    async def _count(match: dict) -> int:
        return await db.deposits.count_documents(match)

    approved_match = {"status": "approved"}
    pending_match  = {"status": "pending"}
    rejected_match = {"status": "rejected"}
    auto_match     = {"status": "approved", "auto_verified": True}
    manual_match   = {"status": "approved", "$or": [{"auto_verified": {"$exists": False}}, {"auto_verified": False}]}

    total_amount   = await _sum(approved_match)
    today_amount   = await _sum({**approved_match, "created_at": {"$gte": today}})
    week_amount    = await _sum({**approved_match, "created_at": {"$gte": week}})
    month_amount   = await _sum({**approved_match, "created_at": {"$gte": month}})

    approved_count = await _count(approved_match)
    pending_count  = await _count(pending_match)
    rejected_count = await _count(rejected_match)
    auto_count     = await _count(auto_match)
    manual_count   = await _count(manual_match)

    # Unique depositors
    unique_users = await db.deposits.distinct("user_id", approved_match)

    # Top 5 depositors
    top_cur = db.deposits.aggregate([
        {"$match": approved_match},
        {"$group": {"_id": "$user_id", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
        {"$limit": 5},
    ])
    top = []
    async for d in top_cur:
        top.append({"user_id": d["_id"], "amount": float(d.get("total") or 0), "count": int(d.get("count") or 0)})

    return {
        "total_amount":   total_amount,
        "today_amount":   today_amount,
        "week_amount":    week_amount,
        "month_amount":   month_amount,
        "approved_count": approved_count,
        "pending_count":  pending_count,
        "rejected_count": rejected_count,
        "auto_count":     auto_count,
        "manual_count":   manual_count,
        "unique_users":   len(unique_users),
        "top":            top,
    }


# ── Admin User Notes ──────────────────────────────────────────────────────────

async def add_user_note(user_id: int, admin_id: int, note_text: str):
    from datetime import datetime
    note = {
        "text": note_text,
        "admin_id": admin_id,
        "created_at": datetime.utcnow(),
    }
    await db.users.update_one(
        {"user_id": user_id},
        {"$push": {"admin_notes": note}}
    )


async def get_user_notes(user_id: int):
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        return []
    return user.get("admin_notes", [])


async def delete_user_note(user_id: int, note_idx: int) -> bool:
    user = await db.users.find_one({"user_id": user_id})
    if not user:
        return False
    notes = user.get("admin_notes", [])
    if note_idx < 0 or note_idx >= len(notes):
        return False
    notes.pop(note_idx)
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"admin_notes": notes}}
    )
    return True


# ── Recent OTP Sessions ───────────────────────────────────────────────────────

async def get_recent_otp_sessions(limit: int = 50):
    """Return last `limit` sessions (all statuses) sorted newest first."""
    return await db.sessions.find(
        {},
        sort=[("created_at", -1)]
    ).limit(limit).to_list(None)
