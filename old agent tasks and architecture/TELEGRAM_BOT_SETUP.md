# Telegram Bot Setup Guide — KTM Bus Tracker OTP Authentication

## Overview

The KTM Bus Tracker app uses **Telegram as an OTP delivery channel** for secure, instant login without SMS costs. Users enter their Telegram Chat ID and receive OTP immediately.

### Simplified Flow
1. User enters **Chat ID** (from @userinfobot)
2. Backend sends **OTP directly** to Telegram
3. User enters **6-digit code** in app
4. ✅ **Logged in!**

No need to send `/start` or open the bot manually!

### Flow Diagram
```
┌─────────────────────────────┐
│  Flutter App                │
│  1. Enter Chat ID           │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────────┐
│  Backend: /api/auth/otp/request │
│  2. Generate OTP                │
│  3. Send via Telegram           │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Telegram Bot               │
│  "Your OTP: 123456"         │
└────────┬────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Flutter App                │
│  4. Enter 6-digit OTP       │
└────────┬────────────────────┘
         │
         ▼
┌──────────────────────────────────┐
│  Backend: /api/auth/otp/verify   │
│  5. Verify & return JWT          │
└────────┬─────────────────────────┘
         │
         ▼
    ✅ Logged In!
```

---

## Step 1: Create the Telegram Bot

