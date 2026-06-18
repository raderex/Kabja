# Telegram OTP Integration — Backend Implementation

## Overview

The KTM Bus Tracker backend implements **Telegram-based OTP authentication** for secure, free, and instant login without SMS costs. This document describes the backend implementation.

## Architecture

### Components

1. **OTP Gateway** (`services/otp_gateway.py`)
   - Abstract gateway interface with multiple implementations
   - Telegram, Aakash SMS, Sparrow SMS support
   - Rate limiting and Redis-based OTP storage

2. **Auth Endpoints** (`main.py`)
   - `/api/auth/otp/request` — Issue OTP via configured provider
   - `/api/auth/otp/verify` — Verify code and return JWT
   - `/api/auth/telegram/deeplink` — Get bot deep link for Flutter
   - `/api/telegram/webhook` — Webhook receiver for Telegram updates

3. **Redis Schema**
   ```
   otp:{chat_id}           → {code}:{timestamp}    TTL: 5 min
   otp_rate:{chat_id}      → "1"                    TTL: 60 sec
   tg_pending:{chat_id}    → "pending"              TTL: 10 min
   driver:{username}:assignment    → hash with bus_id, route_id
   parent:{username}:routes        → set of allowed route_ids
   ```

## Implementation Details

### OTP Gateway Pattern

```python
# Abstract base class
class OTPGateway(ABC):
    async def send_otp(self, identifier: str, code: str) -> bool:
        """Deliver OTP via provider"""
        
    async def issue(self, r: Redis, identifier: str) -> bool:
        """Rate limit → generate → store → send"""

# Concrete implementations
class TelegramMockSMSGateway(OTPGateway):
    # For development/staging
    async def send_otp(self, chat_id: str, code: str) -> bool:
        # Uses Telegram Bot API
        
class AakashSMSGateway(OTPGateway):
    # For Nepal production
    async def send_otp(self, phone: str, code: str) -> bool:
        # Uses Aakash SMS API
```

### Authentication Flow

```
1. Flutter App
   POST /api/auth/otp/request
   {
     "username": "parent_123",
     "identifier": "123456789",  // Telegram chat_id or phone
     "role": "parent"
   }

2. Backend
   a. Check rate limit (1 OTP per 60 sec per identifier)
   b. Generate 6-digit code (cryptographically secure)
   c. Store in Redis: otp:{identifier} = {code}:{timestamp}
   d. Send via Telegram: "Your OTP: 123456"
   e. Return to Flutter: {"status": "otp_sent"}

3. Flutter App (after receiving code)
   POST /api/auth/otp/verify
   {
     "username": "parent_123",
     "identifier": "123456789",
     "code": "123456",
     "role": "parent"
   }

4. Backend
   a. Verify: Redis.get(otp:{identifier}) == 123456
   b. Delete OTP from Redis (one-time use)
   c. Fetch role-specific data:
      - If driver: get assigned bus_id, route_id
      - If parent: get allowed routes
   d. Sign JWT with role + route data
   e. Return: {"access_token": "...", "token_type": "bearer"}

5. Flutter App
   Store JWT in secure storage
   Use for all future API requests
```

## Code Examples

### Issuing OTP

```python
# File: main.py

@app.post("/api/auth/otp/request")
async def otp_request(body: OTPRequestBody) -> dict[str, Any]:
    """
    Issue a 6-digit OTP via configured gateway.
    
    body.identifier:
      - Telegram mode: chat_id (number string)
      - SMS mode: phone number (e.g. "9801234567")
    """
    r = await get_redis()
    
    # otp_gateway.issue() handles:
    # - Rate limiting
    # - Code generation
    # - Redis storage
    # - Provider delivery
    ok = await otp_gateway.issue(r, body.identifier)
    
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="OTP could not be sent. Check identifier or try again.",
        )
    
    response = {"status": "otp_sent"}
    
    # Include hint for Telegram mode
    if isinstance(otp_gateway, TelegramMockSMSGateway):
        response["telegram_link"] = otp_gateway.deep_link_url()
        response["hint"] = "Open link, send /start, enter code"
    
    return response
```

### Verifying OTP

