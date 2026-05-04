"""SMS-based deposit auto-verification (clean rewrite — Apr 2026).

Listens for forwarded Airtel Payments Bank credit SMS in a private Telegram
group (populated by an Android SMS forwarder bot), parses the amount and
Txn-ID/UTR, caches them for 10 min, and exposes unified_verify() so the
deposit handler can race against incoming SMS.

Required env vars (set on Railway):
    SMS_GROUP_ID         — Telegram group ID where forwarder posts SMS
                           (e.g. -1001234567890)
    SMS_SENDER_FILTER    — comma-separated sender substrings to accept
                           (default: "AD-AIRBNK-S")

Sample message (exact format we parse):
    From: AD-AIRBNK-S
    Time: 2026-04-26 21:06:48+0530

    Airtel Payments Bank a/c is credited with Rs.10.00. Txn ID: 611677659509. Call 180023400 for help
"""

import os
import re
import asyncio
import datetime
import logging

logger = logging.getLogger("sms_verifier")

CACHE_TTL_SECONDS = 10 * 60  # 10 minutes


# ---- Env config ----
def _parse_group_id() -> int:
    raw = (os.getenv("SMS_GROUP_ID") or "").strip()
    try:
        return int(raw) if raw else 0
    except ValueError:
        logger.warning(f"[SMS] invalid SMS_GROUP_ID env value: {raw!r}")
        return 0


SMS_GROUP_ID = _parse_group_id()
SMS_SENDER_FILTER = (os.getenv("SMS_SENDER_FILTER") or "AD-AIRBNK-S").strip()
SMS_FILTERS = [f.strip().upper() for f in SMS_SENDER_FILTER.split(",") if f.strip() and f.strip() != "*"]


# ---- Regex ----
# Matches "Rs.10.00", "Rs 10", "INR 10.00"
_AMOUNT_RE = re.compile(r"(?:Rs\.?|INR)\s*([0-9]+(?:\.[0-9]{1,2})?)", re.IGNORECASE)
# Matches "Txn ID: 611677659509", "UTR: ...", "Ref No 1234567890"
_UTR_RE = re.compile(
    r"(?:Txn\s*ID|UTR|RRN|Ref(?:erence)?\s*(?:No|ID|#)?)[:\s#-]*([0-9]{10,16})",
    re.IGNORECASE,
)
# Fallback: any standalone 10-16 digit number
_FALLBACK_DIGITS_RE = re.compile(r"\b([0-9]{10,16})\b")
# Credit / debit detection
_CREDIT_RE = re.compile(r"\bcredited\b", re.IGNORECASE)
_DEBIT_RE = re.compile(r"\b(debited|debit|withdrawn|spent|paid\s+to)\b", re.IGNORECASE)


