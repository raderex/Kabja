# ⬡ Kabja — Run. Capture. Dominate.
**Territory Running App for Nepal — Claim the streets you run.**

Kabja turns every run into a strategy game. Run through streets to capture H3 hex territory cells. Compete with other runners. Connect Strava to auto-import your activities. Built with a fully self-hosted, zero-Google stack.

Inspired by [INTVL](https://www.intvl.com.au/) — adapted for Nepal.

---

## Architecture

```
Flutter App (Android + iOS)
├── Run Screen        ── GPS tracking → POST /api/run-update (3s interval)
├── Territory Map     ── WSS /ws/{user_id} (nearby runners + territory)
├── Competition       ── GET /api/competitions
├── Profile           ── Strava OAuth + stats
│
FastAPI Backend (Python 3.12)
├── JWT Auth          POST /api/auth/login
├── Run Lifecycle     POST /api/run/start → /api/run-update → /api/run/finish
├── Territory Engine  H3 hex cell claiming (resolution 10)
├── Strava OAuth      GET /api/strava/auth-url → callback → sync
├── Leaderboard       GET /api/leaderboard
├── Competitions      GET /api/competitions + cron snapshot
├── WS Manager        /ws/{user_id} (live stats, nearby runners, sync events)
│
┌──────────────────────────────────────────────────────┐
│  Redis 7          — GPS state, sessions, TTL 30s     │
│  PostgreSQL 16    — users, runs, cells, competitions │
│  OSRM             — Nepal road-snap (foot profile)   │
│  Nginx            — SSL termination, WS proxy        │
└──────────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone
git clone git@github.com:raderex/OpenBus.git kabja
cd kabja

# 2. Configure
cp .env.example .env    # edit secrets + Strava credentials

# 3. OSRM data (one-time, ~1.5GB)
wget https://download.geofabrik.de/asia/nepal-latest.osm.pbf -P osrm_data/

# 4. Launch
docker compose up -d

# 5. Verify
curl http://localhost:8000/health
```

## Features

### Core
- ⬡ **Territory Capture** — Run through streets to claim H3 hex cells (resolution 10, ~15k m² each)
- 🏃 **Live Run Tracking** — Real-time GPS with distance, pace, duration stats
- 🗺️ **Territory Map** — See your claimed territory + nearby runners on OpenFreeMap tiles
- 🏆 **Competitions** — Time-boxed territory competitions with leaderboard snapshots
- 📊 **Leaderboard** — Global ranking by km² of territory owned

### Strava Integration
- 🔗 **Connect Strava** — OAuth 2.0 flow from within the app
- 🔄 **Auto-Sync** — Import past activities to claim territory retroactively
- 📡 **Webhooks** — New Strava activities auto-imported in real-time
- 🔌 **Disconnect** — Clean unlinking with Strava deauthorization

### Technical
- 🚀 **Zero Google APIs** — OpenFreeMap tiles, self-hosted OSRM, no proprietary dependencies
- ⚡ **Real-time** — WebSocket-based live updates (stats, nearby runners, sync events)
- 🛣️ **Road Snap** — OSRM matches raw GPS traces to road network
- 🔐 **JWT Auth** — Stateless HS256 tokens, secure storage on device
- 📱 **Background GPS** — Foreground service survives screen-off on both platforms
- 🐳 **Docker Stack** — One `docker compose up` to run everything

## File Structure

```
kabja/
├── docker-compose.yml              # Full stack orchestration
├── .env                            # Secrets (gitignored)
├── ARCHITECTURE.md                 # System design & component overview
├── AGENT_BACKEND.md                # Backend engineer task spec
├── AGENT_FRONTEND.md               # Frontend engineer task spec
├── AGENT_REALTIME.md               # Realtime engineer task spec
│
├── backend/
│   ├── main.py                     # FastAPI app (auth, run lifecycle, WS, Strava routes)
│   ├── strava.py                   # Strava OAuth + activity sync + webhook handler
│   ├── territory.py                # H3 hex cell engine (process_run → claim cells)
│   ├── cron.py                     # Competition snapshot job (hourly)
│   ├── db.py                       # Async PostgreSQL (SQLAlchemy + asyncpg)
│   ├── migrations/                 # Alembic migrations
│   │   └── versions/
│   │       ├── 001_initial_schema.py
│   │       └── 002_strava_integration.py
│   ├── services/
│   │   ├── ws_broadcast.py         # Tracking WebSocket broadcaster
│   │   ├── tracking_manager.py     # GPS validation + storage
│   │   ├── share_manager.py        # Location sharing sessions
│   │   └── ...
│   ├── Dockerfile
│   └── requirements.txt
│
├── flutter/
│   ├── pubspec.yaml
│   └── lib/
│       ├── main.dart               # App entry, router, theme, bottom nav (4 tabs)
│       ├── core/
│       │   ├── auth/               # JWT auth provider + secure storage
│       │   ├── config/             # API base URLs
│       │   ├── network/            # RunRepository, StravaRepository, WS manager
│       │   └── strava/             # StravaProvider, deep link handler
│       └── features/
│           ├── run/                # Run screen (start/pause/finish + live stats)
│           ├── map/                # Territory map, leaderboard panel
│           ├── competition/        # Prize carousel + countdown
│           └── profile/            # User profile + Strava integration UI
│
├── nginx/                          # SSL termination, WS proxy
├── osrm_data/                      # Nepal OSM data for routing
└── scripts/                        # Setup & deployment scripts
```

## API Endpoints

### Authentication
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/auth/login` | — | JWT token generation |

### Run Lifecycle
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `POST` | `/api/run/start` | Bearer | Create run session, returns `run_id` |
| `POST` | `/api/run-update` | Bearer | GPS update (hot path, Redis only) |
| `POST` | `/api/run/finish` | Bearer | End run → territory engine |
| `GET`  | `/api/run/{run_id}/location` | Bearer | Get live run position |

### Territory & Leaderboard
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET`  | `/api/territory/{user_id}` | — | H3 cells owned by user |
| `GET`  | `/api/leaderboard` | — | Top runners by km² |
| `GET`  | `/api/competitions` | Bearer | Active + upcoming competitions |

### Strava Integration
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| `GET`  | `/api/strava/auth-url` | Bearer | Get Strava OAuth URL |
| `GET`  | `/api/strava/callback` | — | OAuth callback (exchanges code → tokens) |
| `GET`  | `/api/strava/status` | Bearer | Connection status + profile |
| `POST` | `/api/strava/sync` | Bearer | Trigger manual activity import |
| `GET`  | `/api/strava/sync-status` | Bearer | Check if sync is running |
| `DELETE` | `/api/strava/disconnect` | Bearer | Unlink Strava account |
| `GET`  | `/api/strava/webhook` | — | Webhook subscription verification |
| `POST` | `/api/strava/webhook` | — | Webhook event receiver |

### WebSocket
| Endpoint | Description |
|----------|-------------|
| `WS /ws/{user_id}` | Live stats, nearby runners, territory results, Strava sync events |

**WS message types:**
```json
{ "type": "position",          "payload": { "run_id", "lat", "lng", "speed", "bearing" } }
{ "type": "stats",             "payload": { "distance_km", "duration_s", "pace_min_km", "speed_ms" } }
{ "type": "territory_result",  "payload": { "cells_captured", "km2_captured", "cells_lost" } }
{ "type": "strava_sync",       "payload": { "activity_name", "cells_captured", "km2_captured", "source" } }
{ "type": "strava_sync_status","payload": { "status": "syncing" | "complete" } }
```

## Configuration

```bash
# ── Core ──────────────────────────────────────────────
REDIS_PASSWORD=your_strong_redis_password
JWT_SECRET=your_256bit_secret_key
POSTGRES_PASSWORD=your_postgres_password

# ── Public URL ────────────────────────────────────────
PUBLIC_URL=https://yourdomain.com

# ── Strava OAuth ──────────────────────────────────────
STRAVA_CLIENT_ID=your_strava_client_id
STRAVA_CLIENT_SECRET=your_strava_client_secret
STRAVA_REDIRECT_URI=https://yourdomain.com/api/strava/callback
STRAVA_APP_REDIRECT=kabja://strava-callback
STRAVA_WEBHOOK_VERIFY_TOKEN=your_random_verify_token

# ── Telegram OTP (optional) ──────────────────────────
TELEGRAM_BOT_TOKEN=your_bot_token
```

## Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Territory cells | H3 resolution 10 | ~15k m² per cell — good urban granularity |
| Map tiles | OpenFreeMap | Zero API key, no usage limits |
| Routing | OSRM (self-hosted) | Nepal OSM data, foot profile, <10ms snap |
| Real-time | FastAPI WebSockets | Native async, no message broker needed |
| GPS state | Redis HASH + TTL 30s | Sub-ms reads, auto-expiry = offline detection |
| Persistence | PostgreSQL + Alembic | Territory ownership, competitions, Strava tokens |
| Flutter map | flutter_map | Leaflet-based, no Google dependency |
| Auth | JWT HS256 | Stateless, mobile-friendly |
| Strava | OAuth 2.0 + webhooks | Auto-import activities, real-time sync |
| Deep links | `kabja://` scheme | Strava OAuth callback returns to app |

## Tech Stack

**Backend:** Python 3.12 · FastAPI · PostgreSQL 16 · Redis 7 · OSRM · Nginx · Alembic · h3-py · httpx

**Mobile:** Flutter 3.x · Riverpod · flutter_map · geolocator · go_router · google_fonts · shimmer · app_links

**Infrastructure:** Docker Compose · OpenStreetMap · Cloudflare Tunnel (optional)

## Development

**Backend:**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Flutter:**
```bash
cd flutter
flutter pub get
flutter run
# Production: flutter run --dart-define=API_BASE_URL=https://yourdomain.com
```

## Documentation

- [**ARCHITECTURE.md**](ARCHITECTURE.md) — System design & component overview
- [**AGENT_BACKEND.md**](AGENT_BACKEND.md) — Backend engineer task specifications
- [**AGENT_FRONTEND.md**](AGENT_FRONTEND.md) — Frontend engineer task specifications
- [**AGENT_REALTIME.md**](AGENT_REALTIME.md) — Realtime engineer task specifications

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT — build freely, deploy locally, dominate territory.

---

**Made for Nepal** 🇳🇵 | **Kabja** — ⬡ Run. Capture. Dominate.
