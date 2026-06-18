# Free Hosting Guide — Test KTM Bus Tracker on Mobile Devices

## Options Summary

| Option | Cost | Setup | Speed | Notes |
|--------|------|-------|-------|-------|
| **Same WiFi** | Free | 5 min | Fastest | Easiest, local only |
| **ngrok** | Free* | 5 min | Good | 2 req/sec limit, restarts URL |
| **Cloudflare Tunnel** | Free | 10 min | Good | Unlimited, stable URL ⭐ |
| **Render/Railway** | Free* | 15 min | Slower | 15 min auto-sleep, paid for uptime |
| **Your Own Server** | Cost | - | Varies | Not viable without budget |

**You chose: Cloudflare Tunnel** (Best free option!)

---

## 🏠 Option 1: Same WiFi (Easiest)

Perfect if testing with device on **same network** as your laptop.

### Setup (2 minutes)

1. **Find your laptop's IP:**
   ```bash
   # On Linux/Mac
   ifconfig | grep "inet 192"
   # Look for something like: 192.168.1.100
   
   # On Windows
   ipconfig
   ```

2. **Update Flutter config:**
   ```dart
   // flutter/lib/core/config/app_config.dart
   static const String baseUrl = 'http://192.168.1.100:8000';
   // Replace with YOUR IP from above
   ```

3. **Start backend (allow network access):**
   ```bash
   docker-compose up -d
   # OR if running locally:
   python -m uvicorn main:app --host 0.0.0.0 --port 8000
   ```

4. **On your phone (same WiFi):**
   - Open Flutter app
   - It will connect to `192.168.1.100:8000`
   - ✅ Done!

**Pros:** Fast, simple, no external service  
**Cons:** Only works on same WiFi

---

## 🌐 Option 2: Cloudflare Tunnel (Recommended) ⭐

Free, no credit card, unlimited usage, stable URL.

### Step 1: Install Cloudflare Tunnel

```bash
# Download tunnel CLI
# Option A: macOS
brew install cloudflare/cloudflare/cloudflared

# Option B: Linux
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Option C: Windows
# Download from: https://github.com/cloudflare/cloudflared/releases
# Extract and run cloudflared.exe
```

### Step 2: Authenticate

```bash
cloudflared tunnel login
# Opens browser to authenticate with Cloudflare
# (You need FREE Cloudflare account - sign up at https://dash.cloudflare.com)
```

### Step 3: Create Tunnel

```bash
# Create a new tunnel (one time)
cloudflared tunnel create bustrack

# This creates a stable URL like: bustrack-abc123.trycloudflare.com
```

### Step 4: Configure Tunnel

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: bustrack
credentials-file: /home/YOUR_USERNAME/.cloudflared/bustrack.json

ingress:
  - hostname: bustrack.your-domain.com
    service: http://localhost:8000
  - hostname: bustrack-test.trycloudflare.com
    service: http://localhost:8000
  - service: http://localhost:8000
```

Or simpler **without domain** (uses auto-generated URL):

```yaml
tunnel: bustrack
credentials-file: /home/YOUR_USERNAME/.cloudflared/bustrack.json

ingress:
  - service: http://localhost:8000
```

### Step 5: Start Backend

```bash
# Terminal 1: Start Docker services
cd ~/Documents/bustrack
docker-compose up -d

# Verify backend is running
curl http://localhost:8000/health
```

### Step 6: Start Tunnel

```bash
# Terminal 2: Start Cloudflare Tunnel
cloudflared tunnel run bustrack

# Output will show:
# | Tunnel running at: https://bustrack-abc123.trycloudflare.com
```

**Copy that URL!** → It's your public backend URL.

### Step 7: Update Flutter Config

```dart
// flutter/lib/core/config/app_config.dart
static const String baseUrl = 'https://bustrack-abc123.trycloudflare.com';
// Replace with YOUR tunnel URL from above
```

### Step 8: Update Environment Variables

```bash
# Edit .env
PUBLIC_URL=https://bustrack-abc123.trycloudflare.com
```

### Step 9: Register Telegram Webhook

```bash
# Terminal 3: Register with Telegram
python backend/telegram_bot.py register

# Verify
python backend/telegram_bot.py info
```

### Step 10: Test on Phone

```bash
# On your phone (any network)
flutter run
# OR build and install APK

# Test login:
# - Username: testuser
# - Chat ID: <your chat id>
# - Tap "Send OTP to Telegram"
# - ✅ Receive OTP instantly
```

**Pros:** Works from anywhere, stable URL, no credit card required  
**Cons:** URL changes if tunnel restarts (but can create permanent domain)

---

## 🔄 Option 3: ngrok (Free but Limited)

Free tier: 1 connection, rate limited

### Quick Setup

```bash
# 1. Install
# macOS
brew install ngrok

# Linux
wget https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.zip
unzip ngrok-v3-stable-linux-amd64.zip