```python
@app.post("/api/auth/otp/verify")
async def otp_verify(body: OTPVerifyBody) -> dict[str, str]:
    """
    Verify OTP code and return signed JWT.
    
    JWT contains:
    - sub: username
    - role: driver|parent|admin
    - assigned_bus, assigned_route (if driver)
    - allowed_routes (if parent)
    """
    r = await get_redis()
    
    # Verify code (returns False if invalid or expired)
    if not await verify_otp(r, body.identifier, body.code):
        raise HTTPException(status_code=401, detail="Invalid OTP")
    
    # Get role-specific metadata
    extra = {}
    
    if body.role == "driver":
        # Fetch driver assignment from Redis
        assignment = await r.hgetall(f"driver:{body.username}:assignment")
        if assignment:
            extra["assigned_bus"] = assignment.get("bus_id")
            extra["assigned_route"] = assignment.get("route_id")
    
    elif body.role == "parent":
        # Fetch parent's subscribed routes
        routes = await r.smembers(f"parent:{body.username}:routes")
        if routes:
            extra["allowed_routes"] = list(routes)
    
    # Create JWT
    token = create_token(
        sub=body.username,
        role=body.role,
        extra=extra
    )
    
    return {"access_token": token, "token_type": "bearer"}
```

### Telegram Gateway

```python
# File: services/otp_gateway.py

class TelegramMockSMSGateway(OTPGateway):
    """
    Development/staging OTP delivery via Telegram Bot API.
    
    Required env vars:
      - TELEGRAM_BOT_TOKEN: from @BotFather
      - TELEGRAM_BOT_NAME: bot username
    """
    
    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.bot_name = os.getenv("TELEGRAM_BOT_NAME")
        self._api = f"https://api.telegram.org/bot{self.token}"
    
    def deep_link_url(self) -> str:
        """Return URL for Flutter to open Telegram bot"""
        return f"https://t.me/{self.bot_name}?start=auth"
    
    async def send_otp(self, chat_id: str, code: str) -> bool:
        """Send OTP message to Telegram chat"""
        message = (
            f"🚌 *KTM School Bus Tracker*\n\n"
            f"Your one-time password is:\n\n"
            f"*{code}*\n\n"
            f"Valid for 5 minutes."
        )
        
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{self._api}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                }
            )
            
            if resp.json().get("ok"):
                log.info("OTP sent to chat_id=%s", chat_id)
                return True
            else:
                log.error("Failed to send OTP: %s", resp.json())
                return False
    
    async def register_webhook(self, public_url: str) -> bool:
        """Register webhook URL with Telegram servers"""
        webhook_url = f"{public_url}/api/telegram/webhook"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self._api}/setWebhook",
                json={
                    "url": webhook_url,
                    "allowed_updates": ["message"],
                }
            )
            
            data = resp.json()
            if data.get("ok"):
                log.info("Telegram webhook registered: %s", webhook_url)
                return True
            else:
                log.error("Webhook registration failed: %s", data)
                return False
```

### Telegram Webhook Receiver

```python
@app.post("/api/telegram/webhook")
async def telegram_webhook(update: TelegramUpdate, request: Request) -> dict:
    """
    Receive and process Telegram bot messages.
    
    When user sends /start:
    1. Mark chat_id as pending in Redis (tg_pending:{chat_id})
    2. Send welcome message
    3. User taps "Request OTP" in Flutter
    4. Backend sends OTP via /api/auth/otp/request
    """
    
    # Verify webhook secret if configured
    if TELEGRAM_WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if secret != TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Bad secret")
    
    msg = update.message
    if not msg:
        return {"status": "no_message"}
    
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    
    # Only handle /start command
    if not text.startswith("/start"):
        return {"status": "ignored"}
    
    # Mark this chat_id as ready for OTP
    r = await get_redis()
    await r.setex(f"tg_pending:{chat_id}", 600, "pending")
    
    log.info("Telegram /start from chat_id=%s", chat_id)
    
    # Send welcome message
    if TELEGRAM_BOT_TOKEN:
        welcome = (
            "🚌 *KTM School Bus Tracker*\n\n"
            "Go back to the app and tap *Request OTP*.\n"
            "I'll send your code here right away!"
        )
        
        async with httpx.AsyncClient(timeout=6.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": welcome,
                    "parse_mode": "Markdown",
                }
            )
    
    return {"status": "ok", "chat_id": chat_id}
```

## Rate Limiting

The OTP system implements **60-second rate limiting** per identifier:

```python
async def is_rate_limited(r: Redis, identifier: str) -> bool:
    """
    Returns True if identifier has requested OTP in last 60 seconds.
    """
    key = f"otp_rate:{identifier}"
    
    if await r.exists(key):
        return True  # Still rate limited
    
    # Set rate limit flag
    await r.setex(key, 60, "1")
    return False
```

This prevents brute-force attacks and spam.

## Security Considerations

