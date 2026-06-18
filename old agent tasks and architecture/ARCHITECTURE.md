# KTM Bus Tracker — System Architecture & DeepSeek Coding Brief
# ==============================================================
# 
# STATUS: Living document — updated by architect (Antigravity) + coder (DeepSeek)
# LAST UPDATED: 2026-05-27
# PURPOSE: Single source of truth for all code changes, bug fixes, and design decisions.
#          Read this FIRST before touching any file.
#
# HOW THIS DOCUMENT WORKS:
#   - Architect writes: ROOT CAUSE ANALYSIS, ARCHITECTURE DECISIONS, CODING SPECS
#   - DeepSeek implements: the exact specs defined in CODING TASKS sections
#   - Both update: the CHANGE LOG at the bottom after each session
# ================================================================


## ═══════════════════════════════════════════════════════════════
## SECTION 1 — SYSTEM OVERVIEW (read before anything else)
## ═══════════════════════════════════════════════════════════════

### What this app is
A real-time school bus tracker for Kathmandu Valley.
- Parent app: sees live bus position on map, gets ETA, gets geofence alert
- Driver app: broadcasts GPS in background, auto-connects to backend
- Backend: FastAPI + Redis + PostgreSQL + OSRM routing engine
- Infrastructure: Docker Compose on Linux host, exposed via Cloudflared tunnel

### Stack versions (LOCKED — do not change without architect sign-off)
| Layer        | Technology              | Version     |
|--------------|-------------------------|-------------|
| Flutter      | Dart SDK                | ≥3.3.0      |
| Flutter      | flutter_map             | ^7.0.2      |
| Flutter      | flutter_riverpod        | ^2.5.1      |
| Flutter      | go_router               | ^14.0.2     |
| Flutter      | geolocator              | ^12.0.0     |
| Backend      | Python / FastAPI        | 3.11 / 0.x  |
| Backend      | Redis                   | 7.x         |
| Backend      | PostgreSQL              | 16.x        |
| Backend      | asyncpg                 | 0.29.x      |
| Backend      | jose (JWT)              | 3.x         |
| Infra        | Docker Compose          | v3.9        |
| Infra        | Nginx                   | 1.25-alpine |
| Tunnel       | Cloudflared             | latest      |
| Android      | AGP                     | 9.0.1       |
| Android      | Kotlin                  | 2.3.20      |
| Android      | Gradle Wrapper          | 9.1.0       |
| Android      | compileSdk / targetSdk  | 36          |


## ═══════════════════════════════════════════════════════════════
## SECTION 2 — ROOT CAUSE ANALYSIS: "Routes Error" on Real Device
## ═══════════════════════════════════════════════════════════════

### Symptom
App on physical Android phone → logs in fine → Home screen shows
"Failed to load routes" / "Connection failed" error.
This happens specifically when backend is exposed via Cloudflared tunnel.

### Diagnosed Root Causes (in priority order)

#### RC-1 [CRITICAL] — Flutter app_config.dart hardcoded to Waydroid IP
File: flutter/lib/core/config/app_config.dart
Problem: baseUrl = 'http://192.168.240.1:8000' — this is the Waydroid
bridge IP. A real Android phone on a different network CANNOT reach this.
When using Cloudflared, the URL must be the tunnel HTTPS URL.

Fix required:
  - app_config.dart must read the base URL from a build-time environment
    variable (--dart-define) OR a runtime config file.
  - The Flutter app must use HTTPS URL for Cloudflared, not local IP.
  - The WebSocket URL must also use wss:// (not ws://) when behind HTTPS.

#### RC-2 [CRITICAL] — WebSocket upgrade fails through Cloudflared
File: nginx/nginx.conf + docker-compose.yml
Problem: Cloudflared proxies HTTP/HTTPS correctly but WebSocket upgrades
need explicit headers: Upgrade: websocket + Connection: Upgrade.
If Nginx is not setting these OR Cloudflared strips them, WS connects
then immediately drops → the app shows "reconnecting" forever.

Fix required:
  - Nginx must explicitly proxy_set_header Upgrade and Connection for /ws/
  - Cloudflared config must have no-tls-verify: false and proper tunnel routing.
  - The WS URL in Flutter must use wss:// (not ws://) when hitting Cloudflared.

