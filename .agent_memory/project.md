# KTM School Bus Tracker — Agent Memory

## Project Overview
A school bus tracking system with:
- **FastAPI** backend for API + WebSocket real-time tracking
- **PostgreSQL 16** for trip history and audit trails
- **Redis 7** for caching and pub/sub
- **OSRM v5.27.1** for Nepal routing (data pre-processed in `osrm_data/`)
- **Nginx 1.25** as reverse proxy with SSL, WebSocket support, rate limiting
- **Flutter** mobile app for parents/drivers
- **Certbot** for automatic SSL renewal

## Architecture
```
nginx (443/80) → FastAPI (8000) → PostgreSQL (5432), Redis (6379), OSRM (5000)
```

## Docker Compose Services
| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `nginx` | nginx:1.25-alpine | 80, 443 | Reverse proxy |
| `api` | ./backend/Dockerfile | 8000 | FastAPI application |
| `postgres` | postgres:16-alpine | 5432 | Trip history DB |
| `redis` | redis:7-alpine | 6379 | Cache + pub/sub |
| `osrm` | ghcr.io/project-osrm/osrm-backend:v5.27.1 | 5000 | Nepal routing |
| `certbot` | certbot/certbot | - | SSL renewal |

## Key Environment Variables
Required in `.env`:
- `JWT_SECRET` - JWT signing key
- `REDIS_PASSWORD` - Redis auth
- `POSTGRES_PASSWORD` - PostgreSQL password
- `PUBLIC_URL` - Public domain (e.g., https://bustrack.yourdomain.com)
- `CORS_ORIGINS` - CORS allowed origins
- `OTP_PROVIDER` - `telegram`, `aakash`, or `sparrow`
- `TELEGRAM_BOT_TOKEN` - BotFather token (if telegram OTP)

## Current Status (2026-05-18)
- **OSRM Nepal data pre-processed** in `osrm_data/` with `nepal-latest.osrm.*` files
- OSRM uses **CH (Contraction Hierarchies)** algorithm (not MLD - data wasn't built for MLD)
- Docker compose starts all services: nginx, api, postgres, redis, osrm
- Services running successfully
- Health endpoints: API at `http://localhost:8000/health`, OSRM working at `http://localhost:5000`

## Docker Compose Commands
```bash
# Start all services (use override for local dev)
docker compose -f docker-compose.yml -f docker-compose.override.yml.local up -d

# Stop all services
docker compose -f docker-compose.yml -f docker-compose.override.yml.local down

# View logs
docker compose -f docker-compose.yml -f docker-compose.override.yml.local logs -f

# Check status
docker compose -f docker-compose.yml -f docker-compose.override.yml.local ps
```

## Key Files Changed
- `docker-compose.yml` - CH algorithm, bind mount osrm_data, removed OSRM health check
- `docker-compose.override.yml.local` - **NEW** Local dev without SSL, no port exposures
- `.env` - Environment configuration
- `nginx/nginx.conf` - WebSocket proxy (3600s timeout), rate limiting
- `nginx/nginx.conf.local` - **NEW** Development nginx config without SSL
- `backend/Dockerfile` - Python 3.11 slim base image
- `osrm_data/` - OSRM files renamed to `nepal-latest.osrm.*`

## WebSocket Endpoint
`wss://host/ws/{route_id}?token=<JWT>` - Real-time bus location streaming

## Fixes Applied (2026-05-18)
1. **OSRM files renamed**: `nepal-260517.osrm.*` → `nepal-latest.osrm.*`
2. **OSRM algorithm**: Changed from `mld` to `ch` (data wasn't built for Multi-Level Dijkstra)
3. **OSRM volume**: Changed from named volume to bind mount `./osrm_data:/data`
4. **OSRM health check removed**: Container doesn't have curl/wget
5. **API depends_on OSRM removed**: OSRM not critical for API startup
6. **Override file created**: `docker-compose.override.yml.local` for local dev without SSL