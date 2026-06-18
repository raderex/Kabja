# HANDOFF — KTM School Bus Tracker v3.0

**Status**: Architecture v3 — Complete Redesign  
**Created**: 2026-05-28  
**Architect**: Antigravity (Senior Systems Architect)  
**For**: 3 coding agents to implement in parallel

---

## 1. WHAT THIS APP IS

A **real-time school bus tracker** for Kathmandu Valley.  
Parents see their child's bus live on a map. Drivers broadcast GPS.  
This is NOT a public transit app — it is a **school-specific** system.

### Core Principles
- **1 student = 1 parent account = 1 bus assignment**
- **Login → Map immediately** (no route list, no selection screen)
- **GPS is primary**, network is the delivery pipe
- **Offline-resilient**: GPS buffers locally when network drops
- **Nepal bus numbering**: mixed alpha-numeric (A, B, A1, Ba2, Ka3, etc.)
- **Scalable**: designed for 100+ schools, 1000+ buses, 50k+ parents

---

## 2. APP FLOW (CRITICAL — READ FIRST)

### Parent App Flow
```
Login → Map Screen (full-screen, edge-to-edge)
  ├── IF has_assignment: Show assigned bus live on map
  │     └── Bottom sheet: bus info, ETA, speed, driver name
  ├── IF no_assignment: Show "Connect to Bus" overlay on map
  │     ├── Option A: Enter tracking code (driver shares it)
  │     └── Option B: Scan QR code (future)
  └── Settings drawer: profile, notifications, logout
```

### Driver App Flow
```
Login → Map Screen (full-screen, edge-to-edge)
  ├── IF has_assignment: Show route stops on map + broadcast controls
  │     ├── "Start Broadcasting" FAB → begins GPS sharing
  │     ├── Share code card (appears after start) → give to parents
  │     └── Stats overlay: speed, pings sent, parents connected, trip time
  ├── IF no_assignment: Show "Contact school admin" message
  └── Settings drawer: profile, bus info, logout
```

### Key Change from v2
- **DELETED**: Home screen with route list (Route 1, Route 2, Route 3 garbage)
- **DELETED**: Route selection page
- **NEW**: Map is the FIRST and ONLY screen after login
- **NEW**: Parent-Driver connection via tracking codes
- **NEW**: Manual test mode — driver shares code, parent enters it

---

## 3. NEPAL BUS NUMBERING SYSTEM

In Nepal, buses have physical number plates AND route identifiers.  
School buses use internal numbering assigned by the school.

### Bus Number Format
```
Pattern: [A-Z]{1,3}[0-9]{0,3}
Examples: A, B, C, A1, A2, Ba1, Ka3, Ga12, Bus1, Bus2
```

### Data Model
```
Bus {
  bus_number:    "A1"              // Nepal-style identifier (unique per school)
  license_plate: "Ba 2 Kha 1234"  // Government plate (optional)
  school_id:     "school_001"     // Which school owns this bus
  capacity:      40               // Seats
  active:        true
}

Route {
  route_id:     "route_001"
  school_id:    "school_001"
  bus_number:   "A1"              // Which bus runs this route
  name:         "Baneshwor → Patan School"
  stops:        [...]             // Ordered list of stops
}

Assignment {
  parent_id:    "parent1"
  student_name: "Ram Sharma"
  bus_number:   "A1"
  route_id:     "route_001"
  school_id:    "school_001"
}
```

### For MVP Testing (No School Admin Yet)
Routes are NOT managed yet. The connection happens via **tracking codes**:
1. Driver starts broadcasting → gets code "XK7M2P"
2. Driver tells parent the code (WhatsApp, verbal, etc.)
3. Parent enters code → connects to driver's live GPS
4. Parent sees bus on map in real-time

---

## 4. LOCATION TRACKING ARCHITECTURE

### GPS Strategy: GPS Primary, Network Secondary

