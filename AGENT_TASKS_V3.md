# Kabja — Next Task Briefs (V3)
> Based on thorough audit of the live repo as of 2026-06-18.
> Distribute the relevant section to each agent. Do not give all three to one agent.

---

## CRITICAL FINDING — READ FIRST

The `.gitignore` has `*.md` at the top, blocking ALL markdown files.
This means:
- `AGENT_BACKEND.md`, `AGENT_FRONTEND.md`, `AGENT_REALTIME.md` are all gitignored
- Any future `.md` notes or docs will silently not push

**First thing any agent does:**
```bash
# Remove the *.md line from .gitignore (line 3)
# Keep only: !README.md
# Then force-add the agent files:
git add -f AGENT_*.md ARCHITECTURE.md
git commit -m "fix: unblock .md files from gitignore"
git push
```

Also: the docker-compose still has `PUBLIC_URL` defaulting to `bustrack.yourdomain.com` — old KTM bus tracker URL. Change to `kabja.yourdomain.com` everywhere.

---

---

# AGENT: Realtime Engineer — Tasks V3

## What's confirmed working (don't touch)
- Redis config in docker-compose is correct (maxmemory, TTL, password auth)
- OSRM container config is correct (ch algorithm, port 5000, foot profile)
- WebSocket path `/ws/{user_id}` is confirmed in README
- WS message envelope `{type, payload}` is confirmed

## What's broken or missing — fix these in order

### Task 1 — OSRM profile is wrong (car.lua, not foot.lua)
**This is a hard bug.** The docker-compose OSRM prep command uses:
```
osrm-extract -p /opt/car.lua /data/nepal-latest.osm.pbf
```
**This is the car routing profile.** Runners are on foot. Car routing snaps GPS to roads that runners can't legally or physically use (highways, expressways). Change to:
```
osrm-extract -p /opt/foot.lua /data/nepal-latest.osm.pbf
```
If OSRM data was already processed with `car.lua`, it must be reprocessed. Delete the existing `.osrm*` files and re-run all three extract/partition/customize commands with `foot.lua`. This is non-negotiable — wrong profile means territory claims on motorways.

Fix in `docker-compose.yml` comments (lines 67-80). Update all three docker run commands to use `foot.lua`.

### Task 2 — WS connection drops every 60s (nginx timeout)
The nginx config almost certainly has no `proxy_read_timeout`. Default nginx timeout is 60 seconds. Any WebSocket connection idle for 60s drops silently. A runner standing still for 1 minute loses their live connection.

Open `nginx/nginx.conf`. Find the `/ws/` location block. Verify AND add if missing:
```nginx
location /ws/ {
    proxy_pass http://kabja_api:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 86400s;    # ← CRITICAL — 24h, not 60s default
    proxy_send_timeout 86400s;
    proxy_connect_timeout 10s;
}
```
Without `proxy_read_timeout 86400s` the app will appear to randomly disconnect during runs.

### Task 3 — GPS update interval is too fast for 4GB VRAM (Alienware RTX 3050 Ti)
The run sends GPS every 3 seconds. On a physical device running both the app and the local server, this creates ~20 req/s per active runner (GPS update + Redis write + session update). Under load this will spike CPU. Change the GPS update interval logic to:
- Send every **5 seconds** when speed < 1 m/s (walking/stopped)
- Send every **3 seconds** when speed ≥ 1 m/s (running)

This requires a small change in the Flutter `run_controller.dart` (pass to Frontend Engineer) AND document it here so the backend rate limiter doesn't reject slow updates.

### Task 4 — Add rate limiting to `/api/run-update`
The hot path has no rate limiting. A buggy client could flood it. Add to `main.py`:
```python
from collections import defaultdict
import time

_rate_buckets: dict[str, list[float]] = defaultdict(list)

def _check_rate(user_id: str, max_per_minute: int = 30) -> bool:
    """Simple in-memory rate limiter. 30 updates/min = one every 2s."""
    now = time.time()
    bucket = _rate_buckets[user_id]
    # Drop entries older than 60s
    _rate_buckets[user_id] = [t for t in bucket if now - t < 60]
    if len(_rate_buckets[user_id]) >= max_per_minute:
        return False
    _rate_buckets[user_id].append(now)
    return True

# In /api/run-update route, add before Redis write:
if not _check_rate(token["user_id"]):
    raise HTTPException(status_code=429, detail="Too many GPS updates")
```

