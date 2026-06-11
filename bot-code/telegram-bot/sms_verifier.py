"""SMS verifier stub — replaced by ALOO BharatPe API verification."""
import os, logging
logger = logging.getLogger("sms_verifier")

SMS_GROUP_ID = 0
SMS_SENDER_FILTER = ""
SMS_FILTERS = []


class SmsVerifier:
    def is_configured(self): return False
    def add_from_message(self, text): return {"status": "skipped", "reason": "stub"}
    def lookup(self, utr): return None

verifier = SmsVerifier()


async def unified_verify(utr, expected_amount, tolerance=1.0, timeout=600):
    return {"matched": False, "reason": "not_configured"}
