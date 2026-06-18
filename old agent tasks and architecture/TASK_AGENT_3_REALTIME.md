# AGENT 3 — Real-Time Systems Engineer (v3.1 — Reliability + Feature Pass)

## Agent Profile
- **Role**: Senior WebSocket / Real-Time Systems Engineer
- **Codename**: Agent 3 — Real-Time Systems Engineer
- **Scope**: `backend/main.py` WebSocket sections, `backend/services/ws_broadcast.py`

## Context (READ FIRST)
The WebSocket broadcaster from v3.0 is implemented and the `/ws/track/{tracking_code}` endpoint exists. This pass fixes reliability issues and adds missing real-time features that make the app feel live and dynamic.

## What's Already Working
- ✅ `TrackingBroadcaster` class with Redis pub/sub listener per tracking code
- ✅ `/ws/track/{tracking_code}?token=JWT` endpoint
- ✅ Ping/pong heartbeat
- ✅ Stale connection cleanup every 60s
- ✅ "ended" message when driver stops
- ✅ `parents_count` broadcast when parents join/leave

## Issues Found / Missing Features

1. ❌ **WS auth token passed as query param is insecure + has URL encoding issues** — parent token may contain `+` or `=` characters that break URL parsing
2. ❌ **No reconnect on WS drop** — if WS drops mid-session, parent sees blank connection with no recovery
3. ❌ **`parents_count` is NOT sent to driver** — driver has no idea how many parents are watching their broadcast in real time
4. ❌ **Driver's WS connection** (`/ws/track/{code}`) is used only to receive `parents_count`. But there's no mechanism to send `parents_count` updates to the driver's WebSocket when they connect (driver uses the same endpoint)
5. ❌ **Last known position not always sent on connect** — the current-location send block relies on Redis hash existing with TTL=30s. If GPS hasn't been sent recently, parent connects to empty map
6. ❌ **No `speed_alert` frame** when bus is stationary > 60s (stuck bus detection)
7. ❌ **`/ws/track/{code}` JWT verification uses `_verify_jwt` internal function** — this must be wired correctly. Confirm it's using the same JWT secret as login.

---

## Task List

### T1: Fix Token URL-Encoding Issue in WS Auth
**Priority**: 🔴 CRITICAL
**File**: `backend/main.py`

JWT tokens contain Base64 characters (`+`, `/`, `=`) which are URL-special. When passed as query params, they can get corrupted.

**Fix**: Decode the token after URL-decoding it:
```python
@app.websocket("/ws/track/{tracking_code}")
async def ws_track(websocket: WebSocket, tracking_code: str):
    # 1. Validate token — URL-decode it first
    import urllib.parse
    raw_token = websocket.query_params.get("token", "")
    token = urllib.parse.unquote(raw_token)  # FIX: decode URL encoding
    
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        claims = _verify_jwt(token)
    except Exception as exc:
        log.warning("WS JWT verification failed: %s", exc)
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    # ... rest of handler unchanged
```

---

### T2: Send `parents_count` Update to Driver's WS Connection
**Priority**: 🔴 CRITICAL
**File**: `backend/services/ws_broadcast.py` + `backend/main.py`

When a parent joins or leaves, the `TrackingBroadcaster` already broadcasts `parents_count` to ALL clients connected on that tracking code. Since the driver also connects to the same `/ws/track/{code}`, they WILL receive it — IF they are connected.

**Problem**: The driver may not be connected to `/ws/track/{code}` at all (they only POST GPS updates). They need a separate notification channel — OR they should connect to the same WS endpoint.

**Solution**: The Flutter driver app already connects to the WS endpoint via `_connectShareWs()` in `broadcast_provider.dart`. Make sure the WS broadcaster sends `parents_count` to ALL connected clients (including drivers) — **this is already the behavior**. 

**Verify** in `_broadcast()` method of `TrackingBroadcaster`:
```python
async def _broadcast(self, tracking_code: str, data: dict) -> None:
    """Sends to ALL connected clients — drivers AND parents on same code."""
    clients = self._connections.get(tracking_code, set()).copy()
    if not clients:
        return
    payload = json.dumps(data)
    dead = []
    for ws in clients:
        try:
            await ws.send_text(payload)
            self._last_activity[ws] = time.time()
        except Exception:
            dead.append(ws)
    for ws in dead:
        await self.unregister(ws)
```

**This is correct as-is** — confirm it exists and works. No change needed if already implemented.

---

### T3: Send Current Stats on WS Connect (Last Known GPS + Parent Count)
**Priority**: 🔴 CRITICAL
**File**: `backend/main.py` — `ws_track` endpoint

When a parent connects mid-trip, they should immediately receive:
1. The last known GPS position (so map shows bus instantly)
2. The current parent count

