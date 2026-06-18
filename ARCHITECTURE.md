# OpenBus → Sport Tracker: New Architecture
> **For Claude Code agents.** This document replaces the original `ARCHITECTURE.md`.
> Read every section that applies to your role before touching any file.

---

## 0. Project identity change

| Field | Before | After |
|---|---|---|
| Name | KTM School Bus Tracker | OpenRun (working title) |
| Users | Schools, drivers, parents | Individual runners, public |
| Core loop | Track a bus, see ETA | Run → capture territory → compete |
| Monetisation | None (open source) | Monthly competitions with prizes |
| Reference product | — | [INTVL](https://www.intvl.com.au) |

The stack is **intentionally preserved**. Nothing is rewritten from scratch.
~70% of the existing codebase maps directly onto the new system.

---

## 1. High-level system architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FLUTTER MOBILE APP                           │
│  ┌─────────────────────────────┐  ┌──────────────────────────────┐  │
│  │       Runner Screen         │  │     Territory Map Screen     │  │
│  │  (was: Driver Screen)       │  │  (was: Parent Screen)        │  │
│  │  - Background GPS           │  │  - OpenFreeMap base layer    │  │
│  │  - Run session lifecycle    │  │  - Claimed cell polygons     │  │
│  │  - Foreground service       │  │  - Nearby runners (WS)       │  │
│  │  - POST /api/run-update     │  │  - Leaderboard panel         │  │
│  └──────────────┬──────────────┘  └────────────┬─────────────────┘  │
│                 │ HTTPS                         │ WSS                │
└─────────────────┼─────────────────────────────-┼────────────────────┘
                  │                              │
          ┌───────┴──────────────────────────────┴──────┐
          │                 NGINX                        │
          │  SSL termination · WS proxy · static pages   │
          └───────────────────┬──────────────────────────┘
                              │
          ┌───────────────────┴──────────────────────────┐
          │              FASTAPI BACKEND                  │
          │  (Python 3.12 · Uvicorn 4 workers)            │
          │                                               │
          │  ┌─────────────┐  ┌──────────────────────┐   │
          │  │  Auth layer │  │   WS Manager          │   │
          │  │  JWT HS256  │  │   /ws/{user_id}       │   │
          │  └─────────────┘  └──────────────────────-┘   │
          │  ┌─────────────┐  ┌──────────────────────┐   │
          │  │ Run Ingest  │  │   ETA / OSRM proxy    │   │
          │  │ POST        │  │   (reused, road-snap) │   │
          │  │ /api/run-   │  └──────────────────────-┘   │
          │  │ update      │  ┌──────────────────────┐   │
          │  └──────┬──────┘  │  Territory Engine    │   │
          │         │         │  territory.py (NEW)  │   │
          │         │         │  H3 cell claim logic │   │
          │         │         └──────────┬───────────┘   │
          │         │                    │               │
          │  ┌──────▼────────────────────▼───────────┐   │
          │  │           Redis 7                      │   │
          │  │  run:{id}:loc  TTL 30s  (live GPS)    │   │
          │  │  run:{id}:session  (active run state) │   │
          └──┴────────────────────────────────────────┴───┘
                              │
          ┌───────────────────┴──────────────────────────┐
          │           PostgreSQL (NEW)                    │
          │  users · runs · cells · competitions         │
          └───────────────────────────────────────────────┘
                              │
          ┌───────────────────┴──────────────────────────┐
          │           OSRM (unchanged)                    │
          │  Nepal OSM · MLD algorithm · <10ms            │
          │  NEW USE: road-snapping run traces            │
          └───────────────────────────────────────────────┘
```

---

## 2. What changes, what stays

### 2a. KEEP — zero changes required

| Component | File(s) | Notes |
|---|---|---|
| JWT auth | `backend/main.py` (auth routes) | HS256, 24h tokens, unchanged |
| Redis TTL state | `backend/main.py` (redis client) | Rename key prefix only |
| OSRM service | `docker-compose.yml`, `osrm_data/` | Add road-snap call on run finish |
| Nginx config | `nginx/conf.d/bustrack.conf` | Update upstream names only |
| Docker Compose | `docker-compose.yml` | Add postgres service |
| Cloudflare tunnel | `cloudflared/` | Unchanged |
| Telegram bot | `backend/main.py` (OTP section) | Repurpose for competition alerts |
| flutter_map | `flutter/pubspec.yaml` | Same OpenFreeMap tiles |
| Riverpod | `flutter/pubspec.yaml` | Same state management |
| geolocator | `flutter/pubspec.yaml` | Same background GPS |

### 2b. ADAPT — modify existing code

| Component | Old behaviour | New behaviour |
|---|---|---|
| `POST /api/gps-update` | Receives `{bus_id, lat, lng}` | Receives `{run_id, lat, lng, speed, bearing}` → rename to `POST /api/run-update` |
| Redis key | `bus:{id}:loc` | `run:{id}:loc` (TTL 30s unchanged) |
| `WS /ws/{route_id}` | Parent subscribes to bus route | `WS /ws/{user_id}` — subscribe to own run + nearby runners |
| `driver_screen.dart` | Driver sends bus GPS | Runner sends own GPS + run state |
| `tracking_screen.dart` | Parent sees bus on map | Runner sees territory map + nearby runners |
| User roles | `driver` / `parent` | Single role: `runner` (simplify auth) |
| ETA service | Bus → next stop ETA | Road-snap: snap raw GPS trace to road network |

### 2c. BUILD NEW

| Component | Where | Description |
|---|---|---|
| `territory.py` | `backend/territory.py` | H3 cell engine — converts a finished run polyline into claimed hex cells |
| PostgreSQL schema | `backend/db.py` + `migrations/` | Tables: `users`, `runs`, `cells`, `competitions`, `competition_entries` |
| `GET /api/leaderboard` | `backend/main.py` | Returns top N runners by km² of cells owned |
| `GET /api/competitions` | `backend/main.py` | Active + past competitions with prize info |
| `POST /api/run/finish` | `backend/main.py` | Triggers territory engine on run completion |
| `competition_screen.dart` | `flutter/lib/features/competition/` | Prize carousel, countdown timer, entry count |
| Leaderboard panel | `flutter/lib/features/map/` | Overlay on territory map screen |
| Cron job | `backend/cron.py` | Snapshot cell ownership at competition end, pick winner |

---

## 3. Database schema (PostgreSQL)

```sql
-- Users (extends existing JWT auth)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    telegram_id TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Run sessions
CREATE TABLE runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    distance_km FLOAT,
    polyline TEXT,          -- encoded Google polyline of the route
    snapped_polyline TEXT,  -- OSRM road-snapped version
    status TEXT             -- 'active' | 'finished' | 'abandoned'
);