### OTP Storage
- **Stored in Redis** with 5-minute TTL
- **Deleted immediately** after successful verification (one-time use)
- **Never persisted** to database

### Code Generation
```python
def _gen_otp() -> str:
    """Cryptographically secure 6-digit code"""
    return "".join(secrets.choice(string.digits) for _ in range(6))
```
Uses Python's `secrets` module (CSPRNG), not `random`.

### OTP Comparison
```python
if secrets.compare_digest(stored_code, code):
    # Constant-time comparison prevents timing attacks
```

### JWT Security
```python
token = jwt.encode(
    payload={
        "sub": username,
        "role": role,
        "exp": datetime.now() + timedelta(minutes=1440),
        **extra
    },
    key=JWT_SECRET,
    algorithm="HS256"
)
```

## Environment Variables

| Variable | Dev | Prod | Description |
|----------|-----|------|-------------|
| `TELEGRAM_BOT_TOKEN` | Required | Required | Token from @BotFather |
| `TELEGRAM_BOT_NAME` | Optional | Required | Bot username (no @) |
| `TELEGRAM_WEBHOOK_SECRET` | Optional | Required | Secret for webhook verification |
| `OTP_PROVIDER` | `telegram` | `telegram\|aakash\|sparrow` | OTP delivery method |
| `PUBLIC_URL` | `http://localhost:8000` | HTTPS domain | For webhook registration |
| `JWT_SECRET` | Any value | Strong random | For signing tokens |
| `REDIS_HOST` | `localhost` | Redis host | For OTP storage |

## Testing

### Manual OTP Flow
```bash
# 1. Request OTP
curl -X POST http://localhost:8000/api/auth/otp/request \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "identifier": "123456789",
    "role": "parent"
  }'

# Expected response:
# {"status": "otp_sent", "telegram_link": "..."}

# 2. Check Redis for code
redis-cli GET "otp:123456789"
# Example: 847392:1621234567.89

# 3. Verify OTP
curl -X POST http://localhost:8000/api/auth/otp/verify \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "identifier": "123456789",
    "code": "847392",
    "role": "parent"
  }'

# Expected response:
# {"access_token": "eyJ0eXAi...", "token_type": "bearer"}
```

### Unit Tests

```python
# tests/test_otp.py

@pytest.mark.asyncio
async def test_otp_generation():
    """OTP should be 6 digits"""
    code = _gen_otp()
    assert len(code) == 6
    assert code.isdigit()

@pytest.mark.asyncio
async def test_rate_limiting(redis):
    """Second request within 60s should be rate limited"""
    result1 = await is_rate_limited(redis, "test_user")
    assert result1 is False
    
    result2 = await is_rate_limited(redis, "test_user")
    assert result2 is True
    
    # After 60s, should be allowed
    await asyncio.sleep(61)
    result3 = await is_rate_limited(redis, "test_user")
    assert result3 is False
```

## Production Deployment

### Prerequisites
- HTTPS enabled with valid SSL certificate
- Redis with persistence enabled
- Telegram bot created and configured
- Public domain registered

### Configuration Checklist
- [ ] `TELEGRAM_BOT_TOKEN` set from @BotFather
- [ ] `TELEGRAM_BOT_NAME` matches actual bot username
- [ ] `TELEGRAM_WEBHOOK_SECRET` is a strong random secret
- [ ] `PUBLIC_URL` is HTTPS and publicly accessible
- [ ] `JWT_SECRET` is 32+ character random string
- [ ] `OTP_PROVIDER` is set to `telegram`
- [ ] Webhook is registered: `python telegram_bot.py info`

### Monitoring

```bash
# Check webhook status
curl -X GET https://api.telegram.org/bot<TOKEN>/getWebhookInfo | jq

# Monitor OTP requests
docker-compose logs -f api | grep -i otp

# Check Redis OTP keys
redis-cli KEYS "otp:*"

# Monitor rate limiting
redis-cli KEYS "otp_rate:*"
```

## Switching Providers

To switch from Telegram to SMS (Aakash or Sparrow):

1. **Update .env**
   ```env
   OTP_PROVIDER=aakash  # or sparrow
   AAKASH_API_KEY=your_key
   ```

2. **Update Flutter** to request phone number instead of chat_id

3. **Restart backend**
   ```bash
   docker-compose restart api
   ```

The SMS provider will automatically be used for all OTP requests.

---

*For user-facing setup instructions, see [TELEGRAM_BOT_SETUP.md](../TELEGRAM_BOT_SETUP.md)*