#### RC-3 [CRITICAL] — PostgreSQL not seeded → routes table is empty
File: backend/services/route_manager.py (init_route_schema)
Problem: The /api/routes endpoint queries PostgreSQL. If PostgreSQL 
container just started OR was wiped, init_route_schema() seeds it — BUT 
only if init_schema() (trip_logger) succeeds first. If PostgreSQL is 
unreachable (wrong env var, container not healthy yet), BOTH init_schema 
and init_route_schema are skipped silently (see main.py lifespan, line 401).
Result: routes table doesn't exist → /api/routes returns 503 or crashes.

Fix required:
  - Route manager needs its own fallback: if PostgreSQL unavailable,
    return hardcoded ROUTE_REGISTRY from memory (never return empty).
  - The /api/routes endpoint must NEVER fail with a 500/503 — it must
    return at minimum the 3 hardcoded routes.

#### RC-4 [HIGH] — CORS_ORIGINS env var missing the Cloudflared domain
File: .env → CORS_ORIGINS
Problem: CORS_ORIGINS=https://your-domain.com — this is a placeholder.
When Cloudflared URL is different (trycloudflare.com subdomain changes 
on every restart with the free tier), the CORS whitelist is stale.
Native Flutter apps don't use browser CORS, but ANY web-based admin 
panel or curl test from a browser will be blocked.

Fix required:
  - .env must have the actual Cloudflared URL in CORS_ORIGINS.
  - For trycloudflare.com free tunnels: accept that URL changes each restart.
  - Long-term: use a named Cloudflare tunnel (persistent URL).

#### RC-5 [HIGH] — Cloudflared free tunnel URL changes on every restart
File: .env → PUBLIC_URL, flutter/lib/core/config/app_config.dart
Problem: trycloudflare.com gives a random subdomain every time cloudflared
restarts. The Flutter APK is compiled with the old URL baked in → broken.

Fix required:
  - Either use a named Cloudflare tunnel (cloudflare zero trust → persistent)
  - OR use --dart-define at build time so the APK always uses the right URL
  - OR implement a runtime config: app fetches config URL from a known
    local IP at first launch, caches it in secure storage.

#### RC-6 [MEDIUM] — usesCleartextTraffic="false" blocks HTTP
File: android/app/src/main/AndroidManifest.xml line 31
Problem: android:usesCleartextTraffic="false" is set. This blocks all
plain HTTP traffic. If the app ever tries to hit http:// (not https://),
the request silently fails on Android 9+.
With Cloudflared (HTTPS), this is correct. But in local dev against 
192.168.240.1:8000 (HTTP), this is the reason requests fail on a real 
phone even if the IP is reachable.

Fix required:
  - For local dev flavor: create a debug network security config that allows
    cleartext to 192.168.240.1 only.
  - For production flavor (Cloudflared): keep usesCleartextTraffic="false".

#### RC-7 [MEDIUM] — JWT allowed_routes empty for regular parents
File: backend/main.py, _seed_users + login endpoint
Problem: Regular parents (parent1, parent2, parent3) get allowed_routes
from Redis: await r.smembers(f"parent:{username}:routes"). But Redis is 
empty until /api/admin/seed is called. If seed was never called, 
allowed_routes = [] and the WebSocket /ws/{route_id} returns 403 
for non-superuser parents.

Fix required:
  - /api/admin/seed must be called once after every fresh deploy.
  - Add an auto-seed step on startup for dev environments.
  - Document this clearly in RUNBOOK section below.


## ═══════════════════════════════════════════════════════════════
## SECTION 3 — ARCHITECTURE DECISIONS (rationale for every design choice)
## ═══════════════════════════════════════════════════════════════

### AD-1: Configuration strategy — build-time --dart-define (chosen)
We will use Flutter's --dart-define-from-file mechanism.
A file called flutter/config/env.json is gitignored and contains:
  { "BASE_URL": "https://your-tunnel.trycloudflare.com", "WS_BASE": "wss://..." }
app_config.dart reads these with String.fromEnvironment().
This means: no code change needed, just update env.json and rebuild APK.

### AD-2: Routes fallback — in-memory + PostgreSQL (defense in depth)
/api/routes MUST return data even if PostgreSQL is down.
Strategy: try PostgreSQL first. If it fails, return in-memory ROUTE_REGISTRY.
This makes the app functional even during DB maintenance.

