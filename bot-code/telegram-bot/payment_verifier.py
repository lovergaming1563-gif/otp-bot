"""Auto-payment verifier using bharataalu.animeverse23.in API.

Endpoint: GET /api/v1/verify?api_key=<key>&merchant_id=<mid>&amount=<amount>
Response:  {"success": true, "merchant_id": "...", "utr": "UTR..."}
           {"success": false, ...}

Health:    GET /api/v1/ping

Required env vars:
    VERIFY_API_KEY      — API key for the payment gateway
    VERIFY_MERCHANT_ID  — Merchant ID registered with the gateway
"""

import os
import asyncio
import logging
import aiohttp

logger = logging.getLogger("payment_verifier")

BASE_URL = "http://bharataalu.animeverse23.in"
VERIFY_ENDPOINT = "/api/v1/verify"
PING_ENDPOINT = "/api/v1/ping"

VERIFY_API_KEY = os.getenv("VERIFY_API_KEY", "").strip()
VERIFY_MERCHANT_ID = os.getenv("VERIFY_MERCHANT_ID", "").strip()

POLL_INTERVAL = 5   # seconds between API polls
REQUEST_TIMEOUT = 10  # seconds per HTTP request


def is_configured() -> bool:
    """Return True only if both env vars are set."""
    return bool(VERIFY_API_KEY and VERIFY_MERCHANT_ID)


async def ping() -> bool:
    """Check if the API is reachable. Returns True on success."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}{PING_ENDPOINT}",
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                return resp.status == 200
    except Exception as e:
        logger.warning(f"[PayVerify] ping failed: {e}")
        return False


async def verify_payment(
    amount: float,
    timeout: int = 600,
    poll_interval: int = POLL_INTERVAL,
) -> dict:
    """Poll the API until a payment matching `amount` is detected or timeout.

    Returns one of:
        {"matched": True,  "utr": "<UTR>", "amount": <amount>}
        {"matched": False, "reason": "not_configured"}
        {"matched": False, "reason": "not_found"}   # timeout reached
        {"matched": False, "reason": "api_error", "detail": "..."}
    """
    if not is_configured():
        logger.warning("[PayVerify] not configured — VERIFY_API_KEY / VERIFY_MERCHANT_ID missing")
        return {"matched": False, "reason": "not_configured"}

    params = {
        "api_key": VERIFY_API_KEY,
        "merchant_id": VERIFY_MERCHANT_ID,
        "amount": str(amount),
    }

    deadline = asyncio.get_event_loop().time() + max(1, int(timeout))

    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() < deadline:
            try:
                async with session.get(
                    f"{BASE_URL}{VERIFY_ENDPOINT}",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if data.get("success"):
                            utr = str(data.get("utr", "")).strip()
                            logger.info(
                                f"[PayVerify] ✅ payment detected — amount={amount} utr={utr}"
                            )
                            return {"matched": True, "utr": utr, "amount": amount}
                        else:
                            logger.debug(
                                f"[PayVerify] poll — no payment yet for amount={amount}"
                            )
                    else:
                        logger.warning(
                            f"[PayVerify] HTTP {resp.status} from verify endpoint"
                        )
            except aiohttp.ClientError as e:
                logger.warning(f"[PayVerify] request error: {e}")
            except Exception as e:
                logger.error(f"[PayVerify] unexpected error: {e}", exc_info=True)
                return {"matched": False, "reason": "api_error", "detail": str(e)}

            await asyncio.sleep(poll_interval)

    logger.info(f"[PayVerify] timeout reached for amount={amount}")
    return {"matched": False, "reason": "not_found"}
