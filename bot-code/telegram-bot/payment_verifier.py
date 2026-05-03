import aiohttp
import logging
import io
import random

logger = logging.getLogger(__name__)

VERIFY_BASE_URL = "http://bharataalu.animeverse23.in"
MAX_TRIES = 5


async def verify_payment(api_key: str, merchant_id: str, amount: float) -> dict:
    """
    Call bharataalu API to verify a UPI payment by exact amount.
    Returns: {"success": bool, "utr": str or None, "error": str or None}
    """
    url = f"{VERIFY_BASE_URL}/api/v1/verify"
    params = {
        "api_key": api_key,
        "merchant_id": merchant_id,
        "amount": f"{amount:.2f}",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                data = await resp.json(content_type=None)
                if data.get("success"):
                    return {"success": True, "utr": data.get("utr"), "error": None}
                else:
                    return {
                        "success": False,
                        "utr": None,
                        "error": data.get("message", "Payment not found"),
                    }
    except Exception as e:
        logger.error(f"[PAYMENT] API call failed: {e}")
        return {"success": False, "utr": None, "error": str(e)}


def generate_unique_amount(base_amount: float) -> float:
    """Add random paise (01-99) to make amount unique per payment."""
    paise = random.randint(1, 99)
    return round(base_amount + paise / 100, 2)


def generate_upi_qr_bytes(upi_id: str, amount: float, name: str = "OTP Service") -> io.BytesIO:
    """Generate a UPI QR code image and return as BytesIO."""
    import qrcode
    upi_link = (
        f"upi://pay?pa={upi_id}"
        f"&pn={name.replace(' ', '%20')}"
        f"&am={amount:.2f}"
        f"&cu=INR"
        f"&tn=Deposit"
    )
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(upi_link)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
