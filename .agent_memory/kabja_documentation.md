# Kabja — Project Documentation & Memory

> **Last updated:** 2026-06-14 | **Author:** Antigravity Agent

---

## 1. Origin Story

Kabja began life as **KTM School Bus Tracker** (OpenBus) — a school bus GPS tracking system built for Kathmandu, Nepal. The original system allowed:
- **Drivers** to broadcast their bus GPS location via a Flutter app
- **Parents** to track their child's bus in real-time on a map
- **Backend** powered by FastAPI + Redis + OSRM (Nepal road routing)

### Key dates
| Date | Milestone |
|------|-----------|
| 2026-05-18 | Initial Docker Compose setup, OSRM Nepal data processed (CH algorithm) |
| 2026-06-02 | Architecture pivot: Bus Tracker → Territory Running App (INTVL-inspired) |
| 2026-06-09 | Agent task specs written: Backend, Frontend, Realtime engineers |
| 2026-06-14 | First successful APK compile to Waydroid (release mode) |

---

## 2. The Pivot: Bus Tracker → Kabja

Inspired by [INTVL](https://www.intvl.com.au/) (an Australian territory running app), the project was rebranded to **Kabja** ("capture" in Nepali). The core idea:

> Run through streets to claim H3 hex territory cells. Compete with others. Connect Strava.

### What was reused from Bus Tracker
- Flask→FastAPI backend, JWT auth, Redis GPS state, OSRM road-snapping
- Flutter app shell (flutter_map, Riverpod, geolocator, go_router)
- Docker Compose infrastructure (Redis, Nginx, OSRM)
- WebSocket real-time architecture

### What was built new
- **Territory Engine** (`backend/territory.py`) — H3 hex cell claiming via `h3-py`
- **PostgreSQL** — users, runs, cells, competitions tables
- **Strava Integration** (`backend/strava.py`) — OAuth, activity import, webhooks
- **Competition System** — time-boxed competitions with leaderboard snapshots
- **Run Lifecycle** — start → GPS track → finish → OSRM snap → H3 claim

---

## 3. Current Architecture (2026-06-14)

```
Flutter App (Android/Waydroid)
├── RunScreen          — GPS tracking, start/pause/finish
├── TerritoryMapScreen — Map + H3 polygons + nearby runners (WS)
├── CompetitionScreen  — Prize carousel + countdown
├── ProfileScreen      — User info + Strava integration

FastAPI Backend (Python 3.12)
├── Auth (JWT HS256)
├── Run Lifecycle (start → update → finish → territory)
├── Territory Engine (H3 res 10, ~15k m² per cell)
├── Strava (OAuth 2.0, activity import, webhooks)
├── Leaderboard + Competitions
├── WebSocket Manager (/ws/{user_id})

Infrastructure
├── PostgreSQL 16 — persistent data
├── Redis 7 — GPS state, sessions, TTL
├── OSRM — Nepal road-snap (foot profile)
├── Nginx — SSL termination, WS proxy
```

---

## 4. Current State of the Flutter App

### Navigation: Bottom tab bar (4 tabs)
0. **Run** — `RunScreen` (GPS run tracking with start/pause/finish)
1. **Territory** — `TerritoryMapScreen` (map with H3 territory polygons)
2. **Compete** — `CompetitionScreen` (prize carousel + countdown)
3. **Profile** — `ProfileScreen` (user info + Strava)

### Known Issues (as of 2026-06-14)
1. **App opens to Run tab, not Map** — Users expect map-first UX
2. **Map not loading** — `territory_map_screen.dart` uses OpenFreeMap tile URL format that returns vector tiles (not raster PNGs): `https://tiles.openfreemap.org/styles/liberty/{z}/{x}/{y}.png` — this is WRONG; OpenFreeMap style endpoints serve vector tiles, not PNG rasters
3. **Start Run button not working** — Likely API connectivity issue (API_BASE_URL defaults to `localhost:8000`, which won't work on Waydroid)
4. **No navigation drawer** — The old `map_screen.dart` had a proper drawer with settings; the new `territory_map_screen.dart` is minimal
5. **No mobile menu / hamburger** — Missing top-left menu for accessing all modules
6. **Old bus tracker code still present** — `map_screen.dart`, `broadcast_provider.dart`, `tracking_provider.dart` etc. are legacy
7. **Territory not loading on map open** — Territory is loaded but map tiles may fail first

### Product Flavors
- `parent` — `com.ktmbustrack.parent` (KTM School Bus)
- `driver` — `com.ktmbustrack.driver` (KTM Bus Driver)
- Both flavors still reference old bus-tracker branding

### Build Config
- Android Gradle: `build.gradle.kts` with Kotlin DSL
- Namespace fixes applied in root `build.gradle.kts` for h3_flutter
- NDK minSdk suppression in `gradle.properties`
- CMake version override (3.18.1 → 3.22.1) for h3_flutter native lib

---

## 5. Agent Task Specs

Three `.md` files define tasks for specialist agents:

| File | Agent | Focus |
|------|-------|-------|
| `AGENT_BACKEND.md` | Backend Engineer | Strava OAuth, DB migrations, territory engine |
| `AGENT_FRONTEND.md` | Frontend Engineer | UI/UX modernization, Strava UI, Profile screen |
| `AGENT_REALTIME.md` | Realtime Engineer | WebSocket push, Redis sync status, GPS ingest |

---

## 6. Design Language

- **Theme**: Dark, premium, sport-tech (Nike Run Club meets strategy game)
- **Colors**: Amber/gold accent (#FFB300) on deep black (#0A0A0F)
- **Typography**: Inter (Google Fonts), weight 600-900
- **Cards**: Glassmorphism with `BackdropFilter`, 20px border radius
- **Animations**: flutter_animate, pulsing dots for live state, shimmer loading
- **Reference**: INTVL app aesthetic
