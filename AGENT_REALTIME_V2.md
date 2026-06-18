# AGENT: Realtime Engineer — V2
> **Ship today. Test tonight.**
> You own: WebSocket stability · GPS hot path · live run state · real-time testing.
> The backend Python is written. Your job is to verify it actually works end-to-end and fix anything broken.

---

## Context

The backend is built (FastAPI + Redis + PostgreSQL). The Flutter app has zero Dart files yet — the Frontend Engineer is writing those today. Your job is to make sure the real-time layer is bulletproof before they wire up to it, and to write the test scripts they can run while running.

**Repo:** `https://github.com/raderex/Kabja`
**Your files:** `backend/main.py` · `backend/services/ws_broadcast.py` · `backend/services/tracking_manager.py`

---

## Task 1 — Verify the backend boots cleanly

```bash
cd kabja
cp .env.example .env   # fill in: REDIS_PASSWORD, JWT_SECRET, POSTGRES_PASSWORD, PUBLIC_URL

docker compose up -d postgres redis
docker compose run --rm api alembic upgrade head
docker compose up -d

# Verify all 6 services are Up (not Restarting):
docker compose ps

# Health check:
curl http://localhost:8000/health
# Expected: { "status": "ok" }
```

If any service is in restart loop: `docker compose logs api --tail=50` and fix the error before proceeding.

---

## Task 2 — Audit `backend/main.py` for these exact issues

Open `main.py` and check each of these. Fix anything that's wrong.

### 2a. Verify `/api/run-update` Redis key format
```python
# MUST be:
key = f"run:{payload.run_id}:loc"
await redis.setex(key, 30, json.dumps({...}))

# NOT:
key = f"bus:{payload.bus_id}:loc"   # old format — delete if found
```

### 2b. Verify `/api/run/start` creates session with correct shape
The session stored in Redis MUST have this exact shape — Flutter depends on it:
```python
session = {
    "run_id": run_id,           # UUID string
    "user_id": user_id,         # from JWT
    "status": "active",
    "started_at": "2026-06-02T10:00:00",  # ISO UTC
    "polyline": [],             # [[lat, lng], ...]
    "distance_km": 0.0,
    "last_speed": 0.0,
}
await redis.set(f"run:{run_id}:session", json.dumps(session))
# NO TTL on session key — it must persist until /api/run/finish
```

### 2c. Verify `/api/run/finish` cleans up Redis
After territory processing:
```python
await redis.delete(f"run:{run_id}:loc")      # clean up live GPS
await redis.delete(f"run:{run_id}:session")  # clean up session
```
If these deletes are missing, Redis fills up with dead sessions.

### 2d. Verify WS path is `/ws/{user_id}` NOT `/ws/{route_id}`
```python
# MUST be:
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):

# NOT:
@app.websocket("/ws/{route_id}")   # old bus tracker path — rename if found
```

### 2e. Verify WS sends `stats` message every 5 seconds
There must be an asyncio task that pushes to the runner's WS connection:
```python
{
    "type": "stats",
    "payload": {
        "distance_km": float,
        "duration_s": int,
        "pace_min_km": float,
        "speed_ms": float,
    }
}
```
If this loop is missing or broken, the Flutter run screen will never update live stats.

### 2f. Verify WS sends `position` for nearby runners
```python
{
    "type": "position",
    "payload": {
        "run_id": str,
        "lat": float,
        "lng": float,
        "speed": float,
        "bearing": float,
    }
}
```

### 2g. Verify `territory_result` is pushed after finish
After `process_run()` completes in the background task:
```python
await websocket.send_text(json.dumps({
    "type": "territory_result",
    "payload": {
        "cells_captured": int,
        "km2_captured": float,
        "cells_lost": int,      # MUST NOT be hardcoded 0
    }
}))
```

---

## Task 3 — Fix `cells_lost` (currently hardcoded 0)

In `backend/territory.py`, find `process_run()`. The return currently has:
```python
return {"cells_captured": N, "km2_captured": X, "cells_lost": 0}  # BUG
```

Fix it by querying cells the user previously owned that are now owned by someone else:
```python
async def _get_cells_lost(user_id: str, since: str) -> int:
    """Count cells that were owned by user but stolen since their last run."""
    async with AsyncSessionLocal() as db:
        result = await db.execute("""
            SELECT COUNT(*) FROM cells
            WHERE run_id IN (
                SELECT id FROM runs WHERE user_id = :uid
            )
            AND owner_id != :uid
        """, {"uid": user_id})
        row = result.fetchone()
        return row[0] if row else 0
```