### Prerequisites
- Telegram account
- Access to @BotFather (Telegram's official bot creation tool)

### Create Bot
1. **Open Telegram** and search for **@BotFather**
2. Send `/start` → follow the welcome message
3. Send `/newbot`
4. **Choose a name** for your bot (e.g., "KTM Bus Tracker")
5. **Choose a username** (must end with "bot", e.g., `ktm_bus_tracker_bot`)
6. **Copy the token** that looks like:
   ```
   123456789:ABCdefGHIjklmnoPQRstuvWXYZabcdefGHI
   ```

### Configure Bot Permissions (Optional but Recommended)
1. Go back to @BotFather, send `/mybots`
2. Select your bot, then `/setcommands`
3. Paste:
   ```
   start - Receive your login OTP code
   help - Get help
   ```

---

## Step 2: Deploy Backend with HTTPS

**Telegram requires HTTPS for webhook!** Your public URL must be `https://` not `http://`.

### Option A: Using ngrok (Development)
```bash
# Install ngrok: https://ngrok.com/
ngrok http 8000
# Gets you a URL like: https://abc123.ngrok.io
```

### Option B: Using your own domain
```bash
# Example: https://bustrack.yourdomain.com
# Must have valid SSL certificate (use Let's Encrypt for free)
```

### Option C: Using Docker + Nginx Reverse Proxy
See [DEPLOYMENT.md](../DEPLOYMENT.md) for full production setup.

---

## Step 3: Configure Environment Variables

1. **Copy the example file:**
   ```bash
   cp .env.example .env
   ```

2. **Fill in Telegram credentials:**
   ```env
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklmnoPQRstuvWXYZabcdefGHI
   TELEGRAM_BOT_NAME=ktm_bus_tracker_bot
   TELEGRAM_WEBHOOK_SECRET=your-random-secret-key-12345
   PUBLIC_URL=https://your-public-domain.com
   OTP_PROVIDER=telegram
   JWT_SECRET=your-jwt-secret-key
   ```

3. **Generate a random webhook secret:**
   ```bash
   python -c "import secrets; print(secrets.token_hex(16))"
   # Example output: 8f3a2c9d1e5b4f7a6c2d9e1f3a5b7c8d
   ```

---

## Step 4: Register Webhook with Telegram

The backend needs to tell Telegram where to send incoming messages (the webhook URL).

### Using the Management Script

We provide a Python utility to register/manage the webhook:

```bash
# Make it executable
chmod +x backend/telegram_bot.py

# Register webhook
python backend/telegram_bot.py register

# Check status
python backend/telegram_bot.py info

# Send test message
python backend/telegram_bot.py test 123456789  # Replace with your chat_id
```

### Manually Register Webhook

If the script doesn't work, register manually:

```bash
curl -X POST https://api.telegram.org/bot<YOUR_TOKEN>/setWebhook \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-public-domain.com/api/telegram/webhook",
    "allowed_updates": ["message"],
    "secret_token": "your-webhook-secret"
  }'
```

Expected response:
```json
{
  "ok": true,
  "result": true,
  "description": "Webhook was set"
}
```

---

## Step 5: Find Your Telegram Chat ID

You need your chat_id for testing. Here are two ways:

### Method 1: Using the Bot Itself
1. Send `/start` to your bot in Telegram
2. Go to: `https://t.me/userinfobot`
3. Send `/start` and it will show your user ID (use this as chat_id)

### Method 2: Using the API
```bash
# After sending a message to your bot, check the logs:
python backend/telegram_bot.py info
# Look for the webhook info which shows recent message chat_id
```

---

## Step 6: Test the Integration

### Test 1: Send Message to Bot
1. Open Telegram
2. Search for your bot (e.g., @ktm_bus_tracker_bot)
3. Send `/start`
4. Check your backend logs for: `Telegram /start from chat_id=...`

### Test 2: Verify Webhook Registration
```bash
python backend/telegram_bot.py info
```

Expected output:
```
✅ Webhook info retrieved:
   URL: https://your-public-domain.com/api/telegram/webhook
   IP: 91.108.x.x (Telegram's IP)
   Pending updates: 0
```

### Test 3: Send Test OTP
```bash
# Get your chat_id first (see "Find Your Telegram Chat ID" above)
python backend/telegram_bot.py test YOUR_CHAT_ID
```

You should see: `🚌 KTM School Bus Tracker` test message in your Telegram DM.

---

## Step 7: Test in Flutter App

### Development Mode (Telegram)
1. **Start backend:**
   ```bash
   cd backend
   python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

2. **Update Flutter config** (`flutter/lib/core/config/app_config.dart`):
   ```dart
   class AppConfig {
     static const String baseUrl = 'http://localhost:8000';
     static const String telegramBotName = 'your_bot_name_here';
   }
   ```

3. **Start Flutter app:**
   ```bash
   cd flutter
   flutter run
   ```

4. **Test Login Flow (Simplified):**
   - Enter username: `testuser`
   - Select role: `parent`
   - Get your Chat ID from @userinfobot
   - Enter Chat ID in the app
   - Tap "Send OTP to Telegram"
   - **Instantly** receive OTP in Telegram DM
   - Enter 6-digit code in app
   - ✅ Login successful!

**That's it!** No need to send /start or open the bot manually anymore.

---

## Production Deployment

### Requirements
- ✅ HTTPS enabled with valid SSL certificate
- ✅ Backend publicly accessible
- ✅ Telegram bot token stored securely (environment variable)
- ✅ Webhook secret configured
- ✅ Redis running with persistence
- ✅ JWT secret generated and stored securely

### Using Docker Compose
```bash
# Build images
docker-compose build

# Start services
docker-compose up -d

# Check backend is running
curl https://your-domain.com/health

# Register webhook
docker-compose exec backend python telegram_bot.py register

# View logs
docker-compose logs -f backend
```

### Environment Variables Checklist
- [ ] `TELEGRAM_BOT_TOKEN` — Set and unique per environment
- [ ] `TELEGRAM_WEBHOOK_SECRET` — Strong random secret
- [ ] `PUBLIC_URL` — HTTPS domain
- [ ] `JWT_SECRET` — 32+ character random secret
- [ ] `REDIS_HOST` — Pointing to Redis instance
- [ ] `OTP_PROVIDER` — Set to `telegram`

---

## Troubleshooting

### Webhook Not Registering
```bash
# Check if PUBLIC_URL is HTTPS
echo $PUBLIC_URL
# Must start with https://

# Verify SSL certificate is valid
curl -v https://your-domain.com/api/telegram/webhook

# Check webhook secret is set
python backend/telegram_bot.py info
```

### Bot Not Receiving Messages
```bash
# Check backend logs
docker-compose logs -f backend | grep -i telegram

# Verify webhook is registered
curl -X GET https://api.telegram.org/bot<TOKEN>/getWebhookInfo

# Manually test webhook
curl -X POST https://your-domain.com/api/telegram/webhook \
  -H "X-Telegram-Bot-Api-Secret-Token: YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"update_id": 999, "message": {"chat": {"id": 123}, "text": "/start"}}'
```

### OTP Not Sending
```bash
# Check if identifier (chat_id) is correct format
# Should be a number, not @username

# Verify bot can send DMs
python backend/telegram_bot.py test <CHAT_ID>

# Check Redis has the OTP stored
redis-cli GET "otp:<chat_id>"
```

### Rate Limiting Issues
```bash
# If user can't request OTP for 60s
# This is by design — check /api/auth/otp/request returns 429

# Clear rate limit manually
redis-cli DEL "otp_rate:<chat_id>"
```

---

## API Reference

### Endpoints

#### 1. Get Telegram Deep Link
```http
GET /api/auth/telegram/deeplink
```
Returns the Telegram bot link for the Flutter app to open.

**Response:**
```json
{
  "url": "https://t.me/ktm_bus_tracker_bot?start=auth",
  "bot": "ktm_bus_tracker_bot"
}
```

#### 2. Request OTP
```http
POST /api/auth/otp/request
Content-Type: application/json

{
  "username": "parent_user_123",
  "identifier": "123456789",
  "role": "parent"
}
```

**Response:**
```json
{
  "status": "otp_sent",
  "telegram_link": "https://t.me/ktm_bus_tracker_bot?start=auth",
  "hint": "Open the link, send /start to the bot..."
}
```

#### 3. Verify OTP
```http
POST /api/auth/otp/verify
Content-Type: application/json

{
  "username": "parent_user_123",
  "identifier": "123456789",
  "code": "123456",
  "role": "parent"
}
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer"
}
```

#### 4. Telegram Webhook
```http
POST /api/telegram/webhook
Content-Type: application/json
X-Telegram-Bot-Api-Secret-Token: your-secret