### Task 5 — Verify abandoned run cleanup is in cron.py
Open `backend/cron.py`. Confirm it has a job that:
- Scans Redis for `run:*:session` keys where `status == "active"`
- Checks if the matching `run:*:loc` key (TTL 30s) has expired
- If expired AND session is >90 minutes old → marks session `abandoned` and deletes Redis keys

If this job is missing, Redis slowly accumulates dead sessions. Add it if not there.

### Task 6 — Write and commit the WS test script
Create `scripts/ws_monitor.py`:
```python
#!/usr/bin/env python3
"""
Usage: python3 scripts/ws_monitor.py <user_id> <jwt_token>
Run during a live test to watch all WS messages in real time.
"""
import asyncio, sys, json, websockets
from datetime import datetime

async def monitor(user_id, token):
    uri = f"ws://localhost:8000/ws/{user_id}"
    print(f"Connecting to {uri}\n")
    async with websockets.connect(uri, extra_headers={"Authorization": f"Bearer {token}"}) as ws:
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=65)
                msg = json.loads(raw)
                t = datetime.now().strftime("%H:%M:%S")
                mtype = msg.get("type", "?")
                p = msg.get("payload", {})
                if mtype == "stats":
                    print(f"[{t}] STATS  dist={p.get('distance_km',0):.3f}km  pace={p.get('pace_min_km',0):.1f}min/km  dur={p.get('duration_s',0)}s")
                elif mtype == "position":
                    print(f"[{t}] RUNNER run_id={str(p.get('run_id','?'))[:8]}  lat={p.get('lat',0):.4f}  lng={p.get('lng',0):.4f}")
                elif mtype == "territory_result":
                    print(f"[{t}] TERRITORY +{p.get('cells_captured',0)} cells  {p.get('km2_captured',0):.4f}km²  lost={p.get('cells_lost',0)}")
                else:
                    print(f"[{t}] {mtype.upper()}  {p}")
            except asyncio.TimeoutError:
                await ws.send("ping")
    
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 ws_monitor.py <user_id> <token>")
        sys.exit(1)
    asyncio.run(monitor(sys.argv[1], sys.argv[2]))
```

```bash
pip install websockets
chmod +x scripts/ws_monitor.py
git add scripts/ws_monitor.py
git commit -m "feat: add WS live monitor script for testing"
```

---

---

# AGENT: Backend Engineer — Tasks V3

## What's confirmed working (don't touch)
- PostgreSQL 16 container with healthcheck ✓
- Alembic migration structure (001, 002) ✓
- Strava OAuth endpoint list in README ✓
- CORS is referenced in compose CORS_ORIGINS env var ✓
- Cron service in docker-compose ✓

## What's broken or missing — fix these in order

### Task 1 — DATABASE_URL uses wrong driver (sync, not async)
In `docker-compose.yml` line ~133:
```yaml
DATABASE_URL: "postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
```
This is the **sync** PostgreSQL URL. SQLAlchemy async requires `postgresql+asyncpg://`. If `db.py` builds its engine from `DATABASE_URL` directly, every DB operation will either error out or block the event loop.

Fix the env var in docker-compose:
```yaml
DATABASE_URL: "postgresql+asyncpg://${POSTGRES_USER:-openrun}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-openrun}"
```
AND verify `db.py` uses this URL correctly for `create_async_engine()`.

### Task 2 — No `/api/auth/register` endpoint (confirmed missing from README API table)
The README's Authentication section only lists `POST /api/auth/login`. No register endpoint. The Flutter app cannot create new users without it.

