import hashlib
import hmac
import json
import logging
from decimal import Decimal

import httpx
from fastapi import HTTPException, status

from backend.app.config import settings


logger = logging.getLogger(__name__)
RAZORPAY_API = "https://api.razorpay.com/v1"


def ensure_razorpay_configured() -> None:
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Online payments are not configured. Contact the resort to complete this booking.",
        )
    if settings.razorpay_test_mode and not settings.razorpay_key_id.startswith("rzp_test_"):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Test mode is enabled, but the configured key is not a Razorpay test key.",
        )


def razorpay_request(method: str, path: str, **kwargs) -> dict:
    ensure_razorpay_configured()
    try:
        with httpx.Client(
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret),
            timeout=15,
        ) as client:
            response = client.request(method, f"{RAZORPAY_API}{path}", **kwargs)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Razorpay request failed with status %s.", exc.response.status_code)
        raise HTTPException(status_code=502, detail="Payment provider rejected the request.") from None
    except (httpx.RequestError, ValueError):
        logger.exception("Could not complete the Razorpay request.")
        raise HTTPException(status_code=502, detail="Payment provider is temporarily unavailable.") from None


def verify_checkout_signature(order_id: str, payment_id: str, signature: str) -> bool:
    expected = hmac.new(
        settings.razorpay_key_secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, signature: str | None) -> bool:
    if not settings.razorpay_webhook_secret or not signature:
        return False
    expected = hmac.new(
        settings.razorpay_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def to_paise(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


def to_rupees(paise: int) -> Decimal:
    return (Decimal(paise) / Decimal(100)).quantize(Decimal("0.01"))


def compact_json(value: dict) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