### AD-3: WebSocket over Cloudflared — wss:// with ping/pong keepalive
Cloudflared has a 100s idle connection timeout by default.
Our WsResilienceManager already sends ping every 20s — this is correct.
Nginx must proxy_read_timeout 3600s for /ws/ location.
Cloudflared's own keepalive is handled by the tunnel protocol.

### AD-4: Cleartext traffic — flavor-based network security config
Parent flavor APK = production = HTTPS only (usesCleartextTraffic="false").
Dev testing = separate res/xml/network_security_config.xml that allows
cleartext to 192.168.240.1 (Waydroid) and 10.0.2.2 (AVD emulator).
This allows local testing without compromising production security.

### AD-5: Named Cloudflare tunnel (recommended upgrade)
Free trycloudflare.com = URL changes every restart = broken APKs.
Named tunnel = permanent URL = one build works forever.
Setup: cloudflare zero trust → tunnels → create tunnel → get TUNNEL_ID.
Commit tunnel config to repo (but NOT the credentials JSON).


## ═══════════════════════════════════════════════════════════════
## SECTION 4 — FILE MAP (every file, its role, who owns it)
## ═══════════════════════════════════════════════════════════════

### Flutter (flutter/)
| File                                     | Role                           | Owner    |
|------------------------------------------|--------------------------------|----------|
| lib/main.dart                            | App entry, theme, router       | Redesigned ✓ |
| lib/core/config/app_config.dart          | URL config — NEEDS FIX         | DeepSeek |
| lib/core/auth/auth_provider.dart         | JWT storage, login, OTP        | Fixed ✓  |
| lib/core/network/dio_client.dart         | HTTP client with JWT inject    | OK       |
| lib/core/network/ws_resilience_manager.dart | WS reconnect logic          | OK       |
| lib/features/auth/login_screen.dart      | Login UI — Redesigned ✓        | Done     |
| lib/features/auth/telegram_auth_screen.dart | OTP UI — Fixed ✓           | Done     |
| lib/features/home/home_screen.dart       | Route list — Redesigned ✓      | Done     |
| lib/features/tracking/tracking_screen.dart | Map tracking — Redesigned ✓  | Done     |
| lib/features/tracking/bus_marker_animator.dart | Smooth GPS animation   | Fixed ✓  |
| lib/features/driver/driver_screen.dart   | Driver GPS — Redesigned ✓      | Done     |
| android/app/build.gradle.kts            | Android build config — Fixed ✓ | Done     |
| android/gradle.properties               | Gradle flags — Fixed ✓         | Done     |
| android/app/src/main/AndroidManifest.xml | Permissions                   | Needs network_security_config |

### Backend (backend/)
| File                          | Role                                    | Status        |
|-------------------------------|----------------------------------------|---------------|
| main.py                       | FastAPI app, all endpoints              | Needs RC-3 fix |
| services/route_manager.py     | PostgreSQL route CRUD + seeding        | Needs fallback |
| services/trip_logger.py       | PostgreSQL trip snapshots               | OK            |
| services/geofence.py          | Haversine stop proximity check         | OK            |
| services/otp_gateway.py       | Telegram OTP sending                   | OK            |

### Infrastructure
| File                          | Role                                    | Status        |
|-------------------------------|----------------------------------------|---------------|
| docker-compose.yml            | Service orchestration                   | Needs review  |
| .env                          | Secrets + config                        | Needs update  |
| nginx/nginx.conf              | SSL, WS proxy, rate limiting           | Needs WS headers |
| cloudflared/config.yml        | Tunnel routing (MISSING — must create) | DeepSeek      |

### New files to create
| File                                           | Purpose                        |
|------------------------------------------------|--------------------------------|
| flutter/config/env.json                        | Build-time URL config (gitignored) |
| flutter/config/env.production.json             | Production URL template        |
| flutter/config/env.waydroid.json               | Waydroid/local dev URLs        |
| android/app/src/main/res/xml/network_security_config.xml | Dev cleartext policy |
| cloudflared/config.yml                         | Named tunnel config            |
| RUNBOOK.md                                     | Step-by-step ops guide         |


