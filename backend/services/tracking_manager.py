import logging
import math
import secrets
import string
import time
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis
from services.trip_logger import get_pg_pool

log = logging.getLogger("bustrack.tracking")

# ── Constants ──────────────────────────────────────────────────
TRACKING_CODE_LENGTH = 6
TRACKING_DEFAULT_HOURS = 4
TRACKING_MAX_HOURS = 24
MAX_PARENTS_PER_SESSION = 50
GPS_MAX_SPEED_KMH = 200
GPS_MAX_TELEPORT_KM = 50
GPS_MIN_INTERVAL_SEC = 2
GPS_BATCH_MAX_POINTS = 100

# ── Schema ─────────────────────────────────────────────────────
TRACKING_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracking_sessions (
    id              SERIAL PRIMARY KEY,
    tracking_code   VARCHAR(8) UNIQUE NOT NULL,
    driver_id       VARCHAR(100) NOT NULL,
    bus_number      VARCHAR(20) NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL,
    active          BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_tracking_code ON tracking_sessions(tracking_code);
CREATE INDEX IF NOT EXISTS idx_tracking_driver ON tracking_sessions(driver_id);

CREATE TABLE IF NOT EXISTS gps_history (
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
CREATE INDEX IF NOT EXISTS idx_gps_bus ON gps_history(bus_number, recorded_at DESC);
"""

async def init_tracking_schema() -> None:
    """Initialize PostgreSQL tables. Idempotent."""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(TRACKING_SCHEMA_SQL)
        log.info("tracking schema initialised ✓")
    except Exception as exc:
        log.warning("Failed to init tracking schema (non-fatal): %s", exc)


def generate_tracking_code(length: int = TRACKING_CODE_LENGTH) -> str:
    """Generate a random alphanumeric code like XK7M2P."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def start_tracking(
    r: aioredis.Redis,
    driver_id: str,
    bus_number: str,
    driver_name: str | None = None,
    duration_hours: float = TRACKING_DEFAULT_HOURS,
) -> dict:
    """
    Create a new tracking session.
    Returns: {tracking_code, expires_at}
    Raises: ValueError if driver already has active session.
    """
    existing = await r.get(f"driver:{driver_id}:active")
    if existing:
        existing_code = existing if isinstance(existing, str) else existing.decode()
        info = await r.hgetall(f"tracking:{existing_code}:info")
        if info:
            def _d(v):
                return v.decode() if isinstance(v, bytes) else v
            raw = info.get(b"expires_at") or info.get("expires_at") or b""
            return {
                "tracking_code": existing_code,
                "expires_at": _d(raw),
                "already_active": True,
            }
    duration_hours = max(0.5, min(duration_hours, TRACKING_MAX_HOURS))
    expires_at = datetime.now(tz=timezone.utc) + timedelta(hours=duration_hours)
    ttl_seconds = int(duration_hours * 3600)
    for _ in range(10):
        code = generate_tracking_code()
        exists = await r.exists(f"tracking:{code}:info")
        if not exists:
            break
    else:
        raise ValueError("Failed to generate unique tracking code")
    pipe = r.pipeline()
    pipe.hset(f"tracking:{code}:info", mapping={
        "driver_id": driver_id,
        "bus_number": bus_number,
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "expires_at": expires_at.isoformat(),
        **({"driver_name": driver_name} if driver_name else {}),
    })
    pipe.expire(f"tracking:{code}:info", ttl_seconds)
    pipe.setex(f"driver:{driver_id}:active", ttl_seconds, code)
    await pipe.execute()
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO tracking_sessions (tracking_code, driver_id, bus_number, expires_at)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (tracking_code) DO UPDATE SET active = TRUE, started_at = now(), expires_at = $4""",
                code, driver_id, bus_number, expires_at,
            )
    except Exception as exc:
        log.warning("Failed to log tracking session to PG: %s", exc)
    log.info("Tracking started: code=%s driver=%s bus=%s", code, driver_id, bus_number)
    return {"tracking_code": code, "expires_at": expires_at.isoformat(), "already_active": False}


async def stop_tracking(r: aioredis.Redis, driver_id: str) -> bool:
    """Stop tracking session. Returns True if a session was active."""
    code = await r.get(f"driver:{driver_id}:active")
    if not code:
        return False
    code = code if isinstance(code, str) else code.decode()
    pipe = r.pipeline()
    pipe.delete(f"driver:{driver_id}:active")
    pipe.delete(f"tracking:{code}:info")
    pipe.delete(f"tracking:{code}:location")
    pipe.delete(f"tracking:{code}:parents")
    await pipe.execute()
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE tracking_sessions SET active = FALSE, ended_at = now() WHERE tracking_code = $1""",
                code,
            )
    except Exception as exc:
        log.warning("Failed to mark session ended in PG: %s", exc)
    log.info("Tracking stopped: code=%s driver=%s", code, driver_id)
    return True


