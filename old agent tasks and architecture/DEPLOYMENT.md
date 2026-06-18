# KTM School Bus Tracker — VPS Deployment Guide
# ══════════════════════════════════════════════
# Target: Ubuntu 22.04 LTS VPS (4 vCPU / 8GB RAM recommended)
# OSRM MLD preprocessing needs ~3GB RAM; use a larger droplet for prep only.

## ─────────────────────────────────────────────
## STEP 0 — Server bootstrap (run as root)
## ─────────────────────────────────────────────

```bash
apt update && apt upgrade -y
apt install -y docker.io docker-compose-plugin curl git ufw

# Firewall — only expose SSH, HTTP, HTTPS
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Add deploy user
adduser deploy
usermod -aG docker deploy
su - deploy
```

## ─────────────────────────────────────────────
## STEP 1 — Clone & configure
## ─────────────────────────────────────────────

```bash
git clone https://github.com/yourorg/ktm-bus-tracker.git
cd ktm-bus-tracker

# Create .env (never commit this)
cat > .env << 'EOF'
REDIS_PASSWORD=change_me_strong_password_here
JWT_SECRET=change_me_256bit_random_secret_here
ENVIRONMENT=production
CORS_ORIGINS=https://bustrack.yourdomain.com
EOF

chmod 600 .env
```

## ─────────────────────────────────────────────
## STEP 2 — OSRM data preparation
## (one-time, takes 5–15 min depending on VPS)
## ─────────────────────────────────────────────

```bash
mkdir -p osrm_data
cd osrm_data

# Download Nepal OSM data from Geofabrik
wget https://download.geofabrik.de/asia/nepal-latest.osm.pbf

cd ..

# Extract road network (car profile)
docker run --rm -t -v $(pwd)/osrm_data:/data \
  ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-extract -p /opt/car.lua /data/nepal-latest.osm.pbf

# Partition graph (MLD algorithm — faster queries than CH)
docker run --rm -t -v $(pwd)/osrm_data:/data \
  ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-partition /data/nepal-latest.osrm

# Customize weights
docker run --rm -t -v $(pwd)/osrm_data:/data \
  ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-customize /data/nepal-latest.osrm

# Verify OSRM works (should return JSON with routes)
docker run --rm -p 5001:5000 -v $(pwd)/osrm_data:/data \
  ghcr.io/project-osrm/osrm-backend:v5.27.1 \
  osrm-routed --algorithm mld /data/nepal-latest.osrm &

curl "http://localhost:5001/route/v1/driving/85.324,27.717;85.340,27.713?overview=false"
# Should return: {"code":"Ok","routes":[...]}

docker stop $(docker ps -q --filter ancestor=ghcr.io/project-osrm/osrm-backend:v5.27.1)
```

## ─────────────────────────────────────────────
## STEP 3 — SSL Certificate (Let's Encrypt)
## ─────────────────────────────────────────────

```bash
# Point your domain A record to this VPS IP first, then:

# Start Nginx in HTTP-only mode to pass ACME challenge
docker compose up -d nginx

# Issue certificate
docker compose run --rm certbot certonly \
  --webroot -w /var/www/certbot \
  --email your@email.com \
  --agree-tos \
  --no-eff-email \
  -d bustrack.yourdomain.com

# Update nginx/conf.d/bustrack.conf — replace yourdomain.com with your domain
sed -i 's/bustrack.yourdomain.com/bustrack.ACTUALDOMAINHERE.com/g' \
  nginx/conf.d/bustrack.conf

docker compose restart nginx
```

## ─────────────────────────────────────────────
## STEP 4 — Launch the full stack
## ─────────────────────────────────────────────

```bash
docker compose up -d

# Verify all services are healthy
docker compose ps

# Check API health
curl https://bustrack.yourdomain.com/health

# Test GPS endpoint (should return 401 without token)
curl -X POST https://bustrack.yourdomain.com/api/gps-update \
  -H "Content-Type: application/json" \
  -d '{"bus_id":"bus_1","route_id":"route_1","lat":27.717,"lng":85.324}'

# Tail logs
docker compose logs -f api
```