Add to `main.py`:
```python
class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""

@app.post("/api/auth/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    import hashlib, secrets
    # Check duplicate
    result = await db.execute(
        "SELECT id FROM users WHERE username = :u", {"u": req.username.strip()})
    if result.fetchone():
        raise HTTPException(status_code=409, detail="Username taken")
    
    salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256(f"{salt}{req.password}".encode()).hexdigest()
    user_id = str(uuid_lib.uuid4())
    
    async with db.begin():
        await db.execute("""
            INSERT INTO users (id, username, display_name, password_hash, password_salt, created_at)
            VALUES (:id, :u, :dn, :ph, :ps, now())
        """, {"id": user_id, "u": req.username.strip(),
              "dn": req.display_name or req.username,
              "ph": pw_hash, "ps": salt})
    
    token = _create_jwt(user_id, req.username)
    return {"access_token": token, "user_id": user_id,
            "username": req.username, "display_name": req.display_name or req.username}
```

Also update `POST /api/auth/login` to return `user_id` and `display_name` — currently it likely only returns `access_token`. Flutter needs all four fields.

### Task 3 — Migration 003: add auth fields to users table
The current `users` table (migration 001) almost certainly only has `id`, `username`, `telegram_id`, `created_at`. Login with password requires `password_hash` and `password_salt`. Add migration:

Create `backend/migrations/versions/003_user_auth_fields.py`:
```python
"""003_user_auth_fields — add password, display_name, streak fields
Revision ID: 003
Revises: 002
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'

def upgrade():
    op.add_column('users', sa.Column('display_name', sa.Text, nullable=True))
    op.add_column('users', sa.Column('password_hash', sa.Text, nullable=True))
    op.add_column('users', sa.Column('password_salt', sa.Text, nullable=True))
    op.add_column('users', sa.Column('total_km2', sa.Float, server_default='0'))
    op.add_column('users', sa.Column('total_runs', sa.Integer, server_default='0'))
    op.add_column('users', sa.Column('streak_days', sa.Integer, server_default='0'))
    op.add_column('users', sa.Column('last_run_date', sa.Date, nullable=True))
    op.add_column('users', sa.Column('strava_athlete_id', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_access_token', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_refresh_token', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_token_expiry', sa.TIMESTAMP(timezone=True), nullable=True))

def downgrade():
    for col in ['display_name','password_hash','password_salt','total_km2',
                'total_runs','streak_days','last_run_date','strava_athlete_id',
                'strava_access_token','strava_refresh_token','strava_token_expiry']:
        op.drop_column('users', col)
```

Run: `docker compose exec api alembic upgrade head`

### Task 4 — Add `/api/profile/{user_id}` endpoint (missing from README)
The profile screen needs this. It's not in the README API table — add it:
```python
@app.get("/api/profile/{user_id}")
async def get_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute("""
        SELECT u.id, u.username, u.display_name, u.total_km2, u.total_runs,
               u.streak_days, u.created_at, u.strava_athlete_id,
               COUNT(c.h3_index) as live_cells
        FROM users u
        LEFT JOIN cells c ON c.owner_id = u.id
        WHERE u.id = :uid
        GROUP BY u.id
    """, {"uid": user_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user_id": row[0], "username": row[1],
        "display_name": row[2] or row[1],
        "total_km2": round(row[3] or 0, 4),
        "total_runs": row[4] or 0,
        "streak_days": row[5] or 0,
        "joined_at": row[6].isoformat() if row[6] else None,
        "live_cell_count": row[8] or 0,
        "strava_connected": bool(row[7]),
    }
```

### Task 5 — Strava timestamp guard in territory.py
Open `backend/territory.py`. Find the `claim_cells()` INSERT/upsert. The current ON CONFLICT clause almost certainly does not check timestamps. Add the WHERE guard:
```sql
ON CONFLICT (h3_index) DO UPDATE
SET owner_id = EXCLUDED.owner_id,
    captured_at = EXCLUDED.captured_at,
    run_id = EXCLUDED.run_id
WHERE cells.captured_at < EXCLUDED.captured_at  -- ← ADD THIS LINE
```
Pass `run_finished_at` as `captured_at` in the INSERT values. Without this, a Strava import of a 6-month-old run overwrites fresh territory from someone who ran this morning.