# 2. Signup
# https://ngrok.com/signup

# 3. Connect
ngrok config add-authtoken <your_token>

# 4. Start tunnel
ngrok http 8000
# Shows: https://abc123.ngrok.io

# 5. Use that URL in Flutter config
# BASE_URL=https://abc123.ngrok.io
```

**Issues:** URL changes on restart, rate limiting on free tier  
**Better than:** Nothing if Cloudflare fails

---

## 🆚 Side-by-Side Comparison

### Same WiFi
```
Scenario: Testing with friend on same network at home
Cost: $0
Setup: 5 min
Speed: Fastest (local)
Pros: No external service, super fast
Cons: Limited to home WiFi only
```

### Cloudflare Tunnel
```
Scenario: Testing on road, multiple locations
Cost: $0 (free forever)
Setup: 15 min
Speed: Good (Cloudflare CDN)
Pros: Works anywhere, reliable, stable URL
Cons: Slight latency vs local
⭐ RECOMMENDED FOR YOUR USE CASE
```

### ngrok
```
Scenario: Quick temporary test
Cost: $0 (limited) or $8+/month (pro)
Setup: 5 min
Speed: Good
Pros: Super easy setup
Cons: Rate limited, URL changes, requires signup
```

---

## 📱 Testing Workflow

### With Cloudflare Tunnel:

**Terminal 1:**
```bash
cd ~/Documents/bustrack
docker-compose up -d
```

**Terminal 2:**
```bash
cloudflared tunnel run bustrack
# Keep this running!
```

**Terminal 3:**
```bash
cd flutter
flutter run
# Or: flutter build apk && adb install build/app/outputs/flutter-app-release.apk
```

**On Phone:**
- Install Flutter app
- Login with Chat ID (get from @userinfobot)
- Get OTP instantly
- ✅ Start GPS tracking!

### On the Road:
- While driving, test GPS tracking in real-time
- No need to rebuild/restart anything
- Just keep tunnel running!

---

## 🚀 Production-Ready Setup

If you want to keep this running 24/7:

### Option A: Cloudflare Tunnel (Best Free)
```bash
# Keep tunnel running in background
nohup cloudflared tunnel run bustrack > tunnel.log 2>&1 &

# OR use systemd service (Linux)
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

### Option B: Get Cheap VPS
- **Linode**: $5/month (but you said you're broke)
- **Oracle Always Free**: Actually free tier with limits
- **Repl.it/Railway**: Free tier with limitations

---

## 🆘 Troubleshooting

### "Connection refused"
```bash
# Backend not running
docker-compose up -d
curl http://localhost:8000/health
```

### "Tunnel not working"
```bash
# 1. Check tunnel is running
ps aux | grep cloudflared

# 2. Check backend
curl http://localhost:8000/health

# 3. Check from phone
curl https://bustrack-abc123.trycloudflare.com/health
```

### "OTP not sending"
```bash
# 1. Check backend logs
docker-compose logs api | grep -i "telegram\|otp"

# 2. Verify environment
docker-compose exec api env | grep TELEGRAM
```

### "Phone can't connect"
```bash
# 1. Try tunnel URL
curl https://bustrack-abc123.trycloudflare.com/health

# 2. Try local IP (if same WiFi)
curl http://192.168.1.100:8000/health

# 3. Check phone network
# Settings → WiFi → Connected?
```

---

## 💰 Completely Free Tier Comparison

| Service | Free | Setup | Stability | Limits |
|---------|------|-------|-----------|--------|
| **Cloudflare Tunnel** | ✅ Forever | 15 min | Excellent | None |
| **ngrok** | ⚠️ Limited | 5 min | Good | 40 req/min |
| **Localtunnel** | ✅ Yes | 5 min | Fair | - |
| **Docker locally** | ✅ Forever | 5 min | Perfect | WiFi only |
| **Render/Railway** | ⚠️ Limited | 15 min | Poor | 15 min sleep |

---

## My Recommendation

For **GPS testing on the move with friends**:

1. **Start with Cloudflare Tunnel** (best for your case)
2. Can test from anywhere
3. Stable URL for Telegram webhook
4. No credit card needed
5. Works indefinitely

---

## Quick Start (5 Steps)

```bash
# 1. Sign up (free, 2 min)
# https://dash.cloudflare.com/sign-up

# 2. Install cloudflared
brew install cloudflare/cloudflare/cloudflared  # macOS
# or download from: https://github.com/cloudflare/cloudflared/releases

# 3. Authenticate
cloudflared tunnel login

# 4. Create tunnel
cloudflared tunnel create bustrack

# 5. Start tunnel
cloudflared tunnel run bustrack

# Then:
# Terminal 2: docker-compose up -d
# Terminal 3: flutter run

# ✅ Done! Copy the tunnel URL to Flutter baseUrl
```

---

*Last Updated: 2024*  
*For testing GPS tracking on mobile devices - FREE!*
