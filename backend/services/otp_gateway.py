"""
backend/services/otp_gateway.py
================================
Pluggable OTP delivery gateway.

Strategy pattern: swap providers by changing OTP_PROVIDER env var.
  • telegram   — dev/staging: free, zero infra, instant
  • aakash     — Nepal prod:  Aakash SMS (aakashsms.com)
  • sparrow    — Nepal prod:  Sparrow SMS (sparrowsms.com.np)

The core auth logic (generate → store in Redis → verify) never
changes regardless of which gateway is active.
"""

from __future__ import annotations

import logging
import os
import random
import secrets
import string
import time
from abc import ABC, abstractmethod
from typing import Protocol

import httpx
import redis.asyncio as aioredis

log = logging.getLogger("bustrack.otp")

# ──────────────────────────────────────────────────────────────────────────────
#  OTP store in Redis
#  Key:  otp:{identifier}   Value: {code}:{ts}   TTL: 300s
# ──────────────────────────────────────────────────────────────────────────────

OTP_TTL_SECONDS = 300          # 5 minutes to enter the code
OTP_RATE_LIMIT_SECONDS = 60    # minimum gap between resend requests


def _gen_otp() -> str:
    """Cryptographically secure 6-digit OTP."""
    return "".join(secrets.choice(string.digits) for _ in range(6))


async def store_otp(r: aioredis.Redis, identifier: str, code: str) -> None:
    await r.setex(f"otp:{identifier}", OTP_TTL_SECONDS, f"{code}:{time.time()}")


async def verify_otp(r: aioredis.Redis, identifier: str, code: str) -> bool:
    """Returns True and deletes the key on success; False otherwise."""
    stored = await r.get(f"otp:{identifier}")
    if not stored:
        return False
    stored_code, _ = stored.split(":", 1)
    if secrets.compare_digest(stored_code, code):
        await r.delete(f"otp:{identifier}")
        return True
    return False


async def is_rate_limited(r: aioredis.Redis, identifier: str) -> bool:
    key = f"otp_rate:{identifier}"
    if await r.exists(key):
        return True
    await r.setex(key, OTP_RATE_LIMIT_SECONDS, "1")
    return False


# ──────────────────────────────────────────────────────────────────────────────
#  Abstract gateway
# ──────────────────────────────────────────────────────────────────────────────

class OTPGateway(ABC):
    """
    All concrete gateways implement exactly one method: send_otp.
    identifier is a phone number for SMS gateways,
    or a Telegram chat_id for the Telegram gateway.
    """

    @abstractmethod
    async def send_otp(self, identifier: str, code: str) -> bool:
        """Return True on delivery success, False on provider error."""
        ...

    async def issue(self, r: aioredis.Redis, identifier: str) -> bool:
        """
        Public entry point called by the auth router.
        Checks rate limit, generates OTP, stores in Redis, sends via provider.
        """
        if await is_rate_limited(r, identifier):
            log.warning("OTP rate-limited for %s", identifier)
            return False
        code = _gen_otp()
        await store_otp(r, identifier, code)
        ok = await self.send_otp(identifier, code)
        if not ok:
            await r.delete(f"otp:{identifier}")  # clean up on send failure
        return ok


# ──────────────────────────────────────────────────────────────────────────────
#  1.  Telegram gateway  (development / staging)
# ──────────────────────────────────────────────────────────────────────────────