class SmsVerifier:
    """In-memory cache of recently-seen credit SMS, keyed by UTR."""

    def __init__(self):
        # utr -> {"amount": float, "ts": datetime}
        self.cache: dict[str, dict] = {}
        self.total_seen = 0
        self.total_parsed = 0
        self.total_skipped = 0
        self.last_message_at: datetime.datetime | None = None
        self.last_credit_at: datetime.datetime | None = None

    def is_configured(self) -> bool:
        return SMS_GROUP_ID != 0

    def _prune(self):
        now = datetime.datetime.utcnow()
        cutoff = now - datetime.timedelta(seconds=CACHE_TTL_SECONDS)
        dead = [k for k, v in self.cache.items() if v["ts"] < cutoff]
        for k in dead:
            del self.cache[k]

    def _sender_ok(self, text: str) -> bool:
        """True if sender header contains any allowed filter, OR filters disabled."""
        if not SMS_FILTERS:
            return True
        head = text[:300].upper()
        return any(f in head for f in SMS_FILTERS)

    def add_from_message(self, text: str) -> dict:
        """Parse a forwarded SMS payload. Cache it if it's a valid credit.

        Returns dict with status: 'cached' | 'skipped' (+ reason).
        """
        self.total_seen += 1
        self.last_message_at = datetime.datetime.utcnow()

        if not text:
            self.total_skipped += 1
            return {"status": "skipped", "reason": "empty"}

        if not self._sender_ok(text):
            self.total_skipped += 1
            return {"status": "skipped", "reason": "sender_filter"}

        # Must be a CREDIT, not a debit
        if not _CREDIT_RE.search(text):
            self.total_skipped += 1
            return {"status": "skipped", "reason": "not_credit"}
        if _DEBIT_RE.search(text):
            self.total_skipped += 1
            return {"status": "skipped", "reason": "looks_like_debit"}

        m_amt = _AMOUNT_RE.search(text)
        if not m_amt:
            self.total_skipped += 1
            return {"status": "skipped", "reason": "no_amount"}
        try:
            amount = float(m_amt.group(1))
        except ValueError:
            self.total_skipped += 1
            return {"status": "skipped", "reason": "bad_amount"}

        m_utr = _UTR_RE.search(text)
        if m_utr:
            utr = m_utr.group(1).strip()
        else:
            m_fb = _FALLBACK_DIGITS_RE.search(text)
            if not m_fb:
                self.total_skipped += 1
                return {"status": "skipped", "reason": "no_utr"}
            utr = m_fb.group(1).strip()

        self._prune()
        self.cache[utr] = {"amount": amount, "ts": datetime.datetime.utcnow()}
        self.total_parsed += 1
        self.last_credit_at = datetime.datetime.utcnow()
        logger.info(f"[SMS] ✅ cached credit UTR={utr} amount=Rs.{amount}")
        return {"status": "cached", "utr": utr, "amount": amount}

    def lookup(self, utr: str) -> dict | None:
        """Return cached entry for UTR, or None. Auto-prunes expired entries."""
        self._prune()
        return self.cache.get((utr or "").strip())


# Module-level singleton
verifier = SmsVerifier()


async def unified_verify(utr: str, expected_amount: float,
                         tolerance: float = 1.0, timeout: int = 600) -> dict:
    """Wait up to `timeout` seconds for an SMS that matches the given UTR.

    Polls the in-memory cache every few seconds. Returns one of:
      {"matched": True,  "amount": <amount>, "subject": ""}
      {"matched": False, "reason": "amount_mismatch", "expected": .., "received": ..}
      {"matched": False, "reason": "not_found"}
      {"matched": False, "reason": "not_configured"}
    """
    if not verifier.is_configured():
        return {"matched": False, "reason": "not_configured"}

    utr = (utr or "").strip()
    if not utr:
        return {"matched": False, "reason": "not_found"}

    deadline = asyncio.get_event_loop().time() + max(1, int(timeout))
    poll_every = 3  # seconds

    # Cross-process DB lookup (userbot writes there from a different process)
    try:
        from database import sms_cache_get as _db_sms_cache_get
    except Exception:
        _db_sms_cache_get = None

    while asyncio.get_event_loop().time() < deadline:
        hit = verifier.lookup(utr)
        if hit is None and _db_sms_cache_get is not None:
            try:
                hit = await _db_sms_cache_get(utr)
            except Exception as _ge:
                logger.warning(f"[SMS] DB lookup failed: {_ge}")
                hit = None
        if hit is not None:
            received = float(hit["amount"])
            if abs(received - float(expected_amount)) <= float(tolerance):
                logger.info(f"[SMS] ✅ matched UTR={utr} amount=Rs.{received}")
                return {"matched": True, "amount": received, "subject": ""}
            logger.info(f"[SMS] ⚠️ amount_mismatch UTR={utr} expected={expected_amount} received={received}")
            return {
                "matched": False,
                "reason": "amount_mismatch",
                "expected": float(expected_amount),
                "received": received,
            }
        await asyncio.sleep(poll_every)

    return {"matched": False, "reason": "not_found"}