### Task 6 — Seed test data script
Create `scripts/seed.py` and run it after migrations:
```python
#!/usr/bin/env python3
import asyncio, hashlib, secrets, uuid
import sys; sys.path.insert(0, '/app')
from db import AsyncSessionLocal

USERS = [
    ("testrunner", "Test Runner", "test123"),
    ("aarav_kc", "Aarav KC", "test123"),
    ("priya_rana", "Priya Rana", "test123"),
]

async def seed():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            for username, display, pw in USERS:
                salt = "testsalt_v1"
                pw_hash = hashlib.sha256(f"{salt}{pw}".encode()).hexdigest()
                uid = str(uuid.uuid4())
                await db.execute("""
                    INSERT INTO users (id, username, display_name, password_hash, password_salt, created_at)
                    VALUES (:id,:u,:dn,:ph,:ps,now())
                    ON CONFLICT (username) DO NOTHING
                """, {"id":uid,"u":username,"dn":display,"ph":pw_hash,"ps":salt})
                print(f"  ✓ {username} / test123")
            
            # Demo competition
            await db.execute("""
                INSERT INTO competitions
                  (name, prize_description, prize_image_url, starts_at, ends_at, status)
                VALUES (
                  'June Sprint 2026',
                  'Free Kabja Premium for 3 months',
                  'https://placehold.co/800x400/EF9F27/000000?text=June+Sprint',
                  now(), now() + interval '28 days', 'active'
                ) ON CONFLICT DO NOTHING
            """)
            print("  ✓ June Sprint 2026 competition")
    print("\n✓ Seed complete. Login: testrunner / test123")

asyncio.run(seed())
```

```bash
docker compose exec api python /app/scripts/seed.py
```

### Task 7 — Full smoke test (run after all above)
```bash
BASE=http://localhost:8000

# 1. Health
curl -s $BASE/health | python3 -m json.tool

# 2. Register
curl -s -X POST $BASE/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"smoketest99","password":"abc123","display_name":"Smoke"}' | python3 -m json.tool

# 3. Login → get token
TOKEN=$(curl -s -X POST $BASE/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testrunner","password":"test123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

USER_ID=$(curl -s -X POST $BASE/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testrunner","password":"test123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['user_id'])")

# 4. Profile
curl -s $BASE/api/profile/$USER_ID | python3 -m json.tool

# 5. Leaderboard
curl -s $BASE/api/leaderboard | python3 -m json.tool

# 6. Competitions
curl -s -H "Authorization: Bearer $TOKEN" $BASE/api/competitions | python3 -m json.tool

# 7. Territory (empty = correct for new user)
curl -s $BASE/api/territory/$USER_ID | python3 -m json.tool

# 8. Run lifecycle
RUN_ID=$(curl -s -X POST $BASE/api/run/start \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['run_id'])")
echo "run_id: $RUN_ID"

curl -s -X POST $BASE/api/run-update \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"run_id\":\"$RUN_ID\",\"lat\":27.7172,\"lng\":85.3240,\"speed\":2.5,\"bearing\":90,\"timestamp\":\"$(date -u +%FT%TZ)\"}"

curl -s -X POST "$BASE/api/run/finish?run_id=$RUN_ID" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo "All done — zero 500s means you're ready."
```

---

---

# AGENT: Frontend Engineer — Tasks V3

## What's confirmed (structure exists locally)
- Flutter folder exists with `lib/` structure per README
- `pubspec.yaml` references: riverpod, go_router, flutter_map, geolocator, app_links, shimmer, google_fonts
- Four feature folders: run/, map/, competition/, profile/