async def join_tracking(
    r: aioredis.Redis,
    tracking_code: str,
    parent_id: str,
) -> dict | None:
    """
    Parent joins a tracking session.
    Returns session info or None if code is invalid/expired.
    """
    code = tracking_code.strip().upper()
    info = await r.hgetall(f"tracking:{code}:info")
    if not info:
        return None
    def _decode(v):
        return v.decode() if isinstance(v, bytes) else v
    decoded = {_decode(k): _decode(v) for k, v in info.items()}
    expires_at = datetime.fromisoformat(decoded["expires_at"])
    if datetime.now(tz=timezone.utc) > expires_at:
        return None
    parent_count = await r.scard(f"tracking:{code}:parents")
    if parent_count >= MAX_PARENTS_PER_SESSION:
        return None
    await r.sadd(f"tracking:{code}:parents", parent_id)
    new_count = await r.scard(f"tracking:{code}:parents")
    log.info("Parent joined: code=%s parent=%s total=%d", code, parent_id, new_count)
    # Store parent's active session for status lookup (TTL matches session info)
    info_ttl = await r.ttl(f"tracking:{code}:info")
    await r.setex(f"parent:{parent_id}:active_session", max(info_ttl, 3600), code)
    # Look up driver name from a Redis profile hash; fallback to a formatted driver_id
    driver_name_raw = await r.hget(f"driver:{decoded['driver_id']}:profile", "name")
    driver_name = driver_name_raw if driver_name_raw else decoded["driver_id"].replace("_", " ").title()
    return {
        "bus_number": decoded["bus_number"],
        "driver_id": decoded["driver_id"],
        "driver_name": driver_name,
        "tracking_code": code,
        "connected_parents": new_count,
    }


async def get_tracking_status(r: aioredis.Redis, user_id: str, role: str = "driver") -> dict:
    """Get current tracking status for a user (driver or parent)."""
    if role == "driver":
        code = await r.get(f"driver:{user_id}:active")
        if not code:
            return {"is_tracking": False, "role": "driver"}
        code = code if isinstance(code, str) else code.decode()
        parent_count = await r.scard(f"tracking:{code}:parents")
        info = await r.hgetall(f"tracking:{code}:info")
        def _decode(v):
            return v.decode() if isinstance(v, bytes) else v
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
    else:
        # parent role
        code = await r.get(f"parent:{user_id}:active_session")
        if not code:
            return {"is_tracking": False, "role": "parent"}
        code = code if isinstance(code, str) else code.decode()
        info = await r.hgetall(f"tracking:{code}:info")
        if not info:
            await r.delete(f"parent:{user_id}:active_session")
            return {"is_tracking": False, "role": "parent"}
        def _decode(v):
            return v.decode() if isinstance(v, bytes) else v
        decoded = {_decode(k): _decode(v) for k, v in info.items()}
        return {
            "is_tracking": True,
            "role": "parent",
            "tracking_code": code,
            "bus_number": decoded.get("bus_number", ""),
            "connected_parents": await r.scard(f"tracking:{code}:parents"),
            "started_at": decoded.get("started_at", ""),
            "expires_at": decoded.get("expires_at", ""),
        }


def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


