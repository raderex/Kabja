# KTM Bus Tracker — Operations Runbook

Quick reference for deploying and troubleshooting the app.

---

## Pre-Deployment Checklist

- [ ] `.env` file created with all required variables (see `.env.example`)
- [ ] OSRM data preprocessed (see DEPLOYMENT.md STEP 2)
- [ ] Cloudflare tunnel created and tunnel ID obtained
- [ ] `cloudflared/config.yml` updated with tunnel ID
- [ ] Domain DNS A record points to VPS (for Let's Encrypt)
- [ ] `cloudflared/cert.pem` credentials file saved

---

## Deployment

```bash
# 1. SSH to VPS
ssh deploy@your-vps-ip

# 2. Clone and setup
git clone https://github.com/yourorg/ktm-bus-tracker.git
cd ktm-bus-tracker
cp .env.example .env
# Edit .env with your secrets

# 3. Start stack
docker compose up -d

# 4. Verify health
curl http://localhost:8000/health
# Should return: {"status": "ok", "redis": true, ...}
```

---

## Building Flutter APK

### Prerequisites
```bash
# Flutter must be installed at /home/raderex/flutter
/home/raderex/flutter/bin/flutter --version
```

### Build for Waydroid (local dev)
```bash
cd flutter

# Update config if needed (Waydroid IP should already be 192.168.240.1):
# flutter/config/env.waydroid.json

/home/raderex/flutter/bin/flutter build apk --debug --flavor parent \
  --dart-define-from-file=config/env.waydroid.json

# Install to Waydroid:
adb connect 192.168.240.112:5555   # check IP: ip neigh | grep waydroid
adb install build/app/outputs/flutter-apk/app-parent-debug.apk
```

### Build for Real Phone (Cloudflared tunnel)
```bash
cd flutter

# Step 1 — Update tunnel URL:
# Edit flutter/config/env.production.json:
#   "BASE_URL": "https://YOUR-TUNNEL.trycloudflare.com"
#   "WS_BASE":  "wss://YOUR-TUNNEL.trycloudflare.com"

# Step 2 — Build release APK:
/home/raderex/flutter/bin/flutter build apk --release --flavor parent \
  --dart-define-from-file=config/env.production.json

# Step 3 — Install to phone via USB:
adb install -r build/app/outputs/flutter-apk/app-parent-release.apk
```

### Build Driver APK (Waydroid)
```bash
cd flutter
/home/raderex/flutter/bin/flutter build apk --debug --flavor driver \
  --dart-define-from-file=config/env.waydroid.json
adb install build/app/outputs/flutter-apk/app-driver-debug.apk
```

### When Cloudflared Free Tunnel URL Changes
> ⚠️ Free trycloudflare.com URLs change on every restart. Named tunnels (Zero Trust) give permanent URLs.

```bash
# 1. Check new tunnel URL from logs:
cat tunnel.log | grep "Your quick Tunnel"
# OR: docker logs bustrack_cloudflared | grep trycloudflare

# 2. Update flutter/config/env.production.json with new URL

# 3. Rebuild and reinstall APK (steps above)

# 4. Update .env:
#    PUBLIC_URL=https://new-tunnel.trycloudflare.com
#    CORS_ORIGINS=https://new-tunnel.trycloudflare.com
# Then: docker compose restart api
```

### Run Flutter Analyze (before any build)
```bash
cd flutter
/home/raderex/flutter/bin/flutter analyze --no-pub
# Expected: No issues found! (0 issues)
```

---

## Seeding Test Data

```bash
# Seed test users + Redis assignments (idempotent — safe to run multiple times):
curl -X POST http://localhost:8000/api/admin/seed \
  -H "Content-Type: application/json"

# Verify seeded users can log in:
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"parent1","password":"password","role":"parent"}' | jq .

# Test driver login:
curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"driver1","password":"password","role":"driver"}' | jq .
```

> **Note**: In dev mode (`ENVIRONMENT=development`), driver assignments and parent route
> access are auto-seeded on every backend startup — no manual seed call needed.

---

## Post-Deployment Tests

### Test 1: Health Check
```bash
curl https://bustrack.yourdomain.com/health
# Should return 200 OK with JSON
```

### Test 2: Routes Endpoint
```bash
# Get JWT first
TOKEN=$(curl -s -X POST https://bustrack.yourdomain.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"parent1","password":"password","role":"parent"}' \
  | jq -r '.access_token')

# Get routes
curl -H "Authorization: Bearer $TOKEN" \
  https://bustrack.yourdomain.com/api/routes
# Should return array of 3 routes
```

### Test 3: WebSocket Connection
```bash
# Use websocat or similar tool
websocat "wss://bustrack.yourdomain.com/ws/route_1?token=$TOKEN"
# Should connect and stay open (ping every 20 seconds)
```

---

## Troubleshooting

### "Failed to load routes" on Parent App

**Symptoms**: App logs in but home screen shows error

**Cause**: PostgreSQL not initialized or unavailable

**Fix**:
```bash
# Check PostgreSQL status
docker ps | grep postgres

# Check logs
docker logs bustrack_postgres

# Manually initialize (if needed)
docker exec bustrack_api python3 -c \
  "import asyncio; from services.route_manager import init_route_schema; \
   asyncio.run(init_route_schema())"
```

**Fallback**: If PostgreSQL fails, app returns hardcoded FALLBACK_ROUTES (always works)

---

### "Connection failed" on Parent App (WebSocket)

**Symptoms**: Routes load, but bus position doesn't update

**Cause**: WebSocket not connecting or timing out

**Check**:
```bash
# Monitor WebSocket connections
docker logs bustrack_nginx | grep "WS"

# Check if Nginx is running
docker ps | grep nginx

# Verify Nginx config
docker exec bustrack_nginx nginx -t
```

**Fix**:
- Nginx timeout is 3600s (configured correctly)
- If error: restart nginx → `docker restart bustrack_nginx`

---

### "GPS not sending" (Driver App)

**Symptoms**: Driver logs in but tracking doesn't start

**Cause**: GPS permissions or location services disabled

**Fix**:
1. Check Android location permission: Settings → Permissions → Location
2. Ensure Waydroid/emulator has fake location enabled
3. Check logs: `adb logcat | grep geolocator`

---

### WebSocket Freezes After 60 Seconds

**Symptoms**: Bus position updates, then stops (reconnecting message)

**Cause**: Nginx timeout was 60s (should be 3600s)

**Verify**:
```bash
grep "proxy_read_timeout" nginx/nginx.conf
# Should show: proxy_read_timeout 3600s;
```

**Fix**: Ensure nginx.conf has the timeout settings, restart:
```bash
docker restart bustrack_nginx
```

---

### PostgreSQL Startup Slow

**Symptoms**: App hangs for 30+ seconds on startup

**Normal**: PostgreSQL takes 10-20s to initialize on first run

**Monitor**:
```bash
docker logs bustrack_postgres | tail -20
```

---

## Monitoring

### Real-Time Logs
```bash
# All services
docker compose logs -f

# Specific service
docker logs -f bustrack_api
docker logs -f bustrack_nginx
```

### Health Endpoint
```bash
watch -n 5 'curl -s http://localhost:8000/health | jq .'
# Shows: redis status, version, active WS clients
```

### Active WebSocket Clients
```bash
curl -s http://localhost:8000/health | jq '.ws_clients'
# Example output: {"route_1": 2, "route_2": 1, "route_3": 0}
```

---

## Scaling

### Add More Buses
1. Seed new drivers in Redis:
   ```bash
   POST /api/admin/seed
   ```
2. Assign to routes and buses via admin panel (TBD)

### High Concurrent Parents
- Current: 100+ concurrent connections tested
- Limit: Nginx `worker_connections: 4096`
- If needed: increase in nginx.conf

---

## Maintenance

### Restart Services
```bash
# All
docker compose restart

# Specific
docker restart bustrack_api
docker restart bustrack_nginx
```

### View Database
```bash
docker exec bustrack_postgres psql -U bustrack -d bustrack

# Example queries
SELECT * FROM routes;
SELECT COUNT(*) FROM trip_history;
```

### Clear Redis Cache
```bash
docker exec bustrack_redis redis-cli -a $REDIS_PASSWORD FLUSHALL
```

---

## Emergency Procedures

### Complete Reset (DANGER: erases all data)
```bash
docker compose down -v
rm -rf postgres_data/
docker compose up -d
```

### Rollback to Previous Version
```bash
git checkout <commit-hash>
docker compose down
docker build -t bustrack_api ./backend
docker compose up -d
```

---

## References

- Architecture: See `ARCHITECTURE.md`
- Deployment: See `DEPLOYMENT.md`
- API Docs: `https://bustrack.yourdomain.com/api/docs`