```
┌─────────────────────────────────────────────────┐
│                  DRIVER PHONE                    │
│                                                  │
│  ┌──────────────┐   ┌───────────────────┐       │
│  │   GPS/GNSS   │   │ Fused Location    │       │
│  │  (Primary)   │──▶│ Provider (Android) │       │
│  │              │   │ Core Location (iOS)│       │
│  └──────────────┘   └────────┬──────────┘       │
│  ┌──────────────┐            │                   │
│  │ Wi-Fi/Cell   │────────────┘                   │
│  │ (Secondary)  │     fused lat/lng/speed/       │
│  └──────────────┘     bearing/accuracy/ts        │
│                              │                   │
│                    ┌─────────▼─────────┐         │
│                    │  Kalman Filter    │         │
│                    │  (client-side)    │         │
│                    │  smooths noise    │         │
│                    └─────────┬─────────┘         │
│                              │                   │
│            ┌─────────────────┼──────────┐        │
│            │ Network OK?     │          │        │
│            │    YES          │  NO      │        │
│            ▼                 ▼          │        │
│   ┌────────────┐    ┌──────────────┐   │        │
│   │ Send via   │    │ Buffer in    │   │        │
│   │ HTTP POST  │    │ local SQLite │   │        │
│   │ /api/gps   │    │ (offline Q)  │   │        │
│   └────────────┘    └──────────────┘   │        │
│                      replay on reconn   │        │
└─────────────────────────────────────────────────┘

                         │
                         ▼ (network)
                         
┌─────────────────────────────────────────────────┐
│                   BACKEND                        │
│                                                  │
│   POST /api/gps-update                           │
│         │                                        │
│         ▼                                        │
│   ┌──────────┐   ┌───────────┐   ┌───────────┐ │
│   │ Validate │──▶│ Redis     │──▶│ WebSocket │ │
│   │ & Store  │   │ GEOADD +  │   │ Pub/Sub   │ │
│   │          │   │ location  │   │ broadcast │ │
│   └──────────┘   │ hash      │   └─────┬─────┘ │
│                   └───────────┘         │       │
│                                         ▼       │
│                                 ┌──────────┐    │
│                                 │ Parent   │    │
│                                 │ WS conn  │    │
│                                 │ receives │    │
│                                 │ position │    │
│                                 └──────────┘    │
└─────────────────────────────────────────────────┘
```

### Location Update Rules

| State | Interval | Accuracy | Battery |
|-------|----------|----------|---------|
| Active trip (foreground) | 3-5 sec | HIGH_ACCURACY | High (OK) |
| Active trip (background) | 5-10 sec | HIGH_ACCURACY | Medium |
| Driver idle, app open | 15-30 sec | BALANCED | Low |
| App closed | Stop updates | — | Zero |

### Anti-Jitter: Kalman Filter (Client-Side)

The driver app MUST apply a Kalman filter before sending coordinates:
```
Prediction: x̂ₖ = Fxₖ₋₁ + Buₖ   (motion model: last pos + velocity × dt)
Update:     Kₖ = Pₖ(Pₖ + R)⁻¹   (Kalman gain)
Correction: x̂ₖ = x̂ₖ + Kₖ(zₖ - x̂ₖ)  (blend prediction with GPS)

Where:
  R = measurement noise (set from GPS accuracy/HDOP)
  Higher GPS accuracy → lower R → trust GPS more
  Lower GPS accuracy  → higher R → trust prediction more
```

### Nepal-Specific GPS Notes
- **Hills**: GPS works BETTER than network (open sky). Network is spotty.
- **Valleys**: GPS multipath interference from hillsides → increase Kalman R
- **Budget phones**: Many drivers use budget phones. Multi-GNSS helps (GPS+GLONASS+BeiDou)
- **Offline buffering is NOT optional**: Network drops in hills. Buffer ALL points locally.

---

## 5. MAP IMPLEMENTATION REQUIREMENTS

### Bugs to Fix (from user feedback)
1. **Zoom in/out buttons look identical** — icons are the same
2. **Map freezes, can't go back** — likely gesture conflict with FlutterMap
3. **Page becomes unresponsive on map** — animation or rebuild performance issue

### Map Architecture Rules
1. **Edge-to-edge map** — no AppBar, map fills entire screen
2. **Floating controls** — back button, zoom, re-center as floating glass buttons
3. **Zoom buttons**: `+` and `−` text (not icons), positioned right side, vertical stack
4. **Gesture handling**: Map gestures must NOT block system back gesture
5. **WillPopScope/PopScope**: Must wrap screen to handle back button correctly
6. **Performance**: 
   - `tracksViewChanges: false` equivalent — don't rebuild markers every frame
   - Limit marker rebuilds to when position actually changes
   - Use `RepaintBoundary` around marker widgets
7. **Smooth marker animation**: Interpolate between GPS points over 500-1000ms
8. **Map controller disposal**: Properly dispose MapController to prevent memory leaks

### Tile Layer
- OSM tiles via FMTC (Flutter Map Tile Caching) — already implemented
- Offline-first: serve from cache, fetch from network only when stale

---

## 6. DRIVER ↔ PARENT CONNECTION FLOW

### Method 1: Tracking Code (MVP — implement now)
```
Driver                              Parent
  │                                    │
  │ 1. Tap "Start Broadcasting"        │
  │    POST /api/tracking/start        │
  │    Response: { code: "XK7M2P" }    │
  │                                    │
  │ 2. Share code via WhatsApp/verbal  │
  │ ──────────────────────────────────▶│
  │                                    │
  │                     3. Enter code  │
  │                     POST /api/tracking/join/XK7M2P
  │                     Response: { bus_number, driver_name, ws_url }
  │                                    │
  │ 4. GPS broadcasting via            │
  │    POST /api/gps-update            │
  │         │                          │
  │         ▼                          │
  │    Redis pub/sub ─────────────────▶│ 5. WebSocket receives
  │                                    │    live position updates
  │                                    │
  │ 6. Tap "Stop Broadcasting"         │
  │    POST /api/tracking/stop         │
  │    ──▶ Redis cleanup               │
  │    ──▶ WS sends { type: "ended" }  │
  │                                    │ 7. Shows "Trip ended" overlay
```