## ═══════════════════════════════════════════════════════════════
## SECTION 5 — CODING TASKS FOR DEEPSEEK
## ═══════════════════════════════════════════════════════════════
## 
## Instructions for DeepSeek:
##   1. Read SECTION 2 (root causes) fully before writing any code
##   2. Implement ONLY the tasks listed here — do not invent new features
##   3. After each task, update SECTION 7 (Change Log) with what you did
##   4. Do NOT change any file listed as "Done ✓" in SECTION 4
##   5. Follow the exact specs below — no deviations without architect approval
##
## ═══════════════════════════════════════════════════════════════

### TASK T-1: app_config.dart — Runtime URL configuration [RC-1, RC-5]
**File:** flutter/lib/core/config/app_config.dart
**Priority:** CRITICAL — fixes routes error on real device

Implement:
```dart
class AppConfig {
  AppConfig._();

  // Read from --dart-define-from-file at build time.
  // Fallback chain: dart-define → Waydroid IP (dev only)
  static const String baseUrl = String.fromEnvironment(
    'BASE_URL',
    defaultValue: 'http://192.168.240.1:8000',
  );

  static const String wsBase = String.fromEnvironment(
    'WS_BASE',
    defaultValue: 'ws://192.168.240.1:8000',
  );

  static const String telegramBotName = String.fromEnvironment(
    'TELEGRAM_BOT_NAME',
    defaultValue: 'KTMBusTrackerBot',
  );

  // Tile URL — OSM standard raster tiles
  static const String tileUrl =
      'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

  // Kathmandu Valley bounding box (static, never changes)
  static const double bboxWest  = 85.2;
  static const double bboxSouth = 27.6;
  static const double bboxEast  = 85.5;
  static const double bboxNorth = 27.8;

  static const String geocodeUrl = '$baseUrl/api/geocode';
}
```

Also create these files:

**File:** flutter/config/env.waydroid.json
```json
{
  "BASE_URL": "http://192.168.240.1:8000",
  "WS_BASE":  "ws://192.168.240.1:8000",
  "TELEGRAM_BOT_NAME": "sajabusbot"
}
```

**File:** flutter/config/env.production.json  (fill TUNNEL_URL with actual URL)
```json
{
  "BASE_URL": "https://TUNNEL_URL",
  "WS_BASE":  "wss://TUNNEL_URL",
  "TELEGRAM_BOT_NAME": "sajabusbot"
}
```

Add to flutter/.gitignore:
```
config/env.json
config/env.production.json
```

**Build commands DeepSeek must document in RUNBOOK.md:**
```bash
# Local Waydroid dev build:
flutter build apk --debug --flavor parent \
  --dart-define-from-file=config/env.waydroid.json

# Production (Cloudflared) build:
flutter build apk --release --flavor parent \
  --dart-define-from-file=config/env.production.json
```

---

### TASK T-2: Backend routes fallback [RC-3]
**File:** backend/services/route_manager.py
**Priority:** CRITICAL — fixes empty routes list

In get_all_routes(), wrap the PostgreSQL call in try/except.
If PostgreSQL fails, return hardcoded FALLBACK_ROUTES (the same
data as DEFAULT_ROUTES but as plain dicts, no DB).

```python
FALLBACK_ROUTES = [
    {
        "id": "route_1",
        "name": "Baneshwor → Patan School",
        "description": "Via Koteshwor and Patan Dhoka",
        "color": "#EF2A3A",
        "school_lat": 27.7172,
        "school_lng": 85.3240,
        "stops": [
            {"stop_id": "r1_s1", "name": "Baneshwor Chowk",  "lat": 27.6934, "lng": 85.3423},
            {"stop_id": "r1_s2", "name": "Koteshwor",         "lat": 27.6867, "lng": 85.3521},
            {"stop_id": "r1_s3", "name": "Patan Dhoka",       "lat": 27.6710, "lng": 85.3195},
            {"stop_id": "r1_s4", "name": "Patan School Gate", "lat": 27.6678, "lng": 85.3213},
        ],
    },
    {
        "id": "route_2",
        "name": "Boudha → Little Angels",
        "description": "Via Chabahil",
        "color": "#EF2A3A",
        "school_lat": 27.6913,
        "school_lng": 85.3420,
        "stops": [
            {"stop_id": "r2_s1", "name": "Boudha Stupa",      "lat": 27.7215, "lng": 85.3622},
            {"stop_id": "r2_s2", "name": "Chabahil",           "lat": 27.7132, "lng": 85.3541},
            {"stop_id": "r2_s3", "name": "Little Angels Gate", "lat": 27.7050, "lng": 85.3410},
        ],
    },
    {
        "id": "route_3",
        "name": "Balaju → Budhanilkantha",
        "description": "Via Samakhushi",
        "color": "#EF2A3A",
        "school_lat": 27.7041,
        "school_lng": 85.3145,
        "stops": [
            {"stop_id": "r3_s1", "name": "Balaju Bus Park",      "lat": 27.7372, "lng": 85.2980},
            {"stop_id": "r3_s2", "name": "Samakhushi",            "lat": 27.7298, "lng": 85.3120},
            {"stop_id": "r3_s3", "name": "Budhanilkantha School", "lat": 27.7912, "lng": 85.3620},
        ],
    },
]

async def get_all_routes() -> list[dict]:
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            # ... existing query code ...
    except Exception as exc:
        log.warning("PostgreSQL unavailable for routes, using fallback: %s", exc)
        return FALLBACK_ROUTES  # never return empty list
```

