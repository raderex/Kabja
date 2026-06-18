# AGENT 2 — Backend API Engineer (v3.1 — Feature Completeness Pass)

## Agent Profile
- **Role**: Senior Python/FastAPI Backend Engineer
- **Codename**: Agent 2 — Backend API Engineer
- **Scope**: `backend/main.py`, `backend/services/tracking_manager.py`
- **Dependencies**: None (can start immediately)

## Context (READ FIRST)
The backend is running in Docker and is healthy at `http://localhost:8000`. Redis, PostgreSQL, OSRM are all up. The tracking API from v3.0 is already implemented. This pass adds missing features and fixes functional gaps.

## What's Already Working
- ✅ `POST /api/tracking/start` → returns tracking code
- ✅ `POST /api/tracking/stop` → stops broadcast
- ✅ `POST /api/tracking/join/{code}` → parent joins session
- ✅ `GET /api/tracking/status` → returns status for driver
- ✅ `POST /api/gps-update` → validates + stores GPS + Redis pub/sub
- ✅ `POST /api/gps-update/batch` → offline replay
- ✅ `GET /health` → health check
- ✅ `POST /api/auth/login` → authentication

## Issues Found / Missing Features

1. ❌ `POST /api/tracking/join/{code}` returns `driver_id` but **no `driver_name`** — parent app shows "—" for driver name
2. ❌ `/api/gps-update` response is `202 Accepted` but **no Redis pub/sub publish when not in tracking session** — GPS updates for drivers in idle mode are stored but not broadcast
3. ❌ **No `GET /api/tracking/join/{code}/info`** — parent needs to get session info (bus number, driver name) before subscribing to WS
4. ❌ **No driver name in user data** — login only returns `access_token`, no user profile
5. ❌ **`/api/tracking/status` only works for drivers** — parent needs to know their active session status too
6. ❌ **Health endpoint missing WebSocket stats** — Agent 3 added the broadcaster but `/health` doesn't expose WS metrics

---

## Task List

### T1: Fix `join_tracking` — Return Driver Name
**Priority**: 🔴 CRITICAL
**File**: `backend/services/tracking_manager.py`

The `join_tracking` function returns `driver_id` but not `driver_name`. The Flutter parent app displays driver name in the bottom sheet — currently always shows "—".

**Problem**: We store `driver_id` in Redis but not `driver_name`. Driver name comes from the user store.

**Fix**: Add `driver_name` lookup from Redis user store when joining:

```python
async def join_tracking(
    r: aioredis.Redis,
    tracking_code: str,
    parent_id: str,
) -> dict | None:
    code = tracking_code.strip().upper()
    info = await r.hgetall(f"tracking:{code}:info")
    if not info:
        return None

    def _decode(val):
        return val.decode() if isinstance(val, bytes) else val

    decoded = {_decode(k): _decode(v) for k, v in info.items()}

    expires_at = datetime.fromisoformat(decoded["expires_at"])
    if datetime.now(tz=timezone.utc) > expires_at:
        return None

    parent_count = await r.scard(f"tracking:{code}:parents")
    if parent_count >= MAX_PARENTS_PER_SESSION:
        return None

    await r.sadd(f"tracking:{code}:parents", parent_id)
    new_count = await r.scard(f"tracking:{code}:parents")

    driver_id = decoded["driver_id"]
    
    # Look up driver's display name from user hash in Redis
    # Users are stored as: user:{username}:data HASH {role, display_name, ...}
    # Try multiple Redis key patterns used by the auth system
    driver_name = None
    
    # Pattern 1: user data hash
    user_data = await r.hgetall(f"user:{driver_id}:data")
    if user_data:
        raw_name = user_data.get(b"display_name") or user_data.get("display_name")
        if raw_name:
            driver_name = raw_name.decode() if isinstance(raw_name, bytes) else raw_name
    
    # Pattern 2: Fall back to username (the driver_id itself)
    if not driver_name:
        driver_name = driver_id.replace("_", " ").title()

    log.info("Parent joined: code=%s parent=%s total=%d driver=%s", 
             code, parent_id, new_count, driver_name)
    
    return {
        "bus_number": decoded["bus_number"],
        "driver_id": driver_id,
        "driver_name": driver_name,
        "tracking_code": code,
        "connected_parents": new_count,
    }
```

---

### T2: Add `GET /api/tracking/info/{code}` Endpoint (Public — No Auth Required for Code Check)
**Priority**: 🔴 CRITICAL
**File**: `backend/main.py`

Parents need to verify a code is valid before joining. The current `/api/tracking/join/{code}` is a `POST` that also joins — there's no lightweight info check. Add:

```python
@app.get("/api/tracking/info/{tracking_code}", tags=["tracking"])
async def tracking_info(tracking_code: str) -> dict:
    """
    Get basic info about a tracking session by code.
    Does NOT add the parent to the session (use POST join for that).
    Returns 404 if code is invalid or expired.
    """
    code = tracking_code.strip().upper()
    info = await app.state.redis.hgetall(f"tracking:{code}:info")
    if not info:
        raise HTTPException(status_code=404, detail="Invalid or expired tracking code")

    def _d(v):
        return v.decode() if isinstance(v, bytes) else v

    decoded = {_d(k): _d(v) for k, v in info.items()}

    expires_at_str = decoded.get("expires_at", "")
    try:
        from datetime import datetime, timezone
        expires_at = datetime.fromisoformat(expires_at_str)
        if datetime.now(tz=timezone.utc) > expires_at:
            raise HTTPException(status_code=404, detail="Tracking session expired")
    except ValueError:
        pass

    parent_count = await app.state.redis.scard(f"tracking:{code}:parents")

    return {
        "bus_number": decoded.get("bus_number", ""),
        "started_at": decoded.get("started_at", ""),
        "expires_at": expires_at_str,
        "connected_parents": parent_count,
    }
```

---

### T3: Fix `/api/tracking/status` to Work for Parents
**Priority**: 🟡 MEDIUM
**File**: `backend/main.py` + `backend/services/tracking_manager.py`

Currently `get_tracking_status` looks up `driver:{id}:active` — only works for drivers. Parents need to know their active session too. Parents store their tracking code in SharedPreferences client-side, but the server should also be able to confirm.

**Add parent tracking status** to `get_tracking_status`:

```python
async def get_tracking_status(r: aioredis.Redis, user_id: str, role: str = "driver") -> dict:
    """Get current tracking status for a user (driver or parent)."""
    
    if role == "driver":
        code = await r.get(f"driver:{user_id}:active")
        if not code:
            return {"is_tracking": False, "role": "driver"}
        code = code if isinstance(code, str) else code.decode()
        parent_count = await r.scard(f"tracking:{code}:parents")
        info = await r.hgetall(f"tracking:{code}:info")
        def _decode(val):
            return val.decode() if isinstance(val, bytes) else val
        decoded = {_decode(k): _decode(v) for k, v in info.items()} if info else {}
        return {
            "is_tracking": True,
            "role": "driver",
            "tracking_code": code,
            "bus_number": decoded.get("bus_number", ""),
            "connected_parents": parent_count,
            "started_at": decoded.get("started_at", ""),
            "expires_at": decoded.get("expires_at", ""),
        }
    
    else:  # parent
        # Check if they're in any active session's parents set
        # NOTE: This is a scan — not ideal at scale, but fine for MVP
        code = await r.get(f"parent:{user_id}:active_session")
        if not code:
            return {"is_tracking": False, "role": "parent"}
        code = code if isinstance(code, str) else code.decode()
        info = await r.hgetall(f"tracking:{code}:info")
        if not info:
            # Session expired — clean up
            await r.delete(f"parent:{user_id}:active_session")
            return {"is_tracking": False, "role": "parent"}
        def _decode(val):
            return val.decode() if isinstance(val, bytes) else val
        decoded = {_decode(k): _decode(v) for k, v in info.items()}
        return {
            "is_tracking": True,
            "role": "parent",
            "tracking_code": code,
            "bus_number": decoded.get("bus_number", ""),
        }
```

**Update `join_tracking`** to store the parent's active session:
```python
# In join_tracking(), after adding parent to set:
await r.sadd(f"tracking:{code}:parents", parent_id)
# Store parent's active session for status lookup:
info_ttl = await r.ttl(f"tracking:{code}:info")
await r.setex(f"parent:{parent_id}:active_session", max(info_ttl, 3600), code)
```

**Update the endpoint in `main.py`**:
```python
@app.get("/api/tracking/status", tags=["tracking"])
async def tracking_status(claims: dict = Depends(require_auth)) -> dict:
    """Get tracking status for current user (driver or parent)."""
    from services.tracking_manager import get_tracking_status
    return await get_tracking_status(
        app.state.redis,
        claims["sub"],
        role=claims.get("role", "driver"),
    )
```

---

### T4: Add `GET /api/user/profile` Endpoint
**Priority**: 🟡 MEDIUM
**File**: `backend/main.py`

The Flutter app needs to display driver name. Currently login returns only `access_token`. Add a profile endpoint:

```python
@app.get("/api/user/profile", tags=["auth"])
async def user_profile(claims: dict = Depends(require_auth)) -> dict:
    """Get current user's profile information."""
    user_id = claims["sub"]
    role = claims.get("role", "unknown")
    
    # Look up display name from Redis
    display_name = user_id  # fallback
    user_data = await app.state.redis.hgetall(f"user:{user_id}:data")
    if user_data:
        def _d(v):
            return v.decode() if isinstance(v, bytes) else v
        decoded = {_d(k): _d(v) for k, v in user_data.items()}
        display_name = decoded.get("display_name", user_id)
    
    result = {
        "username": user_id,
        "display_name": display_name,
        "role": role,
    }
    
    # For drivers: include assignment info if available
    if role == "driver":
        assignment = await app.state.redis.hgetall(f"assignment:{user_id}")
        if assignment:
            def _d(v):
                return v.decode() if isinstance(v, bytes) else v
            assigned = {_d(k): _d(v) for k, v in assignment.items()}
            result["bus_number"] = assigned.get("bus_number")
            result["route_name"] = assigned.get("route_name")
    
    return result
```