## ─────────────────────────────────────────────
## STEP 5 — Seed initial data
## ─────────────────────────────────────────────

```bash
# Get a driver token
TOKEN=$(curl -s -X POST https://bustrack.yourdomain.com/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"driver1","password":"test","role":"driver"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test GPS ping
curl -X POST https://bustrack.yourdomain.com/api/gps-update \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bus_id":"BUS_001","route_id":"route_1","lat":27.717,"lng":85.324,"speed":25.0,"bearing":45.0,"accuracy":5.0}'

# Test WebSocket (install wscat: npm i -g wscat)
PARENT_TOKEN=$(curl -s -X POST https://bustrack.yourdomain.com/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"parent1","password":"test","role":"parent"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

wscat -c "wss://bustrack.yourdomain.com/ws/route_1?token=$PARENT_TOKEN"
# Should receive: {"type":"position","bus_id":"BUS_001",...}
```

## ─────────────────────────────────────────────
## STEP 6 — App Store submission checklist
## ─────────────────────────────────────────────

### Apple App Store

[ ] Privacy Policy hosted at: https://bustrack.yourdomain.com/privacy
[ ] Support URL hosted at:    https://bustrack.yourdomain.com/support
[ ] Background Location entitlement added in Xcode
[ ] NSLocationAlwaysAndWhenInUseUsageDescription set in Info.plist
[ ] UIBackgroundModes includes "location" in Info.plist
[ ] App tested on real device (background location doesn't work in simulator)
[ ] Two separate App Store listings: "KTM School Bus" (Parent) and "KTM Bus Driver" (Driver)
    OR one app with role selection (simpler for small school)
[ ] App Review notes prepared:
    "This is a school bus tracking application for schools in Kathmandu, Nepal.
     The Driver flavor requires background location permission to continuously
     transmit the bus position to parents via our secure WebSocket server.
     The Parent flavor never requests background location."
[ ] Screenshots for 6.5" iPhone and 12.9" iPad prepared
[ ] App icon 1024×1024 PNG (no alpha) prepared

### Google Play Store

[ ] Privacy Policy URL entered in Play Console
[ ] Prominent disclosure implemented (shown before requesting background location)
[ ] Data safety form completed:
    - Location: "Collected, not shared with third parties, used for app functionality"
    - Background location: "Yes, Driver role only"
[ ] Driver app published to "Closed Testing" track first
[ ] Background location policy declaration submitted:
    https://support.google.com/googleplay/android-developer/answer/9799150

## ─────────────────────────────────────────────
## STEP 7 — Monitoring & maintenance
## ─────────────────────────────────────────────

```bash
# Auto-restart on reboot
sudo systemctl enable docker
# Add to crontab: docker compose restart on reboot
(crontab -l 2>/dev/null; echo "@reboot cd /home/deploy/ktm-bus-tracker && docker compose up -d") | crontab -

# Update Nepal OSM data monthly (Geofabrik updates weekly)
# Re-run OSRM preprocessing steps from Step 2 and restart the osrm container

# Monitor Redis memory
docker exec bustrack_redis redis-cli -a $REDIS_PASSWORD info memory

# Check active WebSocket connections
docker compose logs api | grep "WS connected" | wc -l
```

## ─────────────────────────────────────────────
## Architecture notes (Traccar inspiration)
## ─────────────────────────────────────────────

# This system adapts key concepts from Traccar (github.com/traccar/traccar):
#
# 1. Device session model → our Redis bus:{id}:loc hash (TTL-based "online" detection)
# 2. Protocol handler separation → our /api/gps-update endpoint isolates ingestion
# 3. Connection manager → our WebSocket ConnectionManager with per-route rooms
# 4. Position model → our GPSPing Pydantic model mirrors Traccar's Position entity
#
# Key differences from Traccar:
# • Python/FastAPI instead of Java — faster iteration, async-native
# • Redis instead of H2/MySQL for hot state — sub-millisecond reads
# • OSRM instead of GraphHopper — Nepal data works better with OSRM
# • Flutter instead of web-only — single codebase for iOS + Android
# • No-Google tile stack — OpenFreeMap + Protomaps removes all API keys