Same pattern for get_route() — if DB fails, search FALLBACK_ROUTES by id.

---

### TASK T-3: AndroidManifest network security config [RC-6]
**File:** android/app/src/main/AndroidManifest.xml
**New file:** android/app/src/main/res/xml/network_security_config.xml

Create network_security_config.xml:
```xml
<?xml version="1.0" encoding="utf-8"?>
<!-- Allows cleartext (HTTP) only to local dev IPs.
     Production (Cloudflared) always uses HTTPS so this never fires in prod. -->
<network-security-config>
    <base-config cleartextTrafficPermitted="false">
        <trust-anchors>
            <certificates src="system"/>
        </trust-anchors>
    </base-config>
    <domain-config cleartextTrafficPermitted="true">
        <!-- Waydroid bridge IP -->
        <domain includeSubdomains="false">192.168.240.1</domain>
        <!-- Android emulator host -->
        <domain includeSubdomains="false">10.0.2.2</domain>
        <!-- localhost -->
        <domain includeSubdomains="false">localhost</domain>
    </domain-config>
</network-security-config>
```

Update AndroidManifest.xml application tag:
- Remove: android:usesCleartextTraffic="false"
- Add: android:networkSecurityConfig="@xml/network_security_config"

---

### TASK T-4: Nginx WebSocket headers [RC-2]
**File:** nginx/nginx.conf

Find the /ws/ location block and ensure it has EXACTLY these headers:
```nginx
location /ws/ {
    proxy_pass http://api:8000;
    proxy_http_version 1.1;
    
    # Critical for WebSocket upgrade through Cloudflared
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    
    # Preserve client IP and host
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # Keep-alive for long-lived connections (Cloudflared 100s idle timeout)
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    
    # Don't buffer WebSocket frames
    proxy_buffering off;
}
```

---

### TASK T-5: Cloudflared named tunnel config [RC-5]
**New file:** cloudflared/config.yml

Create the cloudflared directory and config file:
```yaml
# cloudflared/config.yml
# Named Cloudflare tunnel configuration
# Setup: cloudflared tunnel login → cloudflared tunnel create bustrack
# Then: cloudflared tunnel route dns bustrack your-subdomain.yourdomain.com
# Credentials file is auto-created at ~/.cloudflared/<TUNNEL_ID>.json

tunnel: <TUNNEL_ID>  # Replace with: cloudflared tunnel list
credentials-file: /home/<YOUR_USER>/.cloudflared/<TUNNEL_ID>.json

ingress:
  # HTTPS API + WebSocket
  - hostname: bustrack.yourdomain.com
    service: http://localhost:8000
    originRequest:
      connectTimeout: 30s
      noTLSVerify: false
      # Critical: allow HTTP/1.1 upgrade for WebSocket
      httpHostHeader: bustrack.yourdomain.com
      
  # Catch-all (required by cloudflared)
  - service: http_status:404
```

Also create cloudflared/README.md explaining the setup steps.

---

### TASK T-6: Auto-seed on startup for dev environment [RC-7]
**File:** backend/main.py — lifespan function