---

### T5: Enhance GPS Update — Broadcast to Driver's Own WS Connection
**Priority**: 🟡 MEDIUM
**File**: `backend/main.py`

Currently, GPS updates are only published to Redis pub/sub when a driver has an active tracking session (`driver:{id}:active` key). But the driver themselves connects via WebSocket to see their own GPS. This is already handled by Agent 3's WS broadcaster — just confirm that the existing pub/sub publish in `validate_and_store_gps` fires correctly.

**Verify** in `tracking_manager.py` that this block is present and correct:
```python
# In validate_and_store_gps():
if tracking_code:
    code = tracking_code if isinstance(tracking_code, str) else tracking_code.decode()
    pipe.hset(f"tracking:{code}:location", mapping=location_data)
    pipe.expire(f"tracking:{code}:location", 30)
    # This MUST publish — Agent 3 subscribes to this channel
    pipe.publish(
        f"tracking:{code}:gps",
        json.dumps({
            "type": "position",
            "bus_number": bus_number,
            "lat": lat,
            "lng": lng,
            "speed": speed,
            "bearing": bearing,
            "accuracy": accuracy,
            "ts": now_ts,
        })
    )
```

If `json` is not imported at the top level of the function, add:
```python
import json
```

---

### T6: Health Endpoint — Add WebSocket Stats
**Priority**: 🟢 LOW
**File**: `backend/main.py`

Update the existing `/health` endpoint to expose WebSocket stats from Agent 3's broadcaster:

```python
@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    # ... existing redis + postgres health checks ...
    
    # Add WS stats:
    ws_stats = {"active_connections": 0, "active_sessions": 0}
    if hasattr(app.state, "broadcaster"):
        ws_stats = {
            "active_connections": app.state.broadcaster.connection_count,
            "active_sessions": len(app.state.broadcaster._connections),
        }
    
    return {
        "status": "ok",
        "version": "3.0.0",
        "redis": redis_ok,
        "postgres": pg_ok,
        "ws": ws_stats,
    }
```

---

## Verification

```bash
cd /home/raderex/Documents/bustrack

# 1. Rebuild backend
docker-compose up -d --build api

# 2. Wait for startup
sleep 5

# 3. Health check
curl http://localhost:8000/health | python3 -m json.tool

# 4. Login as driver
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"raderex","password":"__superuser__","role":"driver"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 5. Get profile
curl http://localhost:8000/api/user/profile \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# Expected: {"username":"raderex","display_name":"...","role":"driver",...}

# 6. Start tracking
RESULT=$(curl -s -X POST http://localhost:8000/api/tracking/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bus_number":"A1"}')
echo $RESULT | python3 -m json.tool
CODE=$(echo $RESULT | python3 -c "import sys,json; print(json.load(sys.stdin)['tracking_code'])")
echo "Code: $CODE"

# 7. Check tracking info (no auth required)
curl http://localhost:8000/api/tracking/info/$CODE | python3 -m json.tool
# Expected: {"bus_number":"A1","started_at":"...","connected_parents":0}

# 8. Login as parent and join — check driver_name is returned
PARENT_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"parent1","password":"x","role":"parent"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://localhost:8000/api/tracking/join/$CODE \
  -H "Authorization: Bearer $PARENT_TOKEN" | python3 -m json.tool
# Expected: {"bus_number":"A1","driver_name":"Raderex","tracking_code":"...","connected_parents":1}

# 9. Parent tracking status
curl http://localhost:8000/api/tracking/status \
  -H "Authorization: Bearer $PARENT_TOKEN" | python3 -m json.tool
# Expected: {"is_tracking":true,"role":"parent","tracking_code":"..."}

# 10. Stop tracking
curl -X POST http://localhost:8000/api/tracking/stop \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

## Success Criteria
- ✅ `POST /api/tracking/join/{code}` returns `driver_name` field (not null)
- ✅ `GET /api/tracking/info/{code}` returns session info without joining
- ✅ `GET /api/tracking/status` works for both drivers AND parents
- ✅ `GET /api/user/profile` returns username, display_name, role
- ✅ Redis pub/sub publishes GPS updates with full JSON (not partial)
- ✅ `GET /health` includes `ws` stats object
- ✅ All existing endpoints still pass (auth, routes, health)
- ✅ No 500 errors on any endpoint
- ✅ Backend restarts cleanly: `docker-compose restart api` + health check passes