-- H3 hex cells (territory)
CREATE TABLE cells (
    h3_index TEXT PRIMARY KEY,  -- H3 cell ID at resolution 10
    owner_id UUID REFERENCES users(id),
    captured_at TIMESTAMPTZ,
    run_id UUID REFERENCES runs(id)
);

-- Monthly competitions
CREATE TABLE competitions (
    id SERIAL PRIMARY KEY,
    name TEXT,
    prize_description TEXT,
    prize_image_url TEXT,
    starts_at TIMESTAMPTZ,
    ends_at TIMESTAMPTZ,
    status TEXT            -- 'upcoming' | 'active' | 'ended'
);

-- Entries: 1 entry per km² owned at snapshot
CREATE TABLE competition_entries (
    id SERIAL PRIMARY KEY,
    competition_id INT REFERENCES competitions(id),
    user_id UUID REFERENCES users(id),
    cell_count INT,        -- cells owned at snapshot time
    km2 FLOAT,             -- computed from cell_count
    created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 4. API contract (full delta)

### Unchanged endpoints
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /health`

### Renamed / modified endpoints

```
BEFORE: POST /api/gps-update
        body: { bus_id, lat, lng, timestamp }

AFTER:  POST /api/run-update
        body: { run_id, lat, lng, speed, bearing, timestamp }
        Redis write: run:{run_id}:loc  TTL=30s
        No DB write (hot path — Redis only)
```

```
BEFORE: GET /api/bus/{bus_id}/location
AFTER:  GET /api/run/{run_id}/location
        Returns: { lat, lng, speed, bearing, last_seen }
```

```
BEFORE: WS /ws/{route_id}
AFTER:  WS /ws/{user_id}
        Server pushes: nearby runner positions (radius 5km)
                       own run stats (distance, pace, duration)
        Message format: { type: "position"|"stats", payload: {...} }
```

### New endpoints

```
POST /api/run/start
     body: { user_id }
     Returns: { run_id }
     Redis: run:{run_id}:session = { status: "active", started_at }

POST /api/run/finish
     body: { run_id, polyline }
     Actions:
       1. OSRM match-route (road snap)
       2. territory.py → compute H3 cells
       3. Upsert cells table (last-writer-wins)
       4. Write run record to PostgreSQL
     Returns: { cells_captured, km2_captured, cells_lost }

GET /api/leaderboard?limit=50
    Returns: [{ username, km2, rank }]

GET /api/competitions
    Returns: [{ id, name, prize, ends_at, my_entries, status }]

GET /api/territory/{user_id}
    Returns: { cells: [h3_index, ...] }
    Used by map screen to render owned territory
```

---

## 5. Flutter app structure (new)

```
flutter/lib/
├── features/
│   ├── run/
│   │   ├── run_screen.dart          # was: driver_screen.dart
│   │   ├── run_controller.dart      # Riverpod: start/pause/finish
│   │   └── gps_service.dart        # background GPS (unchanged logic)
│   ├── map/
│   │   ├── territory_map_screen.dart # was: tracking_screen.dart
│   │   ├── territory_painter.dart    # NEW: render H3 cells as polygons
│   │   └── leaderboard_panel.dart    # NEW: slide-up leaderboard
│   ├── competition/
│   │   ├── competition_screen.dart   # NEW: prize carousel + countdown
│   │   └── competition_controller.dart
│   └── auth/                         # unchanged
├── core/
│   ├── auth/                         # unchanged
│   ├── config/                       # update API base URL only
│   └── network/                      # unchanged
```

### Key Flutter changes by file

**`run_screen.dart`** (was `driver_screen.dart`)
- Keep: background GPS, foreground service, geolocator plugin
- Change: POST endpoint → `/api/run-update`
- Change: payload schema (add speed, bearing)
- Add: run session state (start / pause / finish buttons)
- Add: live stats overlay (pace, distance, duration)

**`territory_map_screen.dart`** (was `tracking_screen.dart`)
- Keep: flutter_map, OpenFreeMap tiles, WebSocket subscription
- Change: WS path → `/ws/{user_id}`
- Change: render runner markers (not bus marker)
- Add: territory layer — fetch `/api/territory/{user_id}`, render H3 polygons
- Add: leaderboard panel (slide-up from bottom)

**`competition_screen.dart`** (new)
- Prize image carousel (mirrors INTVL homepage)
- Countdown timer to competition end
- User's entry count (km² × 1 entry per km²)
- Pull from `GET /api/competitions`

---

## 6. Territory engine (`backend/territory.py`)

```python
# Conceptual logic — implement using h3-py library
import h3

H3_RESOLUTION = 10  # ~15m hexagons — fine enough for running

def polyline_to_cells(polyline_coords: list[tuple]) -> set[str]:
    """Convert a list of (lat, lng) GPS points to H3 cells."""
    cells = set()
    for lat, lng in polyline_coords:
        cell = h3.geo_to_h3(lat, lng, H3_RESOLUTION)
        cells.add(cell)
        # Fill neighbours to avoid gaps between GPS samples
        cells.update(h3.k_ring(cell, 1))
    return cells

def claim_cells(run_id: str, user_id: str, cells: set[str], db):
    """Upsert cells — last writer wins."""
    for cell in cells:
        db.execute("""
            INSERT INTO cells (h3_index, owner_id, captured_at, run_id)
            VALUES (%s, %s, now(), %s)
            ON CONFLICT (h3_index) DO UPDATE
            SET owner_id = EXCLUDED.owner_id,
                captured_at = EXCLUDED.captured_at,
                run_id = EXCLUDED.run_id
        """, (cell, user_id, run_id))
```

Add to `requirements.txt`:
```
h3>=3.7
psycopg2-binary>=2.9
alembic>=1.13
```

---

## 7. Docker Compose additions

Add to `docker-compose.yml`:

```yaml
services:
  # ... existing services unchanged ...

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: openrun
      POSTGRES_USER: openrun
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

volumes:
  postgres_data:
```

Add to `.env.example`:
```
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=openrun
POSTGRES_USER=openrun
POSTGRES_PASSWORD=your_secure_password
```

---

## 8. Agent instructions

---

### AGENT: Realtime Engineer
**Your scope:** WebSocket manager, Redis, GPS ingest hot path.

**Files to read first:**
- `backend/main.py` — find `POST /api/gps-update`, the Redis write block, and the WS manager

**Your tasks in order:**

1. **Rename GPS ingest route** in `main.py`:
   - `POST /api/gps-update` → `POST /api/run-update`
   - Update payload model: add `speed: float`, `bearing: float` fields (optional, default 0.0)
   - Redis key: change `bus:{bus_id}:loc` → `run:{run_id}:loc` (TTL 30s unchanged)

2. **Update WS room logic** in `main.py`:
   - Change room key from `route_id` to `user_id`
   - On each GPS ping received, broadcast to all WS clients within 5km radius
   - Radius check: pull all active `run:*:loc` keys from Redis, filter by haversine distance
   - Broadcast message schema:
     ```json
     { "type": "position", "payload": { "user_id": "...", "lat": 0.0, "lng": 0.0, "speed": 0.0 } }
     ```

3. **Add run session endpoints** in `main.py`:
   - `POST /api/run/start` → write `run:{run_id}:session` to Redis with `status=active`
   - `POST /api/run/finish` → read session, call `territory.py`, write to PostgreSQL, delete Redis keys
   - Use `asyncio.create_task()` for the territory computation so the HTTP response returns immediately

4. **Add live stats broadcast** on WS:
   - Every 5s, push to the runner's own WS connection: `{ "type": "stats", "payload": { "distance_km": ..., "pace_min_km": ..., "duration_s": ... } }`
   - Compute distance from polyline accumulated in Redis session

**Do not touch:** auth, OSRM proxy, nginx config, Flutter files.

---

### AGENT: Backend Engineer
**Your scope:** PostgreSQL, territory engine, leaderboard, competitions API, OSRM road-snap.

**Files to read first:**
- `backend/main.py` — understand existing route structure and how to add new routes
- `backend/requirements.txt` — you will add packages
- `docker-compose.yml` — you will add postgres service

**Your tasks in order:**

1. **Add PostgreSQL to Docker Compose** — see Section 7 above.

2. **Create `backend/db.py`**:
   - Async SQLAlchemy connection pool using `asyncpg`
   - `get_db()` dependency for FastAPI routes
   - Run migrations on startup using Alembic

3. **Create `backend/migrations/`**:
   - Use Alembic. `alembic init migrations`
   - Write `versions/001_initial.py` with the full schema from Section 3

4. **Create `backend/territory.py`**:
   - Implement `polyline_to_cells()` and `claim_cells()` from Section 6
   - Install `h3` library
   - Add `compute_km2(cells: set) -> float` using `h3.cell_area(cell, unit='km^2')`

5. **Add new API routes** to `backend/main.py` (see Section 4):
   - `POST /api/run/finish` — call OSRM match-route, then territory engine, then DB writes
   - `GET /api/leaderboard` — aggregate `cells` table by `owner_id`, join users
   - `GET /api/competitions` — read from `competitions` table
   - `GET /api/territory/{user_id}` — return list of H3 cell indexes for a user

6. **OSRM road-snap** (reuse existing OSRM service):
   - Endpoint to call: `GET http://osrm:5000/match/v1/foot/{coordinates}`
   - Pass the run polyline as a list of `lng,lat` pairs
   - Return the matched geometry as the snapped polyline

7. **Create `backend/cron.py`**:
   - APScheduler job: runs at end of each competition's `ends_at`
   - Snapshots `cells` table per user, writes to `competition_entries`
   - Send winner notification via Telegram bot (reuse existing bot token)

8. **Update `requirements.txt`**:
   ```
   h3>=3.7
   psycopg2-binary>=2.9
   asyncpg>=0.29
   SQLAlchemy>=2.0
   alembic>=1.13
   APScheduler>=3.10
   ```

**Do not touch:** Redis logic, WebSocket manager, Flutter files, Nginx config.

---

### AGENT: Frontend Engineer
**Your scope:** All Flutter code under `flutter/`.

**Files to read first:**
- `flutter/lib/features/tracking/tracking_screen.dart`
- `flutter/lib/features/driver/driver_screen.dart`
- `flutter/lib/core/config/` — find the API base URL constant
- `flutter/pubspec.yaml`

**Your tasks in order:**

1. **Rename driver_screen.dart → run_screen.dart**:
   - Keep all geolocator background GPS code unchanged
   - Change POST endpoint: `/api/gps-update` → `/api/run-update`
   - Update payload: add `speed` (from `Position.speed`) and `bearing` (from `Position.heading`)
   - Add run session UI:
     - **Start Run** button → calls `POST /api/run/start`, stores `run_id` in Riverpod state
     - **Pause** button → stops GPS posting but keeps session open
     - **Finish Run** button → sends accumulated polyline to `POST /api/run/finish`, shows results modal
   - Add stats overlay on screen: pace (min/km), distance (km), duration (mm:ss)
   - Live stats come from WS message type `stats`

2. **Rename tracking_screen.dart → territory_map_screen.dart**:
   - Keep flutter_map, OpenFreeMap tiles — unchanged
   - Change WS path: `/ws/{route_id}` → `/ws/{user_id}`
   - Replace bus marker rendering with runner circle markers (different colours per user)
   - Add territory layer:
     - On screen load: `GET /api/territory/{user_id}` → list of H3 indexes
     - Convert H3 indexes to lat/lng polygons using `h3_flutter` package (or compute boundary manually)
     - Render as semi-transparent filled polygons on the map (`PolygonLayer` in flutter_map)
     - Own territory: amber fill. Others' territory: grey fill.
   - Add leaderboard bottom sheet:
     - Slide-up panel triggered by FAB
     - `GET /api/leaderboard` → list of `{ rank, username, km2 }`
     - Simple ListView

3. **Create `flutter/lib/features/competition/competition_screen.dart`**:
   - `GET /api/competitions` on mount
   - Prize image carousel (use `PageView` widget)
   - Countdown timer (end time from API, update every second with `Timer.periodic`)
   - User's entry count displayed below countdown
   - Match INTVL visual style: bold hero text, minimal UI

4. **Update `flutter/pubspec.yaml`**:
   ```yaml
   dependencies:
     h3_flutter: ^1.0.0  # for H3 polygon boundary calculation
   ```

5. **Update `flutter/lib/core/config/`**:
   - Ensure API base URL is environment-injectable (not hardcoded)
   - Add WS URL config alongside HTTP URL

6. **Update `flutter/lib/core/network/`**:
   - Add `RunRepository` class with methods:
     - `startRun()` → `POST /api/run/start`
     - `sendGpsUpdate(runId, position)` → `POST /api/run-update`
     - `finishRun(runId, polyline)` → `POST /api/run/finish`
     - `getTerritory(userId)` → `GET /api/territory/{userId}`
     - `getLeaderboard()` → `GET /api/leaderboard`
     - `getCompetitions()` → `GET /api/competitions`

**Do not touch:** backend Python files, Docker Compose, Nginx, Redis logic.

---

## 9. Dependency graph (agent coordination)

```
Realtime Engineer
    ↓ (defines WS message schema + /api/run-update payload)
Frontend Engineer reads schema → implements run_screen.dart

Backend Engineer
    ↓ (defines /api/run/finish response + /api/territory/{id} response)
Realtime Engineer reads → calls territory.py on run finish
Frontend Engineer reads → renders territory layer

Realtime Engineer + Backend Engineer must agree on:
    - run_id format (UUID string)
    - Redis key prefix (run:{id}:loc)
    - WS message envelope: { type, payload }
    before Frontend Engineer builds WS listener
```

**Suggested sequence:**
1. Backend Engineer brings up PostgreSQL + schema (30 min)
2. Realtime Engineer renames routes + Redis keys (30 min)
3. Both engineers expose `/api/run/finish` end-to-end (1–2h)
4. Frontend Engineer works against a running backend from step 3

---

## 10. Environment variables (full updated list)

```bash
# Redis (unchanged)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=your_secure_password

# JWT (unchanged)
JWT_SECRET=your_jwt_secret_key
JWT_ALGORITHM=HS256

# OSRM (unchanged)
OSRM_HOST=osrm
OSRM_PORT=5000

# FastAPI (unchanged)
API_PORT=8000
API_WORKERS=4

# Telegram (unchanged — repurposed for competition alerts)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ADMIN_CHAT_ID=your_chat_id

# PostgreSQL (NEW)
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=openrun
POSTGRES_USER=openrun
POSTGRES_PASSWORD=your_secure_password

# Territory (NEW)
H3_RESOLUTION=10
TERRITORY_RING_BUFFER=1       # k_ring size to fill GPS gaps

# Competition (NEW)
COMPETITION_SNAPSHOT_CRON="0 0 * * *"   # daily midnight check
```

---

## 11. Migration checklist (run once on first deploy)

```bash
# 1. Pull new docker-compose with postgres service
docker compose pull

# 2. Start postgres first
docker compose up postgres -d

# 3. Run Alembic migrations
docker compose run backend alembic upgrade head

# 4. Restart full stack
docker compose up -d

# 5. Verify
curl https://yourdomain.com/health
curl https://yourdomain.com/api/leaderboard
```

---

*Last updated: 2026-06-02 | Author: system architect*