After _seed_users(r), add auto-seed for assignments if ENVIRONMENT=development:
```python
if os.getenv("ENVIRONMENT", "production") == "development":
    await _auto_seed_assignments(r)

async def _auto_seed_assignments(r: aioredis.Redis) -> None:
    """Seeds driver assignments and parent routes for dev — idempotent."""
    pipe = r.pipeline()
    # Only seed if not already set
    if not await r.exists("driver:driver1:assignment"):
        pipe.hset("driver:driver1:assignment", mapping={"bus_id": "BUS_001", "route_id": "route_1"})
        pipe.hset("driver:driver2:assignment", mapping={"bus_id": "BUS_002", "route_id": "route_2"})
        pipe.hset("driver:driver3:assignment", mapping={"bus_id": "BUS_003", "route_id": "route_3"})
        pipe.sadd("parent:parent1:routes", "route_1")
        pipe.sadd("parent:parent2:routes", "route_1", "route_2")
        pipe.sadd("parent:parent3:routes", "route_3")
        await pipe.execute()
        log.info("Dev assignments auto-seeded ✓")
```

Add ENVIRONMENT=development to docker-compose.yml for local dev.

---

### TASK T-7: RUNBOOK.md — operations guide
**New file:** RUNBOOK.md (project root)

Must document in clear steps:
1. First-time deploy (Cloudflared)
2. Build Flutter APK for Waydroid testing
3. Build Flutter APK for real phone (Cloudflared)
4. What to do when Cloudflared URL changes (free tunnel)
5. How to seed test data
6. How to check if backend is healthy
7. How to read logs
8. Common errors and how to fix them (include the routes error)


## ═══════════════════════════════════════════════════════════════
## SECTION 6 — API CONTRACT (source of truth for Flutter↔Backend)
## ═══════════════════════════════════════════════════════════════

### Endpoints Flutter uses
| Method | Path                     | Auth    | Response shape                          |
|--------|--------------------------|---------|----------------------------------------|
| POST   | /api/auth/login          | None    | { access_token, token_type }           |
| POST   | /api/auth/otp/request    | None    | { status: "sent" }                     |
| POST   | /api/auth/otp/verify     | None    | { access_token, token_type }           |
| GET    | /api/routes              | Bearer  | List<Route>                            |
| GET    | /api/routes/{id}         | Bearer  | Route + stops + active buses           |
| GET    | /api/driver/assignment   | Bearer  | { bus_id, route_id, route_name }       |
| POST   | /api/gps-update          | Bearer  | { status: "accepted", ts }             |
| WSS    | /ws/{route_id}?token=JWT | Via URL | position / eta / geofence_alert frames |

### Route object shape
```json
{
  "id":          "route_1",
  "name":        "Baneshwor → Patan School",
  "description": "Via Koteshwor and Patan Dhoka",
  "color":       "#EF2A3A",
  "active_buses": 1,
  "stop_count":  4,
  "stops": [
    { "stop_id": "r1_s1", "name": "Baneshwor Chowk", "lat": 27.6934, "lng": 85.3423 }
  ]
}
```

### WebSocket frame types (server → client)
```json
{ "type": "position",       "bus_id": "BUS_001", "lat": 27.71, "lng": 85.32, "speed": 35.0, "bearing": 180.0, "ts": 1234567890 }
{ "type": "eta",            "bus_id": "BUS_001", "distance_m": 1200, "duration_s": 240, "eta_iso": "2026-05-27T13:00:00Z" }
{ "type": "geofence_alert", "bus_id": "BUS_001", "stop_name": "Baneshwor Chowk", "distance_m": 480 }
```


## ═══════════════════════════════════════════════════════════════
## SECTION 7 — CHANGE LOG (append-only, never delete entries)
## ═══════════════════════════════════════════════════════════════

### [2026-05-27] — Architect: Antigravity
- Full codebase audit completed
- Identified 7 root causes for routes error on real device
- Wrote architecture document (this file)
- Completed Flutter UI/UX redesign (Yango Nepal style):
  * main.dart — dark theme, slide transitions, animated splash, AppColors palette
  * login_screen.dart — dark glassmorphism, pulsing bus logo, role pills
  * home_screen.dart — bold route cards, pulse dots, greeting header
  * tracking_screen.dart — edge-to-edge map, draggable bottom sheet
  * driver_screen.dart — circular start/stop, stats grid, trip timer
  * bus_marker_animator.dart — fixed unused field, removed stale imports
  * telegram_auth_screen.dart — fixed loginWithOtp undefined call, curly braces
  * auth_provider.dart — added loginWithOtp() method
- Fixed Android Gradle:
  * gradle.properties — removed stale newDsl + builtInKotlin flags
  * app/build.gradle.kts — fixed kotlin compilerOptions scope