Call this in `process_run()` and return the real number.

---

## Task 4 — Add Strava import timestamp guard

In `backend/territory.py` `claim_cells()`, add the timestamp check to prevent old Strava imports from overwriting fresh live runs:

```python
# In the ON CONFLICT upsert, change to:
await db.execute("""
    INSERT INTO cells (h3_index, owner_id, captured_at, run_id)
    VALUES (:h3, :uid, :ts, :rid)
    ON CONFLICT (h3_index) DO UPDATE
    SET owner_id = EXCLUDED.owner_id,
        captured_at = EXCLUDED.captured_at,
        run_id = EXCLUDED.run_id
    WHERE cells.captured_at < EXCLUDED.captured_at
""", {"h3": cell_id, "uid": user_id, "ts": run_finished_at, "rid": run_id})
```

Pass `run_finished_at` (from `session["finished_at"]`) into `claim_cells()`. This one WHERE clause prevents Strava retroactive imports from stealing live territory.

---

## Task 5 — Write the realtime test script

Create `scripts/test_realtime.sh` — this is what the team runs while physically testing tomorrow:

```bash
#!/bin/bash
# scripts/test_realtime.sh
# Usage: bash scripts/test_realtime.sh
# Run this while someone is doing a test run on the app

BASE="http://localhost:8000"

echo "=== Kabja Realtime Test ==="

# 1. Get auth token
echo -e "\n[1] Getting auth token..."
TOKEN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"testrunner","password":"test123"}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('access_token','FAILED'))")
echo "Token: ${TOKEN:0:30}..."

# 2. Start a run
echo -e "\n[2] Starting run..."
RUN_ID=$(curl -s -X POST "$BASE/api/run/start" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin).get('run_id','FAILED'))")
echo "Run ID: $RUN_ID"

# 3. Send 5 GPS updates (simulating Thamel, Kathmandu)
echo -e "\n[3] Sending GPS updates..."
COORDS=(
  "27.7172 85.3133"
  "27.7178 85.3140"
  "27.7185 85.3148"
  "27.7192 85.3156"
  "27.7199 85.3164"
)
for coord in "${COORDS[@]}"; do
  LAT=$(echo $coord | cut -d' ' -f1)
  LNG=$(echo $coord | cut -d' ' -f2)
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/run-update" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"run_id\":\"$RUN_ID\",\"lat\":$LAT,\"lng\":$LNG,\"speed\":2.5,\"bearing\":90,\"timestamp\":\"$(date -u +%FT%TZ)\"}")
  echo "  GPS update → HTTP $STATUS"
  sleep 1
done

# 4. Finish the run
echo -e "\n[4] Finishing run..."
RESULT=$(curl -s -X POST "$BASE/api/run/finish?run_id=$RUN_ID" \
  -H "Authorization: Bearer $TOKEN")
echo "Result: $RESULT"

# 5. Check territory claimed
echo -e "\n[5] Checking territory..."
USER_ID=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"testrunner","password":"test123"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('user_id',''))")
TERRITORY=$(curl -s "$BASE/api/territory/$USER_ID")
CELL_COUNT=$(echo $TERRITORY | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))")
echo "Cells claimed: $CELL_COUNT"

# 6. Check leaderboard
echo -e "\n[6] Leaderboard..."
curl -s "$BASE/api/leaderboard" | python3 -m json.tool

echo -e "\n=== Test complete ==="
```

```bash
chmod +x scripts/test_realtime.sh
```

---

## Task 6 — Write the WebSocket live monitor

Create `scripts/ws_monitor.py` — run this during a live test run to watch real-time messages:

```python
#!/usr/bin/env python3
# scripts/ws_monitor.py
# Usage: python3 scripts/ws_monitor.py <user_id> <token>

import asyncio
import sys
import json
import websockets
from datetime import datetime

async def monitor(user_id: str, token: str):
    uri = f"ws://localhost:8000/ws/{user_id}"
    print(f"[ws_monitor] Connecting to {uri}")
    print(f"[ws_monitor] Watching for messages... (Ctrl+C to stop)\n")

    try:
        async with websockets.connect(uri) as ws:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=65)
                    msg = json.loads(raw)
                    ts = datetime.now().strftime("%H:%M:%S")
                    mtype = msg.get("type", "unknown")
                    payload = msg.get("payload", {})

                    if mtype == "stats":
                        print(f"[{ts}] STATS — "
                              f"dist: {payload.get('distance_km',0):.3f}km  "
                              f"pace: {payload.get('pace_min_km',0):.1f}min/km  "
                              f"duration: {payload.get('duration_s',0)}s")
                    elif mtype == "position":
                        print(f"[{ts}] NEARBY — run_id: {payload.get('run_id','?')[:8]}  "
                              f"lat: {payload.get('lat',0):.4f}  "
                              f"lng: {payload.get('lng',0):.4f}")
                    elif mtype == "territory_result":
                        print(f"[{ts}] TERRITORY — "
                              f"captured: {payload.get('cells_captured',0)} cells  "
                              f"km2: {payload.get('km2_captured',0):.4f}  "
                              f"lost: {payload.get('cells_lost',0)}")
                    elif mtype == "strava_sync":
                        print(f"[{ts}] STRAVA — {payload.get('activity_name','?')}  "
                              f"cells: {payload.get('cells_captured',0)}")
                    else:
                        print(f"[{ts}] {mtype.upper()} — {payload}")

                except asyncio.TimeoutError:
                    await ws.send("ping")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ping sent")

    except KeyboardInterrupt:
        print("\n[ws_monitor] stopped")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 ws_monitor.py <user_id> <token>")
        sys.exit(1)
    asyncio.run(monitor(sys.argv[1], sys.argv[2]))
```

```bash
# Install deps
pip install websockets

# Run during a live test:
python3 scripts/ws_monitor.py "your-user-id" "your-jwt-token"
```

---

## Task 7 — Nginx WebSocket proxy check

Open `nginx/conf.d/*.conf` and verify these headers exist for the WS proxy block:

```nginx
location /ws/ {
    proxy_pass http://api;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;       # MUST exist
    proxy_set_header Connection "upgrade";         # MUST exist
    proxy_set_header Host $host;
    proxy_read_timeout 86400;                      # 24h — prevents WS timeout
    proxy_send_timeout 86400;
}
```

If `proxy_read_timeout` is missing or set to default (60s), WebSocket connections will silently drop every minute. This will look like the app "disconnecting randomly" during a run.

---

## Task 8 — Abandoned run cleanup

In `backend/cron.py`, add an abandoned session cleanup job alongside the competition snapshot:

```python
async def cleanup_abandoned_runs():
    """
    Find Redis sessions where GPS hasn't updated in 90+ minutes.
    Mark them abandoned so Redis memory doesn't leak.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=90)

    async for key in redis.scan_iter("run:*:session"):
        raw = await redis.get(key)
        if not raw:
            continue
        session = json.loads(raw)
        if session.get("status") != "active":
            continue
        last_gps_key = f"run:{session['run_id']}:loc"
        loc_exists = await redis.exists(last_gps_key)
        if not loc_exists:
            # GPS TTL expired = runner stopped more than 30s ago
            # Check started_at as secondary guard
            started = datetime.fromisoformat(session.get("started_at", "2000-01-01"))
            if started < cutoff:
                session["status"] = "abandoned"
                await redis.set(key, json.dumps(session))
                await redis.delete(last_gps_key)
                print(f"[cron] Abandoned run: {session['run_id']}")

# Add to scheduler:
scheduler.add_job(cleanup_abandoned_runs, "interval", minutes=15, id="run_cleanup")
```

---

## Deliverables checklist

```
□ docker compose ps — all 6 services Up
□ curl /health returns { "status": "ok" }
□ alembic upgrade head — no errors
□ Redis key format: run:{id}:loc (not bus:{id}:loc)
□ WS path: /ws/{user_id}
□ stats pushed every 5s over WS (verified via ws_monitor.py)
□ cells_lost returns real number (not 0)
□ Strava timestamp guard added to claim_cells()
□ scripts/test_realtime.sh runs clean
□ scripts/ws_monitor.py shows live messages
□ Nginx proxy_read_timeout set to 86400
□ Abandoned run cleanup job added to cron.py
```

---

*Realtime Engineer — Kabja V2 — 2026-06-02*