### Method 2: School Admin Assignment (Phase 2 — design now, implement later)
```
Admin Dashboard
  │
  ├── Create School
  ├── Add Buses: A1, A2, B1, B2, Ka1...
  ├── Add Routes: route stops per bus
  ├── Assign Students to Buses
  │     └── student "Ram" → bus "A1" → parent "parent1"
  │
  └── Parent logs in → auto-assigned → sees bus "A1" on map
```

### Method 3: Deep Link Sharing (Phase 2)
```
Driver shares: https://bustrack.app/track/XK7M2P
  → Opens app if installed
  → Falls back to web view if not
```

---

## 7. API CONTRACT v3

### Authentication
| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| POST | `/api/auth/login` | None | `{username, password, role}` | `{access_token, token_type, role}` |

### Tracking (NEW — replaces old share API)
| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| POST | `/api/tracking/start` | Bearer (driver) | `{bus_number}` | `{tracking_code, expires_at}` |
| POST | `/api/tracking/stop` | Bearer (driver) | — | `{status: "stopped"}` |
| POST | `/api/tracking/join/{code}` | Bearer (parent) | — | `{bus_number, driver_name, ws_url}` |
| GET | `/api/tracking/status` | Bearer (any) | — | `{is_tracking, tracking_code, bus_number, connected_parents}` |
| POST | `/api/gps-update` | Bearer (driver) | `{lat, lng, speed, bearing, accuracy, ts, bus_number}` | `{status: "ok"}` |

### Bus Management (for future admin, but backend ready now)
| Method | Path | Auth | Body | Response |
|--------|------|------|------|----------|
| GET | `/api/bus/{bus_number}` | Bearer | — | `{bus_number, school_id, active}` |
| GET | `/api/driver/assignment` | Bearer (driver) | — | `{bus_number, route_id, route_name}` |

### WebSocket
| Path | Auth | Direction | Frame Types |
|------|------|-----------|-------------|
| `/ws/track/{tracking_code}?token=JWT` | Via URL | Server→Client | `position`, `eta`, `geofence_alert`, `ended`, `ping/pong` |

### WebSocket Frame Shapes
```json
// Server → Client: Live position
{
  "type": "position",
  "bus_number": "A1",
  "lat": 27.7172,
  "lng": 85.3240,
  "speed": 35.0,
  "bearing": 180.0,
  "accuracy": 8.5,
  "ts": 1716912000
}

// Server → Client: ETA to next stop
{
  "type": "eta",
  "bus_number": "A1",
  "next_stop": "Baneshwor Chowk",
  "distance_m": 1200,
  "duration_s": 240
}

// Server → Client: Tracking session ended
{
  "type": "ended",
  "reason": "driver_stopped"
}

// Server → Client: Parent count update
{
  "type": "parents_count",
  "count": 3
}
```

---

## 8. BACKEND ARCHITECTURE

### Redis Keys (Hot Data)
```
tracking:{code}:info          HASH  {driver_id, bus_number, started_at, expires_at}
tracking:{code}:location      HASH  {lat, lng, speed, bearing, accuracy, ts}  TTL=30s
tracking:{code}:parents       SET   {parent_id_1, parent_id_2, ...}
driver:{driver_id}:active     STRING  tracking_code  TTL=3600s
bus:{bus_number}:location      HASH  {lat, lng, speed, bearing, ts}  TTL=60s
```

### PostgreSQL Tables
```sql
-- Tracking sessions (audit log)
CREATE TABLE tracking_sessions (
  id            SERIAL PRIMARY KEY,
  tracking_code VARCHAR(8) UNIQUE NOT NULL,
  driver_id     VARCHAR(100) NOT NULL,
  bus_number    VARCHAR(20) NOT NULL,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at      TIMESTAMPTZ,
  expires_at    TIMESTAMPTZ NOT NULL,
  active        BOOLEAN NOT NULL DEFAULT TRUE
);

-- GPS history (for analytics, replay, debugging)
CREATE TABLE gps_history (
  id          BIGSERIAL PRIMARY KEY,
  bus_number  VARCHAR(20) NOT NULL,
  driver_id   VARCHAR(100) NOT NULL,
  lat         DOUBLE PRECISION NOT NULL,
  lng         DOUBLE PRECISION NOT NULL,
  speed       REAL DEFAULT 0,
  bearing     REAL DEFAULT 0,
  accuracy    REAL DEFAULT 0,
  recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_gps_history_bus ON gps_history(bus_number, recorded_at DESC);

-- Future: school, bus, route, assignment tables
```