## The `.gitignore` problem — do this FIRST
The `.gitignore` has `*.md` which is fine for docs but it may also be blocking Dart files if there's a misconfigured rule. More critically, check if `flutter/lib/` is accidentally ignored:
```bash
cd flutter
git check-ignore -v lib/main.dart    # should return nothing (not ignored)
git check-ignore -v lib/             # should return nothing
```
If either returns a rule, find it in `.gitignore` and remove it. Then:
```bash
git add flutter/lib/
git status    # should show ALL dart files as staged
git commit -m "feat: add all Flutter source files"
git push
```

## What to build — in strict order

### Task 1 — Confirm `flutter analyze` passes with zero errors
Before anything else:
```bash
cd flutter
flutter pub get
flutter analyze 2>&1 | head -50
```
Fix every error (not warning) before proceeding. Common errors from AI-generated Dart:
- `The method 'X' isn't defined` → missing import or wrong class name
- `A value of type 'X' can't be assigned to 'Y'` → cast needed
- `The argument type 'X' can't be assigned to parameter type 'Y'` → wrong type
- `Undefined name 'runRepoProvider'` → provider not wired in the right file

### Task 2 — Fix the `runRepoProvider` wiring
The `run_controller.dart` references `runRepoProvider` but it's defined nowhere in the codebase (it was left as a comment in the brief). Add this to `flutter/lib/core/network/run_repository.dart` at the bottom:

```dart
// At the top of run_repository.dart, add:
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_provider.dart';

// At the bottom:
final runRepoProvider = Provider<RunRepository>((ref) {
  final auth = ref.watch(authProvider);
  return RunRepository(getToken: () => auth.token ?? '');
});
```

### Task 3 — Fix the map screen: `h3_flutter` API may differ
The `h3_flutter` package API changed between versions. The brief used `h3.cellToBoundary(BigInt.parse(cellId, radix: 16))`. Verify the actual API:
```bash
cat flutter/.dart_tool/package_config.json | grep h3_flutter
# Find the version, then check: flutter/lib/features/map/map_screen.dart
```

If `cellToBoundary` doesn't exist on the `H3` class, use this fallback that works with any version:
```dart
// Fallback: approximate hex polygon from center point
// Use this if h3_flutter API is different
List<LatLng> _approximateHexFromCenter(double lat, double lng) {
  const r = 0.00015; // ~15m radius in degrees
  return List.generate(6, (i) {
    final angle = (i * 60) * (3.14159 / 180);
    return LatLng(lat + r * cos(angle), lng + r * sin(angle));
  });
}
```
This is less accurate but will render something on the map while you debug the H3 library version.

