# 🚀 Quick Start — Free Hosting for Mobile Testing

## The Fastest Way (Pick One)

### ⭐ Best: Cloudflare Tunnel (Recommended)
Works anywhere, completely FREE, no credit card.

```bash
# 1. Signup (1 min)
# https://dash.cloudflare.com/sign-up

# 2. Install cloudflared
brew install cloudflare/cloudflare/cloudflared  # macOS
# Or: Linux / Windows instructions in FREE_HOSTING_GUIDE.md

# 3. Login
cloudflared tunnel login

# 4. Run setup script
chmod +x scripts/setup_cloudflare_tunnel.sh
./scripts/setup_cloudflare_tunnel.sh

# 5. Note the tunnel URL printed: https://bustrack-xxxxx.trycloudflare.com

# 6. Update Flutter config with that URL
# flutter/lib/core/config/app_config.dart → baseUrl

# 7. Start backend (Terminal 1)
docker-compose up -d

# 8. Start tunnel (Terminal 2) — KEEP RUNNING
cloudflared tunnel run bustrack

# 9. Start app (Terminal 3)
cd flutter && flutter run

# ✅ Done! Test on your phone!
```

**Total time: 10 minutes**

---

### 🏠 Easiest: Same WiFi (If testing at home)

```bash
# 1. Find your laptop IP
ifconfig | grep "inet 192"  # Example: 192.168.1.100

# 2. Update Flutter config
# flutter/lib/core/config/app_config.dart
# static const String baseUrl = 'http://192.168.1.100:8000';

# 3. Start backend
docker-compose up -d

# 4. On phone (same WiFi)
flutter run

# ✅ Done!
```

**Total time: 3 minutes**

---

### Fast: ngrok (If Cloudflare fails)

```bash
# 1. Install
brew install ngrok

# 2. Signup
# https://ngrok.com/signup

# 3. Authenticate
ngrok config add-authtoken <your_token>

# 4. Start tunnel
ngrok http 8000

# 5. Copy URL: https://abc123.ngrok.io

# 6. Update Flutter config with that URL

# 7. Start backend
docker-compose up -d

# 8. Start app
cd flutter && flutter run
```

**Total time: 5 minutes**

---

## Which Should I Choose?

| Scenario | Pick |
|----------|------|
| Testing with friend on **same WiFi** | Same WiFi |
| Testing on **road/outside** | Cloudflare Tunnel ⭐ |
| Quick **temporary test** | ngrok |
| **Production-ready** | Need paid server |

---

## Configuration After Hosting Setup

Once you have your tunnel/ngrok URL (e.g., `https://bustrack-xxxxx.trycloudflare.com`):

### 1. Update Flutter Config
```dart
// flutter/lib/core/config/app_config.dart
class AppConfig {
  static const String baseUrl = 'https://bustrack-xxxxx.trycloudflare.com';
  static const String telegramBotName = 'your_bot_name';
}
```

### 2. Update Environment
```bash
# Edit .env
PUBLIC_URL=https://bustrack-xxxxx.trycloudflare.com
```

### 3. Register Telegram Webhook
```bash
python backend/telegram_bot.py register
```

### 4. Verify
```bash
# Test from phone browser
https://bustrack-xxxxx.trycloudflare.com/health
```

---

## Workflow for Testing GPS on the Move

```
Terminal 1:
  $ docker-compose up -d

Terminal 2 (KEEP RUNNING):
  $ cloudflared tunnel run bustrack
  # Or: ngrok http 8000

Terminal 3:
  $ cd flutter && flutter run

Phone:
  • Install app
  • Login (Chat ID from @userinfobot)
  • Test GPS tracking while driving/moving
```

---

## Troubleshooting

### "Cannot connect from phone"
```bash
# 1. Check tunnel is running
ps aux | grep cloudflared

# 2. Check backend
curl https://your-tunnel-url/health

# 3. Check phone has internet (WiFi or LTE)
```

### "OTP not working"
```bash
# Check logs
docker-compose logs api | grep -i telegram

# Verify TELEGRAM_BOT_TOKEN in .env
```

### "Tunnel keeps disconnecting"
```bash
# Use screen/tmux to keep it running
tmux new-session -d -s tunnel "cloudflared tunnel run bustrack"

# Or create systemd service (see FREE_HOSTING_GUIDE.md)
```

---

## Cost Breakdown

| Option | Cost | Monthly |
|--------|------|---------|
| **Cloudflare Tunnel** | $0 | $0 |
| **ngrok Free** | $0 | $0 |
| **Same WiFi** | $0 | $0 |
| **Your laptop** | Already have | $0 |
| **Docker** | Free | $0 |
| **Total** | **$0** | **$0** |

✅ **Completely FREE!**

---

## Full Documentation

See: `FREE_HOSTING_GUIDE.md` for complete guide with all options, troubleshooting, and production setup.

---

## Next: Test GPS Tracking

Once hosting is setup:

1. ✅ Backend running with public URL
2. ✅ Telegram OTP working
3. ✅ Flutter app on phone
4. ✅ Get friend to drive around while you test tracking!

```
Test checklist:
  ☐ App starts
  ☐ Login works with Chat ID
  ☐ OTP arrives in Telegram
  ☐ GPS shows correct location
  ☐ Real-time updates while moving
  ☐ WebSocket connection stable
```

---

**Ready? Pick your hosting method and get started!** 🚀