### Validation Rules (Anti-Abuse)
1. GPS point with speed > 200 km/h → reject (bus can't go that fast)
2. GPS point > 50km from last known position in < 10s → reject (teleportation)
3. GPS accuracy > 100m → accept but flag as low-quality
4. Rate limit: max 1 GPS update per 2 seconds per driver
5. Tracking code expires after 4 hours (configurable)
6. Max 50 parents per tracking session

---

## 9. SCALABILITY DESIGN

### Current Scale (MVP)
- 1 school, 3-5 buses, 10-20 parents
- Single Docker Compose stack
- Redis + PostgreSQL + FastAPI on one machine

### Target Scale (Production)
- 100 schools, 1000 buses, 50k parents
- Horizontal scaling via:

```
Load Balancer (nginx/HAProxy)
    │
    ├── API Server 1 (stateless FastAPI)
    ├── API Server 2 (stateless FastAPI)
    ├── API Server 3 (stateless FastAPI)
    │
    ├── WebSocket Server 1 (sticky sessions by tracking_code)
    ├── WebSocket Server 2
    │
    └── Redis Cluster (pub/sub for cross-server WS broadcast)
         └── PostgreSQL (read replicas for analytics)
```

### Why This Scales
- **GPS ingestion is HTTP POST** → stateless, can load-balance freely
- **Redis pub/sub** for WS broadcast → any WS server can relay to its connected parents
- **Tracking codes are ephemeral** → Redis TTL handles cleanup automatically
- **GPS history writes are async** → can be batched or queued without blocking response
- **No shared state in API servers** → scale horizontally with zero coordination

---

## 10. AGENT ASSIGNMENTS

Three agents will implement this system in parallel:

| Agent | Role | Task File | Scope |
|-------|------|-----------|-------|
| **Agent 1** | Flutter UI Architect | `TASK_AGENT_1_FLUTTER.md` | Map-first UI, tracking screen, driver broadcast UI, parent join UI, Kalman filter |
| **Agent 2** | Backend API Engineer | `TASK_AGENT_2_BACKEND.md` | Tracking API endpoints, GPS ingestion, Redis storage, PostgreSQL schema |
| **Agent 3** | Real-Time Systems Engineer | `TASK_AGENT_3_REALTIME.md` | WebSocket server, Redis pub/sub, live broadcast pipeline, connection management |

### Dependency Graph
```
Agent 2 (Backend API) ──────┐
                             ├──▶ Agent 1 (Flutter) can test against API
Agent 3 (WebSocket)  ───────┘
                             
Agent 2 and Agent 3 can work in PARALLEL (separate files)
Agent 1 depends on API contract (defined above) — can mock initially
```

---

## 11. ENVIRONMENT

- **Workspace**: `/home/raderex/Documents/bustrack`
- **Backend**: Docker at `http://localhost:8000`
- **Flutter SDK**: `/home/raderex/flutter/bin/flutter`
- **Flutter app**: `/home/raderex/Documents/bustrack/flutter`
- **Backend code**: `/home/raderex/Documents/bustrack/backend`
- **Waydroid IP**: `192.168.240.1:8000` (for local testing)
- **Apps are currently UNINSTALLED** — will rebuild after implementation

---

## 12. CONSTRAINTS (NON-NEGOTIABLE)

1. **NEVER** show a route list/selection page. Map is first screen after login.
2. **NEVER** hardcode routes in the Flutter app. Routes come from backend.
3. **NEVER** use `allow_origins=["*"]` in CORS.
4. **NEVER** commit .env or secrets to git.
5. **ALWAYS** use Kalman filter on GPS before sending to server.
6. **ALWAYS** buffer GPS offline and replay on reconnection.
7. **ALWAYS** handle back button on map screen — it must not freeze.
8. **ALWAYS** dispose MapController and animation controllers properly.
9. **ALWAYS** validate GPS data server-side (speed, distance, accuracy checks).
10. **ALWAYS** run `flutter analyze` — target 0 errors.

---

## 13. CHANGE LOG

### [2026-05-28] — Architect: Antigravity (v3 Redesign)
- Complete architecture redesign: map-first, no route selection
- New tracking code system for driver-parent connection
- GPS architecture: GPS primary, network secondary, Kalman filter, offline buffer
- Nepal bus numbering system support (A, A1, Ba2, Ka3, etc.)
- New API contract v3 with /api/tracking/* endpoints
- Scalability design for 100+ schools
- 3 agent task files created with detailed prompts and roles
- Fixed map UX issues: zoom buttons, back button, gesture handling