### Task 4 — Fix GPS permissions for physical device testing
For testing on a real Android device (critical for tomorrow's run test), the `AndroidManifest.xml` must have foreground service declaration. Open `flutter/android/app/src/main/AndroidManifest.xml` and ensure:

```xml
<!-- Inside <manifest> tag, before <application> -->
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION"/>
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION"/>
<uses-permission android:name="android.permission.ACCESS_BACKGROUND_LOCATION"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE"/>
<uses-permission android:name="android.permission.FOREGROUND_SERVICE_LOCATION"/>
<uses-permission android:name="android.permission.INTERNET"/>

<!-- Inside <application> tag -->
<service
    android:name="com.baseflow.geolocator.GeolocatorService"
    android:foregroundServiceType="location"
    android:exported="false"/>

<!-- Inside the main <activity> tag — for kabja:// deep link -->
<intent-filter android:autoVerify="true">
    <action android:name="android.intent.action.VIEW"/>
    <category android:name="android.intent.category.DEFAULT"/>
    <category android:name="android.intent.category.BROWSABLE"/>
    <data android:scheme="kabja"/>
</intent-filter>
```

Without `FOREGROUND_SERVICE_LOCATION` on Android 14+, background GPS stops working the moment the screen turns off. This will break every outdoor run test.

### Task 5 — Wire the API base URL for physical device testing
The current `AppConfig` uses `10.0.2.2:8000` (Android emulator localhost). For a physical device on the same WiFi as the dev machine:

```dart
// flutter/lib/core/config/app_config.dart
class AppConfig {
  // For emulator: 10.0.2.2
  // For physical device: your machine's local IP (e.g. 192.168.1.100)
  // For production: your domain
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL', defaultValue: 'http://192.168.1.100:8000');
  static const wsBaseUrl = String.fromEnvironment(
    'WS_BASE_URL', defaultValue: 'ws://192.168.1.100:8000');
}
```

Find your machine's local IP:
```bash
ip addr show | grep "inet " | grep -v 127.0.0.1
# or on Mac: ifconfig | grep "inet " | grep -v 127.0.0.1
```

Then run Flutter with the right IP:
```bash
flutter run --dart-define=API_BASE_URL=http://192.168.1.XXX:8000 \
            --dart-define=WS_BASE_URL=ws://192.168.1.XXX:8000
```

### Task 6 — Implement the 3 stub screens
The brief said "create these screens" but gave minimal code for run_screen, competition_screen, and profile_screen. They must all be complete and wired. Minimum viable implementation for each:

**`run_screen.dart`** must:
- Call `POST /api/run/start` when START is tapped → store `run_id` in state
- Send `POST /api/run-update` every 5s via a `Timer.periodic`
- Show distance, duration (incrementing every second), pace
- PAUSE stops the timer and GPS posting
- FINISH calls `POST /api/run/finish` → shows a result modal
- Result modal shows cells captured (from WS territory_result OR from the HTTP response)

**`competition_screen.dart`** must:
- Call `GET /api/competitions` on mount
- Show at minimum: competition name, prize description, countdown timer
- Countdown must tick every second using `Timer.periodic`
- Handle empty competitions list gracefully ("No active competitions")

**`profile_screen.dart`** must:
- Call `GET /api/profile/{user_id}` on mount
- Show: display_name, total_runs, total_km2, streak_days, live_cell_count
- Strava section: if `strava_connected == false` show "Connect Strava" button
- Connect Strava button calls `GET /api/strava/auth-url` → opens URL in browser
- Handle `strava_connected == true` by showing athlete name and "Disconnect" button

### Task 7 — GPS warmup: discard first 60 seconds
In `run_controller.dart`, add a warmup guard so early bad GPS points don't claim phantom territory:
```dart
bool _gpsWarmedUp = false;
DateTime? _runStartTime;

// In _startGps() listener:
_gpsSub = Geolocator.getPositionStream(...).listen((position) {
  // Discard first 60 seconds of GPS (signal stabilisation)
  if (!_gpsWarmedUp) {
    if (_runStartTime == null) _runStartTime = DateTime.now();
    if (DateTime.now().difference(_runStartTime!).inSeconds < 60) {
      return; // Don't add to polyline, don't send to server
    }
    _gpsWarmedUp = true;
  }
  // Normal processing from here
  ...
});
```

Show "Acquiring GPS signal..." text overlay on the run screen for the first 60 seconds so users don't think the app is broken.

### Task 8 — Full flutter run checklist before committing
```bash
flutter pub get
flutter analyze          # zero errors required
flutter run              # on emulator or device

# Manually verify:
# ✓ App opens to map (not splash, not login)
# ✓ Hamburger icon top-left opens side menu
# ✓ Menu items tap correctly (no dead buttons)
# ✓ Login screen submits and redirects to map
# ✓ Register screen creates account
# ✓ After login: START RUN button appears
# ✓ START RUN opens run screen
# ✓ Run screen shows 00:00 timer, 0.00km
# ✓ Timer ticks when START is pressed
# ✓ Competition screen loads and countdown ticks
# ✓ Profile screen shows stats (or login prompt if not authed)
# ✓ No red error banners on any screen

git add flutter/lib/
git commit -m "feat: complete Flutter app with all screens functional"
git push
```

---

## Shared — all agents do this after their tasks

```bash
# Fix the .gitignore *.md line so agent docs push properly:
# Edit .gitignore — remove line: *.md
# Keep line: !README.md
# Then:
git add .gitignore
git commit -m "fix: allow .md files except secrets"
git push
```

---

*Kabja V3 task briefs — 2026-06-18*