class TelegramMockSMSGateway(OTPGateway):
    """
    Uses Telegram Bot API as a zero-cost OTP channel.

    Flow:
      1. Parent opens app → taps "Get OTP via Telegram"
      2. App opens deep link: https://t.me/<BOT_NAME>?start=auth
      3. User sends /start to the bot in Telegram
      4. FastAPI webhook endpoint receives the update, extracts chat_id,
         maps it to the user's pending session (stored in Redis), fires issue()
      5. Bot sends "Your KTM Bus OTP: 123456"

    Required env vars:
      TELEGRAM_BOT_TOKEN   — from @BotFather
      TELEGRAM_BOT_NAME    — e.g. KTMBusTrackerBot  (no @)
    """

    BASE_URL = "https://api.telegram.org/bot{token}"

    def __init__(self) -> None:
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.bot_name = os.getenv("TELEGRAM_BOT_NAME", "YourBusTrackerBot")
        self._api = self.BASE_URL.format(token=self.token)

    def deep_link_url(self) -> str:
        """Return the URL the Flutter app opens to start the auth flow."""
        return f"https://t.me/{self.bot_name}?start=auth"

    async def send_otp(self, chat_id: str, code: str) -> bool:
        """Send the OTP message to the Telegram chat."""
        message = (
            f"🚌 *KTM School Bus Tracker*\n\n"
            f"Your one-time password is:\n\n"
            f"*{code}*\n\n"
            f"Valid for 5 minutes. Do not share this code."
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(
                    f"{self._api}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": message,
                        "parse_mode": "Markdown",
                    },
                )
                data = resp.json()
                if not data.get("ok"):
                    log.error("Telegram sendMessage failed: %s", data)
                    return False
                log.info("OTP sent via Telegram to chat_id=%s", chat_id)
                return True
        except httpx.RequestError as exc:
            log.error("Telegram request error: %s", exc)
            return False

    async def register_webhook(self, public_url: str) -> bool:
        """Call once at startup to register the webhook with Telegram."""
        webhook_url = f"{public_url}/api/telegram/webhook"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{self._api}/setWebhook",
                    json={"url": webhook_url, "allowed_updates": ["message"]},
                )
                data = resp.json()
                log.info("Telegram webhook registration: %s", data)
                return data.get("ok", False)
        except httpx.RequestError as exc:
            log.error("Webhook registration failed: %s", exc)
            return False


# ──────────────────────────────────────────────────────────────────────────────
#  2.  Aakash SMS gateway  (Nepal production)
#      https://aakashsms.com/sms/v3/send
# ──────────────────────────────────────────────────────────────────────────────

class AakashSMSGateway(OTPGateway):
    """
    Aakash SMS — popular Nepal SMS provider.
    Required env vars: AAKASH_API_KEY
    identifier must be a Nepal phone number e.g. "9801234567"
    """

    API_URL = "https://sms.aakashsms.com/sms/v3/send"

    def __init__(self) -> None:
        self.api_key = os.environ["AAKASH_API_KEY"]

    async def send_otp(self, phone: str, code: str) -> bool:
        payload = {
            "auth_token": self.api_key,
            "to": phone,
            "text": f"Your KTM Bus Tracker OTP is {code}. Valid 5 min. Do not share.",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(self.API_URL, data=payload)
                resp.raise_for_status()
                log.info("OTP sent via Aakash SMS to %s", phone)
                return True
        except httpx.HTTPStatusError as exc:
            log.error("Aakash SMS error %s: %s", exc.response.status_code, exc.response.text)
            return False
        except httpx.RequestError as exc:
            log.error("Aakash SMS request error: %s", exc)
            return False


# ──────────────────────────────────────────────────────────────────────────────
#  3.  Sparrow SMS gateway  (Nepal production)
#      https://api.sparrowsms.com/v2/sms/
# ──────────────────────────────────────────────────────────────────────────────

class SparrowSMSGateway(OTPGateway):
    """
    Sparrow SMS — another popular Nepal SMS provider.
    Required env vars: SPARROW_TOKEN
    """

    API_URL = "https://api.sparrowsms.com/v2/sms/"

    def __init__(self) -> None:
        self.token = os.environ["SPARROW_TOKEN"]

    async def send_otp(self, phone: str, code: str) -> bool:
        payload = {
            "token": self.token,
            "from": "BusTracker",
            "to": phone,
            "text": f"Your KTM Bus Tracker OTP is {code}. Valid 5 min. Do not share.",
        }
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.post(self.API_URL, data=payload)
                resp.raise_for_status()
                log.info("OTP sent via Sparrow SMS to %s", phone)
                return True
        except httpx.HTTPStatusError as exc:
            log.error("Sparrow SMS error %s: %s", exc.response.status_code, exc.response.text)
            return False
        except httpx.RequestError as exc:
            log.error("Sparrow SMS request error: %s", exc)
            return False


# ──────────────────────────────────────────────────────────────────────────────
#  Factory — select gateway from env var
# ──────────────────────────────────────────────────────────────────────────────

def get_otp_gateway() -> OTPGateway:
    """
    OTP_PROVIDER=telegram  → TelegramMockSMSGateway  (default, dev)
    OTP_PROVIDER=aakash    → AakashSMSGateway
    OTP_PROVIDER=sparrow   → SparrowSMSGateway
    """
    provider = os.getenv("OTP_PROVIDER", "telegram").lower()
    if provider == "aakash":
        return AakashSMSGateway()
    if provider == "sparrow":
        return SparrowSMSGateway()
    return TelegramMockSMSGateway()