async def validate_and_store_gps(
    r: aioredis.Redis,
    driver_id: str,
    data: dict,
) -> dict:
    lat = data.get("lat")
    lng = data.get("lng")
    speed = data.get("speed", 0)
    bearing = data.get("bearing", 0)
    accuracy = data.get("accuracy", 0)
    ts = data.get("ts", 0)
    bus_number = data.get("bus_number", "")
    if lat is None or lng is None:
        return {"status": "rejected", "reason": "missing lat/lng"}
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return {"status": "rejected", "reason": "invalid coordinates"}
    if speed > GPS_MAX_SPEED_KMH:
        return {"status": "rejected", "reason": f"speed {speed} exceeds max {GPS_MAX_SPEED_KMH}"}
    last_ts_raw = await r.hget(f"bus:{bus_number}:location", "ts")
    if last_ts_raw:
        last_ts = float(last_ts_raw)
        if ts and (ts - last_ts) < GPS_MIN_INTERVAL_SEC:
            return {"status": "rejected", "reason": "rate limited"}
    last_lat_raw = await r.hget(f"bus:{bus_number}:location", "lat")
    last_lng_raw = await r.hget(f"bus:{bus_number}:location", "lng")
    if last_lat_raw and last_lng_raw:
        last_lat = float(last_lat_raw)
        last_lng = float(last_lng_raw)
        dist_km = _haversine_km(last_lat, last_lng, lat, lng)
        if dist_km > GPS_MAX_TELEPORT_KM:
            log.warning("GPS teleportation: bus=%s dist=%.1fkm", bus_number, dist_km)
            return {"status": "rejected", "reason": "teleportation detected"}
    tracking_code = await r.get(f"driver:{driver_id}:active")
    now_ts = ts or time.time()
    location_data = {
        "lat": str(lat),
        "lng": str(lng),
        "speed": str(speed),
        "bearing": str(bearing),
        "accuracy": str(accuracy),
        "ts": str(now_ts),
        "bus_number": bus_number,
    }
    pipe = r.pipeline()
    pipe.hset(f"bus:{bus_number}:location", mapping=location_data)
    pipe.expire(f"bus:{bus_number}:location", 60)
    if tracking_code:
        code = tracking_code if isinstance(tracking_code, str) else tracking_code.decode()
        pipe.hset(f"tracking:{code}:location", mapping=location_data)
        pipe.expire(f"tracking:{code}:location", 30)
        pipe.publish(f"tracking:{code}:gps", f'{{"type":"position","bus_number":"{bus_number}","lat":{lat},"lng":{lng},"speed":{speed},"bearing":{bearing},"accuracy":{accuracy},"ts":{now_ts}}}')
    await pipe.execute()
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO gps_history (bus_number, driver_id, lat, lng, speed, bearing, accuracy) VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                bus_number, driver_id, lat, lng, speed, bearing, accuracy,
            )
    except Exception as exc:
        log.debug("Failed to log GPS to history: %s", exc)
    return {"status": "ok"}


async def validate_and_store_gps_batch(
    r: aioredis.Redis,
    driver_id: str,
    points: list[dict],
) -> dict:
    if len(points) > GPS_BATCH_MAX_POINTS:
        points = points[-GPS_BATCH_MAX_POINTS:]
    accepted = 0
    rejected = 0
    for i, point in enumerate(points):
        is_last = (i == len(points) - 1)
        if is_last:
            result = await validate_and_store_gps(r, driver_id, point)
        else:
            try:
                pool = await get_pg_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO gps_history (bus_number, driver_id, lat, lng, speed, bearing, accuracy, recorded_at) VALUES ($1, $2, $3, $4, $5, $6, $7, to_timestamp($8))""",
                        point.get("bus_number", ""),
                        driver_id,
                        point.get("lat", 0),
                        point.get("lng", 0),
                        point.get("speed", 0),
                        point.get("bearing", 0),
                        point.get("accuracy", 0),
                        point.get("ts", 0),
                    )
                accepted += 1
            except Exception:
                rejected += 1
                continue
            result = {"status": "ok"}
        if result["status"] == "ok":
            accepted += 1
        else:
            rejected += 1
    return {"status": "ok", "accepted": accepted, "rejected": rejected}