The current code sends location from `tracking:{code}:location` hash — but only if it exists. Expand it to also send `parents_count`:

```python
# After websocket.accept() and broadcaster.register():
await broadcaster.register(tracking_code, websocket)

# Send current GPS position immediately (if available)
current_loc = await app.state.redis.hgetall(
    f"tracking:{tracking_code}:location"
)
if current_loc:
    def _d(v):
        return v.decode() if isinstance(v, bytes) else v
    loc = {_d(k): _d(v) for k, v in current_loc.items()}
    try:
        await websocket.send_json({
            "type": "position",
            "bus_number": loc.get("bus_number", ""),
            "lat": float(loc.get("lat", 0)),
            "lng": float(loc.get("lng", 0)),
            "speed": float(loc.get("speed", 0)),
            "bearing": float(loc.get("bearing", 0)),
            "accuracy": float(loc.get("accuracy", 0)),
            "ts": float(loc.get("ts", 0)),
        })
        log.debug("Sent initial position to new WS client: code=%s", tracking_code)
    except Exception as exc:
        log.debug("Failed to send initial position: %s", exc)

# Also send current parent count immediately
parent_count = broadcaster.get_parent_count(tracking_code)
try:
    await websocket.send_json({
        "type": "parents_count",
        "count": parent_count,
    })
except Exception:
    pass
```

---

### T4: Add Stale Bus Detection — "Bus Stopped" Frame
**Priority**: 🟡 MEDIUM
**File**: `backend/services/ws_broadcast.py`

If GPS updates stop coming for > 45 seconds (driver lost network or phone died), parents should be notified instead of showing a stale marker forever.

**Add a background task per tracking session** that sends a `stale` frame if no GPS in 45s:

```python
# In TrackingBroadcaster.register(), after starting Redis listener:
# Also start a GPS staleness monitor
if tracking_code not in self._stale_monitors:
    monitor_task = asyncio.create_task(
        self._monitor_staleness(tracking_code),
        name=f"ws-stale-{tracking_code}",
    )
    self._stale_monitors[tracking_code] = monitor_task

# Add to __init__:
self._stale_monitors: dict[str, asyncio.Task] = {}
self._last_gps_time: dict[str, float] = {}

# Update _listen_redis to record GPS arrival time:
async def _listen_redis(self, tracking_code: str) -> None:
    # ... existing ...
    async for message in pubsub.listen():
        if message["type"] != "message":
            continue
        # Record GPS arrival
        self._last_gps_time[tracking_code] = time.time()
        # ... rest of existing broadcast logic ...

# New monitor:
async def _monitor_staleness(self, tracking_code: str) -> None:
    """Send 'stale' alert if no GPS in 45 seconds."""
    STALE_THRESHOLD = 45
    while True:
        await asyncio.sleep(15)  # Check every 15s
        if tracking_code not in self._connections or not self._connections[tracking_code]:
            break  # No clients connected, stop monitoring
        last = self._last_gps_time.get(tracking_code)
        if last and (time.time() - last) > STALE_THRESHOLD:
            await self._broadcast(tracking_code, {
                "type": "stale",
                "reason": "no_gps",
                "seconds_since_update": int(time.time() - last),
            })

# Also clean up in unregister():
# In unregister(), when no more connections for code:
monitor = self._stale_monitors.pop(code, None)
if monitor:
    monitor.cancel()
    try:
        await monitor
    except asyncio.CancelledError:
        pass
self._last_gps_time.pop(code, None)
```

---

### T5: Improve Shutdown — Graceful Connection Drain
**Priority**: 🟡 MEDIUM
**File**: `backend/services/ws_broadcast.py`

The existing `shutdown()` method cancels all tasks and closes connections. Improve it to also cancel stale monitor tasks:

```python
async def shutdown(self) -> None:
    """Gracefully close all connections and listeners."""
    # Cancel all Redis listeners
    for task in self._listeners.values():
        task.cancel()
    
    # Cancel all stale monitors (NEW)
    for task in self._stale_monitors.values():
        task.cancel()
    
    # Close all WebSocket connections
    for clients in self._connections.values():
        for ws in clients:
            try:
                await ws.close(code=1001, reason="Server shutting down")
            except Exception:
                pass

    self._connections.clear()
    self._listeners.clear()
    self._ws_to_code.clear()
    self._last_activity.clear()
    self._stale_monitors.clear()   # NEW
    self._last_gps_time.clear()    # NEW
    log.info("Broadcaster shutdown complete")
```

---

### T6: Verify `_verify_jwt` Uses Correct Secret
**Priority**: 🔴 CRITICAL
**File**: `backend/main.py`