{
  "update_id": 123456789,
  "message": {
    "chat": {"id": 123456789},
    "text": "/start"
  }
}
```

---

## Advanced Configuration

### Switch to SMS Provider (Production)

1. **Aakash SMS (Nepal):**
   ```env
   OTP_PROVIDER=aakash
   AAKASH_API_KEY=your-api-key
   ```

2. **Sparrow SMS (Nepal):**
   ```env
   OTP_PROVIDER=sparrow
   SPARROW_TOKEN=your-api-token
   ```

3. **Update Flutter app:** Users enter phone number instead of chat_id

### Custom OTP Message

Edit [backend/services/otp_gateway.py](../services/otp_gateway.py):

```python
# Line ~170: TelegramMockSMSGateway.send_otp()
message = (
    f"🚌 Your OTP: *{code}*\n\n"
    f"Valid for 5 minutes."
)
```

### Security Best Practices

- ✅ Always use HTTPS for webhook
- ✅ Generate strong `JWT_SECRET` (32+ chars, random)
- ✅ Store bot token in secure env variable
- ✅ Rotate webhook secret monthly
- ✅ Monitor logs for failed attempts
- ✅ Implement rate limiting (already done: 1 OTP per 60s)
- ✅ Use secure Redis password
- ✅ Enable Redis SSL for production

---

## FAQ

**Q: Can I test without Telegram?**  
A: Yes! Set `OTP_PROVIDER=telegram` in dev mode, all OTPs print to console.

**Q: How long is the OTP valid?**  
A: 5 minutes (300 seconds). Defined in `backend/services/otp_gateway.py`.

**Q: Can I customize the OTP message?**  
A: Yes, edit `TelegramMockSMSGateway.send_otp()` in otp_gateway.py.

**Q: What if webhook registration fails?**  
A: Most common cause: PUBLIC_URL is not HTTPS or backend is unreachable. Check logs.

**Q: Can multiple users share one chat_id?**  
A: Not recommended. Each user should have a unique identifier (their chat_id or phone).

---

## Support

For issues, check:
1. Backend logs: `docker-compose logs backend`
2. Webhook status: `python telegram_bot.py info`
3. Bot is running: `python telegram_bot.py me`
4. Redis is accessible: `redis-cli ping`

---

## Next Steps

- [ ] Create Telegram bot with @BotFather
- [ ] Deploy backend with HTTPS
- [ ] Configure .env variables
- [ ] Register webhook: `python telegram_bot.py register`
- [ ] Test in Flutter app
- [ ] Deploy to production

---

*Last updated: 2024*  
*KTM Bus Tracker — OTP Authentication via Telegram*