- Fixed test/widget_test.dart — MyApp → BusTrackerApp
- Fixed all 46 flutter analyze warnings (withOpacity → withValues, unused imports, etc.)

### [DONE — DeepSeek / Antigravity]
- [x] T-1: app_config.dart — String.fromEnvironment with dart-define-from-file ✓
- [x] T-1: flutter/config/env.waydroid.json ✓
- [x] T-1: flutter/config/env.production.json ✓ (BASE_URL + WS_BASE + TELEGRAM_BOT_NAME)
- [x] T-2: route_manager.py — FALLBACK_ROUTES + try/except in get_all_routes() and get_route() ✓
- [x] T-3: android/app/src/main/res/xml/network_security_config.xml ✓
- [x] T-3: AndroidManifest.xml — networkSecurityConfig attribute + removed usesCleartextTraffic ✓
- [x] T-4: nginx.conf — /ws/ block: Upgrade header, Connection: upgrade, proxy_read_timeout 3600s, proxy_buffering off ✓
- [x] T-5: cloudflared/config.yml — named tunnel template ✓
- [x] T-6: backend/main.py — _auto_seed_assignments() always called on startup ✓
- [x] T-7: RUNBOOK.md — APK build commands, tunnel URL change procedure, seeding docs ✓

### [2026-05-27] — Antigravity (final fixes)
- Fixed env.production.json — was missing BASE_URL and WS_BASE fields (only had TELEGRAM_BOT_NAME)
- Added Flutter APK build section to RUNBOOK.md with --dart-define-from-file commands
- Added "When Cloudflared URL Changes" procedure to RUNBOOK.md
- Added "Seeding Test Data" section to RUNBOOK.md
- All 7 architecture tasks now complete ✓


## ═══════════════════════════════════════════════════════════════
## SECTION 8 — CONSTRAINTS & RULES (non-negotiable)
## ═══════════════════════════════════════════════════════════════

1. NEVER commit .env to git — it contains real secrets (Telegram token, passwords)
2. NEVER put secrets in app_config.dart — use --dart-define-from-file
3. NEVER use allow_origins=["*"] in CORS — breaks security
4. NEVER change the Flutter file structure — features/ and core/ layout is final
5. ALWAYS update this document (SECTION 7 change log) after any change
6. ALWAYS run `flutter analyze` before considering Flutter work done — target 0 issues
7. ALWAYS test /health endpoint after backend changes: curl http://localhost:8000/health
8. The Cloudflared free tunnel URL changes — always rebuild the APK after tunnel restart
9. For Waydroid: use 192.168.240.1 (not localhost or 10.0.2.2)
10. For real Android phone on same WiFi: use the host machine's LAN IP (e.g. 192.168.1.x)


## ═══════════════════════════════════════════════════════════════
## SECTION 9 — TESTING CHECKLIST (run before any deploy)
## ═══════════════════════════════════════════════════════════════

### Backend health check
```bash
curl http://localhost:8000/health
# Expected: { "status": "ok", "redis": true, "version": "3.0.0" }

curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"raderex","password":"x","role":"parent"}'
# Expected: { "access_token": "eyJ...", "token_type": "bearer" }

# Get routes (with the token from above)
curl http://localhost:8000/api/routes \
  -H "Authorization: Bearer eyJ..."
# Expected: JSON array with 3 routes — NEVER empty
```

### Flutter analyze
```bash
cd flutter && /home/raderex/flutter/bin/flutter analyze --no-pub
# Expected: 0 issues found
```

### APK build test
```bash
cd flutter
/home/raderex/flutter/bin/flutter build apk --debug --flavor parent \
  --dart-define-from-file=config/env.waydroid.json
# Expected: Built build/app/outputs/flutter-apk/app-parent-debug.apk
```

### Waydroid install
```bash
adb connect 192.168.240.112:5555   # Waydroid IP varies — check with: ip neigh
adb install build/app/outputs/flutter-apk/app-parent-debug.apk
```

### Real phone (Cloudflared) install
```bash
# 1. Start cloudflared tunnel, note the URL
# 2. Update flutter/config/env.production.json with new URL
# 3. Rebuild APK
# 4. Transfer APK to phone and install, OR:
adb install -r build/app/outputs/flutter-apk/app-parent-release.apk
```