The WS endpoint calls `_verify_jwt(token)`. This must use the same `JWT_SECRET` as the login endpoint. 

**Verify** the function exists and reads from the same env var:
```python
def _verify_jwt(token: str) -> dict:
    """Verify JWT and return claims. Raises exception if invalid."""
    import jwt as pyjwt
    secret = os.environ.get("JWT_SECRET", "changeme-dev-secret")
    return pyjwt.decode(token, secret, algorithms=["HS256"])
```

If this function doesn't exist or uses a different secret name, add/fix it.

Also check `decode_token` (line ~184 in main.py):
```python
def decode_token(token: str) -> dict[str, Any]:
    # Make sure this and _verify_jwt use the SAME secret + algorithm
```

If `decode_token` already exists and works, make `_verify_jwt` just call it:
```python
def _verify_jwt(token: str) -> dict:
    return decode_token(token)
```

---

### T7: Update Health Endpoint with WS Stats
**Priority**: 🟢 LOW
**File**: `backend/main.py`

Coordinate with Agent 2 — this is also listed in their tasks. **One agent should implement this — whichever finishes first.**

```python
@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    # ... existing redis + postgres checks ...
    
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

# 1. Rebuild + start
docker-compose up -d --build api
sleep 5

# 2. Login
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"raderex","password":"__superuser__","role":"driver"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 3. Start tracking
RESULT=$(curl -s -X POST http://localhost:8000/api/tracking/start \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"bus_number":"A1"}')
CODE=$(echo $RESULT | python3 -c "import sys,json; print(json.load(sys.stdin)['tracking_code'])")
echo "Code: $CODE"

# 4. Test WS with URL-encoded token (websocat)
ENCODED_TOKEN=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$TOKEN'))")
websocat "ws://localhost:8000/ws/track/$CODE?token=$ENCODED_TOKEN" &
WS_PID=$!
sleep 2

# 5. Send GPS update — should appear in websocat output
curl -s -X POST http://localhost:8000/api/gps-update \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"lat\":27.7172,\"lng\":85.3240,\"speed\":35,\"bearing\":180,\"accuracy\":8.5,\"ts\":$(date +%s),\"bus_number\":\"A1\"}"
# Expected in websocat: {"type":"position","bus_number":"A1",...}

# 6. Login as parent, connect WS
PARENT_TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"parent1","password":"x","role":"parent"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
curl -s -X POST "http://localhost:8000/api/tracking/join/$CODE" \
  -H "Authorization: Bearer $PARENT_TOKEN" | python3 -m json.tool

# 7. Check health includes WS stats
curl http://localhost:8000/health | python3 -m json.tool
# Expected: {"status":"ok","ws":{"active_connections":1,"active_sessions":1},...}

# 8. Stop tracking — WS should receive "ended"
curl -X POST http://localhost:8000/api/tracking/stop \
  -H "Authorization: Bearer $TOKEN"
# Expected in websocat: {"type":"ended","reason":"driver_stopped"}

kill $WS_PID 2>/dev/null
```

**If websocat not installed**, test with Python:
```python
import asyncio, websockets, json, urllib.parse

TOKEN = "..."  # paste token here
CODE = "..."   # paste code here

async def test():
    encoded = urllib.parse.quote(TOKEN)
    uri = f"ws://localhost:8000/ws/track/{CODE}?token={encoded}"
    async with websockets.connect(uri) as ws:
        # Should get immediate position + parents_count
        msg1 = await asyncio.wait_for(ws.recv(), timeout=5)
        print(f"Message 1: {msg1}")
        msg2 = await asyncio.wait_for(ws.recv(), timeout=5)
        print(f"Message 2: {msg2}")
        
        # Send ping
        await ws.send("ping")
        pong = await asyncio.wait_for(ws.recv(), timeout=3)
        print(f"Pong: {pong}")  # Should be "pong"

asyncio.run(test())
```

## Success Criteria
- ✅ WS connection works with URL-encoded tokens (special chars like `+`, `=` handled)
- ✅ On connect: parent immediately receives last known GPS position
- ✅ On connect: parent immediately receives current `parents_count`
- ✅ Driver WS connection receives `parents_count` updates when parents join/leave
- ✅ After 45s without GPS: `{"type":"stale"}` frame sent to all clients
- ✅ "ended" frame sent when driver stops
- ✅ Ping → "pong" response works
- ✅ Stale connections cleaned up after 120s idle
- ✅ `/health` endpoint includes `ws.active_connections` and `ws.active_sessions`
- ✅ Graceful shutdown cancels all monitor tasks
- ✅ No memory leaks — connections and tasks cleaned up on disconnect
- ✅ `_verify_jwt` uses same secret as login endpoint
