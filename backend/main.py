"""
Kabja — Territory Running App Backend  v4.0
═══════════════════════════════════════════════
New in v3 (production-grade additions):
  ① Telegram OTP auth flow  — TelegramMockSMSGateway + webhook receiver
  ② Geofencing              — Haversine 500m check → FCM mock notification
  ③ Trip logging            — 60s Redis→PostgreSQL snapshots (route replay)
  ④ CORS hardening          — strict origin whitelist from env
  ⑤ Route-scoped JWT        — drivers validated against their assigned bus/route
  ⑥ WS role enforcement     — parents validated against their subscribed routes

Redis key schema:
  bus:{bus_id}:loc              HASH   {lat,lng,speed,bearing,ts,route_id}  TTL=30s
  route:{route_id}:buses        SET    {bus_id …}
  otp:{identifier}              STRING {code:{ts}                           TTL=300s
  otp_rate:{identifier}         STRING 1                                     TTL=60s
  tg_pending:{chat_id}          STRING pending                               TTL=600s
  stop:{stop_id}:fcm_tokens     SET    {fcm_token …}
  geofence:{bus_id}:{stop_id}   STRING 1                                     TTL=120s
  driver:{username}:assignment  HASH   {bus_id, route_id}
  parent:{username}:routes      SET    {route_id …}
  run:{run_id}:loc           STRING {lat,lng,speed,bearing,last_seen}        TTL=30s
  run:{run_id}:session        STRING {run_id,user_id,status,started_at,polyline,distance_km,last_speed}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid as uuid_lib
import math
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import hashlib
import hmac
import httpx
import redis.asyncio as aioredis
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
import urllib.parse
from sqlalchemy.ext.asyncio import AsyncSession
import h3
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from services.ws_broadcast import TrackingBroadcaster
from db import get_db, init_db
from services.tracking_manager import (
    init_tracking_schema,
    start_tracking,
    stop_tracking,
    join_tracking,
    get_tracking_status,
    validate_and_store_gps,
    validate_and_store_gps_batch,
)

# ─────────────────────────────────── Logging ─────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
log = logging.getLogger("kabja")

# ─────────────────────────────────── Config ──────────────────────────────────

JWT_SECRET: str         = os.environ["JWT_SECRET"]
JWT_ALGORITHM: str      = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

REDIS_HOST              = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT              = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD          = os.getenv("REDIS_PASSWORD", "")

OSRM_HOST               = os.getenv("OSRM_HOST", "http://localhost:5000")
PUBLIC_URL              = os.getenv("PUBLIC_URL", "https://bustrack.yourdomain.com")

TELEGRAM_BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_BOT_NAME       = os.getenv("TELEGRAM_BOT_NAME", "KTMBusTrackerBot")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
OTP_PROVIDER            = os.getenv("OTP_PROVIDER", "telegram")

KTM_BBOX                = (85.2, 27.6, 85.5, 27.8)  # W S E N
GPS_TTL_SECONDS         = 30
ETA_PING_DIVISOR        = 5

ALLOWED_ORIGINS: list[str] = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        f"{PUBLIC_URL},http://localhost:3000,http://localhost:8080",
    ).split(",")
    if o.strip()
]

# ──────────────────────────────────── Models ─────────────────────────────────


class GPSPing(BaseModel):
    bus_id:   str   = Field(..., min_length=1, max_length=64)
    route_id: str   = Field(..., min_length=1, max_length=64)
    lat:      float = Field(..., ge=KTM_BBOX[1], le=KTM_BBOX[3])
    lng:      float = Field(..., ge=KTM_BBOX[0], le=KTM_BBOX[2])
    speed:    float = Field(0.0, ge=0)
    bearing:  float = Field(0.0, ge=0, le=360)
    accuracy: float = Field(10.0, ge=0)


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role:     str = Field("parent", pattern="^(driver|parent|admin)$")


class FCMRegisterBody(BaseModel):
    stop_id:   str
    fcm_token: str


class ETAResult(BaseModel):
    bus_id:     str
    route_id:   str
    distance_m: float
    duration_s: float
    eta_iso:    str


class ShareCreateBody(BaseModel):
    expires_in_minutes: int = Field(60, ge=5, le=1440)


class RunUpdatePayload(BaseModel):
    run_id: str
    lat: float
    lng: float
    speed: float = 0.0
    bearing: float = 0.0
    timestamp: str


class RunStartResponse(BaseModel):
    run_id: str

# ──────────────────────────────── Redis pool ─────────────────────────────────

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(
            f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/0",
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


# ─────────────────────────────── GPS helpers ─────────────────────────────────


# OLD store_location DELETED — replaced by run-update handler
# async def store_location(ping: GPSPing) -> None:
#     r = await get_redis()
#     pipe = r.pipeline()
#     pipe.hset(f"bus:{ping.bus_id}:loc", mapping={
#         "lat":      str(ping.lat),
#         "lng":      str(ping.lng),
#         "speed":    str(ping.speed),
#         "bearing":  str(ping.bearing),
#         "ts":       str(time.time()),
#         "route_id": ping.route_id,
#     })
#     pipe.expire(f"bus:{ping.bus_id}:loc", GPS_TTL_SECONDS)
#     pipe.sadd(f"route:{ping.route_id}:buses", ping.bus_id)
#     await pipe.execute()


async def get_bus_location(bus_id: str) -> dict[str, str] | None:
    r = await get_redis()
    data = await r.hgetall(f"bus:{bus_id}:loc")
    return data or None


# ─────────────────────────────── JWT / Auth ──────────────────────────────────


def create_token(sub: str, role: str, extra: dict | None = None) -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {"sub": sub, "role": role, "exp": expire, **(extra or {})}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )


security = HTTPBearer()


async def require_driver(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    claims = decode_token(creds.credentials)
    if claims.get("role") not in ("driver", "admin"):
        raise HTTPException(status_code=403, detail="Driver role required")
    return claims

async def require_parent(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    claims = decode_token(creds.credentials)
    if claims.get("role") not in ("parent", "admin"):
        raise HTTPException(status_code=403, detail="Parent role required")
    return claims


async def require_any_auth(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> dict[str, Any]:
    return decode_token(creds.credentials)


async def _validate_driver_ownership(
    ping: GPSPing, claims: dict[str, Any]
) -> None:
    """Raises 403 if JWT route/bus doesn't match the ping body."""
    assigned_route = claims.get("assigned_route")
    assigned_bus   = claims.get("assigned_bus")
    if assigned_route and assigned_route != ping.route_id:
        raise HTTPException(
            status_code=403,
            detail=f"JWT assigned to route '{assigned_route}', ping claims '{ping.route_id}'",
        )
    if assigned_bus and assigned_bus != ping.bus_id:
        raise HTTPException(
            status_code=403,
            detail=f"JWT assigned to bus '{assigned_bus}', ping claims '{ping.bus_id}'",
        )


async def _validate_parent_route(
    route_id: str, claims: dict[str, Any]
) -> None:
    """Raises 403 if parent is not subscribed to this route."""
    role = claims.get("role")
    if role == "admin":
        return
    if role == "driver":
        raise HTTPException(status_code=403, detail="Drivers cannot subscribe as parent")
    allowed_routes = claims.get("allowed_routes")
    if allowed_routes and route_id not in allowed_routes:
        raise HTTPException(
            status_code=403,
            detail=f"Not subscribed to route '{route_id}'",
        )


# ──────────────────────────────── WebSocket manager ──────────────────────────


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket, route_id: str) -> None:
        await ws.accept()
        async with self._lock:
            self._rooms.setdefault(route_id, set()).add(ws)
        log.info("WS CONNECT route=%s clients=%d", route_id,
                 len(self._rooms.get(route_id, set())))

    async def disconnect(self, ws: WebSocket, route_id: str) -> None:
        async with self._lock:
            room = self._rooms.get(route_id, set())
            room.discard(ws)
            if not room:
                self._rooms.pop(route_id, None)

    async def broadcast(self, route_id: str, message: dict[str, Any]) -> None:
        room = self._rooms.get(route_id, set())
        if not room:
            return
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in list(room):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, route_id)

    async def broadcast_all(self, message: dict[str, Any]) -> None:
        for route_id in list(self._rooms):
            await self.broadcast(route_id, message)

    def client_count(self, route_id: str) -> int:
        return len(self._rooms.get(route_id, set()))


ws_manager = ConnectionManager()

# ─────────────────────────────── OSRM / ETA ──────────────────────────────────

SCHOOL_COORDS: dict[str, tuple[float, float]] = {
    "route_1": (27.7172, 85.3240),
    "route_2": (27.6913, 85.3420),
    "route_3": (27.7041, 85.3145),
}
_ping_counters: dict[str, int] = {}

# ─────────────────────────────── Route registry ──────────────────────────────

ROUTE_REGISTRY: dict[str, dict[str, Any]] = {
    "route_1": {
        "name": "Baneshwor \u2192 Patan School",
        "description": "Via Koteshwor and Patan Dhoka",
        "color": "#1B5E20",
    },
    "route_2": {
        "name": "Boudha \u2192 Little Angels",
        "description": "Via Chabahil",
        "color": "#0D47A1",
    },
    "route_3": {
        "name": "Balaju \u2192 Budhanilkantha",
        "description": "Via Samakhushi",
        "color": "#E65100",
    },
}


async def compute_and_push_eta(ping: GPSPing) -> None:
    _ping_counters[ping.bus_id] = _ping_counters.get(ping.bus_id, 0) + 1
    if _ping_counters[ping.bus_id] % ETA_PING_DIVISOR != 0:
        return
    dest = SCHOOL_COORDS.get(ping.route_id)
    if not dest:
        return
    url = (
        f"{OSRM_HOST}/route/v1/driving/"
        f"{ping.lng},{ping.lat};{dest[1]},{dest[0]}"
        f"?overview=false&steps=false"
    )
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            return
        r = data["routes"][0]
        duration_s = r["duration"]
        eta_dt = datetime.now(tz=timezone.utc) + timedelta(seconds=duration_s)
        await ws_manager.broadcast(ping.route_id, {
            "type":       "eta",
            "bus_id":     ping.bus_id,
            "route_id":   ping.route_id,
            "distance_m": round(r["distance"], 1),
            "duration_s": round(duration_s, 1),
            "eta_iso":    eta_dt.isoformat(),
        })
    except Exception as exc:
        log.warning("ETA error bus=%s: %s", ping.bus_id, exc)


# ─────────────────────────── Geofencing (imported) ───────────────────────────

from services.geofence import (
    check_geofences,
    register_fcm_token,
    unregister_fcm_token,
    STOP_REGISTRY,
)

# ─────────────────────────── Trip logger (imported) ──────────────────────────

from services.trip_logger import (
    init_schema,
    trip_logger_loop,
    get_trip_replay,
    close_pg_pool,
)

# ─────────────────────────── Route manager (imported) ────────────────────────

from services.route_manager import (
    init_route_schema,
    get_all_routes   as db_get_all_routes,
    get_route        as db_get_route,
    create_route     as db_create_route,
    update_route     as db_update_route,
    delete_route     as db_delete_route,
    add_stop         as db_add_stop,
    remove_stop      as db_remove_stop,
)

from services.share_manager import (
    init_share_schema,
    create_share_session,
    validate_share_code,
    add_parent_to_session,
    remove_parent_from_session,
    get_session_status,
    set_driver_connected,
    get_active_share_for_driver,
    store_share_location,
    get_share_location,
)
from strava import (
    get_auth_url,
    exchange_token,
    save_strava_connection,
    clear_strava_connection,
    get_valid_token,
    sync_user_activities,
    handle_webhook_event,
    get_strava_status,
    deauthorize,
    STRAVA_WEBHOOK_VERIFY_TOKEN,
    STRAVA_APP_REDIRECT,
)
from fastapi.responses import RedirectResponse

# ────────────────────────────────── App ──────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("══════ Kabja v4.0 startup ══════")

    r = await get_redis()
    await r.ping()
    log.info("Redis        ✓")
    await _seed_users(r)
    await _auto_seed_assignments(r)

    try:
        await init_schema()
        await init_db()
        await init_route_schema()
        await init_share_schema()
        await init_tracking_schema()
        log.info("PostgreSQL   ✓")
        asyncio.create_task(trip_logger_loop(r), name="trip_logger")
        log.info("Trip logger  ✓ (60s interval)")
    except Exception as exc:
        log.warning("PostgreSQL unavailable — trip logging disabled (%s)", exc)

    # Initialize WebSocket broadcaster
    app.state.broadcaster = TrackingBroadcaster(redis=r)
    log.info("WebSocket broadcaster initialized ✓")
    
    # Start background monitors
    async def _check_stale_ws():
        """Periodically clean up idle WebSocket connections (existing logic)."""
        while True:
            await asyncio.sleep(60)
            try:
                await app.state.broadcaster.check_stale_connections()
            except Exception as exc:
                log.debug("Stale WS check error: %s", exc)

    async def _check_stale_buses():
        """Detect buses with no GPS for >45 seconds and broadcast a stale frame.
        For each bus we inspect its location hash timestamp. If missing or older than 45 s,
        a message `{\"type\": \"stale\", \"bus_id\": <bus_id>}` is sent to all clients on that
        bus's route via the existing `ws_manager` broadcaster.
        """
        while True:
            await asyncio.sleep(45)
            try:
                r = await get_redis()
                route_keys = await r.keys("route:*:buses")
                for rk in route_keys:
                    route_id = rk.split(":")[1]
                    bus_ids = await r.smembers(rk)
                    for bus_id in bus_ids:
                        loc_key = f"bus:{bus_id}:loc"
                        ts_str = await r.hget(loc_key, "ts")
                        if not ts_str:
                            await ws_manager.broadcast(route_id, {"type": "stale", "bus_id": bus_id})
                            continue
                        try:
                            ts = float(ts_str)
                        except ValueError:
                            continue
                        if time.time() - ts > 45:
                            await ws_manager.broadcast(route_id, {"type": "stale", "bus_id": bus_id})
            except Exception as exc:
                log.debug("Stale bus detection error: %s", exc)

    # Start background monitor tasks
    stale_ws_task = asyncio.create_task(_check_stale_ws())
    stale_bus_task = asyncio.create_task(_check_stale_buses())

    log.info("══════ Startup complete ══════")
    yield

    # Shutdown
    stale_ws_task.cancel()
    stale_bus_task.cancel()
    await app.state.broadcaster.shutdown()
    log.info("WebSocket broadcaster shutdown ✓")
    if _redis:
        await _redis.aclose()
    await close_pg_pool()
    log.info("Shutdown complete.")


app = FastAPI(
    title="Kabja API",
    version="4.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ── CORS — strict whitelist ────────────────────────────────────────────────────
# Native mobile apps don't use CORS but the Admin web panel does.
# Never use allow_origins=["*"] in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
    max_age=600,
)

# ═══════════════════════════════ Endpoints ════════════════════════════════════

# ── Tracking Info (public) ────────────────────────────────────────────────────────

@app.get("/api/tracking/info/{tracking_code}", tags=["tracking"])
async def tracking_info(tracking_code: str) -> dict:
    """Public endpoint to fetch basic info for a tracking session.
    Does NOT join the session. Returns 404 if code invalid or expired.
    """
    code = tracking_code.strip().upper()
    r = await get_redis()
    info = await r.hgetall(f"tracking:{code}:info")
    if not info:
        raise HTTPException(status_code=404, detail="Invalid or expired tracking code")
    def _d(v):
        return v.decode() if isinstance(v, bytes) else v
    decoded = {_d(k): _d(v) for k, v in info.items()}
    expires_at_str = decoded.get("expires_at", "")
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            if datetime.now(tz=timezone.utc) > expires_at:
                raise HTTPException(status_code=404, detail="Tracking session expired")
        except Exception:
            pass
    parent_count = await r.scard(f"tracking:{code}:parents")
    return {
        "bus_number": decoded.get("bus_number", ""),
        "started_at": decoded.get("started_at", ""),
        "expires_at": expires_at_str,
        "connected_parents": parent_count,
    }

# ── User Profile (auth) ────────────────────────────────────────────────────────

@app.get("/api/user/profile", tags=["auth"])
async def user_profile(claims: dict = Depends(require_any_auth)) -> dict:
    """Return current user's profile information.
    Includes display name, role, and for drivers their bus/route assignment.
    """
    user_id = claims.get("sub")
    role = claims.get("role", "unknown")
    r = await get_redis()
    display_name = user_id
    user_data = await r.hgetall(f"user:{user_id}:data")
    if user_data:
        def _d(v):
            return v.decode() if isinstance(v, bytes) else v
        decoded = {_d(k): _d(v) for k, v in user_data.items()}
        display_name = decoded.get("display_name", user_id)
    result: dict[str, Any] = {"username": user_id, "display_name": display_name, "role": role}
    if role == "driver":
        assignment = await r.hgetall(f"driver:{user_id}:assignment")
        if assignment:
            def _d(v):
                return v.decode() if isinstance(v, bytes) else v
            a_dec = {_d(k): _d(v) for k, v in assignment.items()}
            result["bus_number"] = a_dec.get("bus_id", "")
            result["route_id"] = a_dec.get("route_id", "")
    return result

# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health", tags=["system"])
async def health() -> dict[str, Any]:
    r = await get_redis()
    redis_ok = await r.ping()
    broadcaster = app.state.broadcaster if hasattr(app.state, "broadcaster") else None
    ws_stats = {"active_connections": 0, "active_sessions": 0}
    if broadcaster:
        ws_stats = {
            "active_connections": broadcaster.connection_count,
            "active_sessions": len(broadcaster._connections),
        }
    return {
        "status":    "ok",
        "redis":     redis_ok,
        "version":   "3.0.0",
        "time":      datetime.now(tz=timezone.utc).isoformat(),
        "ws": ws_stats,
        "ws_clients": {
            rid: ws_manager.client_count(rid)
            for rid in ["route_1", "route_2", "route_3"]
        },
    }


# ═══════════════ AUTH — username + password → JWT ════════════════════════════

# These usernames bypass password check and get full access for any role.
_SUPERUSERS: frozenset[str] = frozenset({"raderex", "suman", "sumeet", "prajwal"})

_DEFAULT_USERS: dict[str, dict[str, str]] = {
    "driver1": {"password": "password", "role": "driver"},
    "driver2": {"password": "password", "role": "driver"},
    "driver3": {"password": "password", "role": "driver"},
    "parent1": {"password": "password", "role": "parent"},
    "parent2": {"password": "password", "role": "parent"},
    "parent3": {"password": "password", "role": "parent"},
    "admin":   {"password": "adminpass", "role": "admin"},
}


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


async def _seed_users(r: aioredis.Redis) -> None:
    """Seed default users into Redis if they don't exist yet."""
    for username, info in _DEFAULT_USERS.items():
        key = f"user:{username}"
        if not await r.exists(key):
            await r.hset(key, mapping={
                "password_hash": _hash_password(info["password"]),
                "role":          info["role"],
            })
    log.info("User credentials seeded ✓")


async def _auto_seed_assignments(r: aioredis.Redis) -> None:
    """
    Idempotent Redis assignment seeding — safe to call on every startup.
    Seeds driver bus/route assignments and parent route subscriptions so the
    app works immediately after a fresh `docker compose up` without any
    manual /api/admin/seed call.
    """
    if await r.exists("driver:driver1:assignment"):
        return  # already seeded, nothing to do
    pipe = r.pipeline()
    pipe.hset("driver:driver1:assignment", mapping={"bus_id": "BUS_001", "route_id": "route_1"})
    pipe.hset("driver:driver2:assignment", mapping={"bus_id": "BUS_002", "route_id": "route_2"})
    pipe.hset("driver:driver3:assignment", mapping={"bus_id": "BUS_003", "route_id": "route_3"})
    pipe.sadd("parent:parent1:routes", "route_1")
    pipe.sadd("parent:parent2:routes", "route_1", "route_2")
    pipe.sadd("parent:parent3:routes", "route_3")
    await pipe.execute()
    log.info("Driver/parent assignments auto-seeded ✓")


async def _verify_user(r: aioredis.Redis, username: str, password: str) -> str | None:
    """
    Return the user's stored role if credentials are valid, else None.
    Superusers always pass regardless of password.
    """
    if username in _SUPERUSERS:
        return "superuser"   # special sentinel — login endpoint grants requested role
    data = await r.hgetall(f"user:{username}")
    if not data:
        return None
    expected = data.get("password_hash", "")
    if not hmac.compare_digest(expected, _hash_password(password)):
        return None
    return data.get("role")


@app.post("/api/auth/login", tags=["auth"])
async def login(body: LoginBody) -> dict[str, str]:
    """
    Authenticate with username + password.
    Superusers (raderex, suman, sumeet, prajwal) bypass password and get
    full access for whichever role they select.
    """
    r = await get_redis()
    stored_role = await _verify_user(r, body.username, body.password)
    if stored_role is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    is_superuser = (stored_role == "superuser")
    effective_role = body.role  # superusers get exactly the role they asked for

    # Regular users: requested role must match their stored role
    if not is_superuser and stored_role != "admin" and stored_role != body.role:
        raise HTTPException(
            status_code=403,
            detail=f"User '{body.username}' does not have role '{body.role}'",
        )

    extra: dict[str, Any] = {}
    if effective_role == "driver":
        if is_superuser:
            # Superusers get assignment from any driver slot or a default
            assignment = await r.hgetall(f"driver:{body.username}:assignment")
            extra["assigned_bus"]   = assignment.get("bus_id", "BUS_001")
            extra["assigned_route"] = assignment.get("route_id", "route_1")
        else:
            assignment = await r.hgetall(f"driver:{body.username}:assignment")
            if assignment:
                extra["assigned_bus"]   = assignment.get("bus_id", "")
                extra["assigned_route"] = assignment.get("route_id", "")
    elif effective_role == "parent":
        if is_superuser:
            # Superusers see all routes
            all_routes = ["route_1", "route_2", "route_3"]
            extra["allowed_routes"] = all_routes
        else:
            routes = await r.smembers(f"parent:{body.username}:routes")
            if routes:
                extra["allowed_routes"] = list(routes)

    token = create_token(sub=body.username, role=effective_role, extra=extra)
    log.info("Login OK user=%s role=%s superuser=%s", body.username, effective_role, is_superuser)
    return {"access_token": token, "token_type": "bearer"}


# ═══════════════ RUN TRACKING ENDPOINTS ═══════════════════════════════════════════════

@app.post("/api/run-update")
async def run_update(payload: RunUpdatePayload, token: str = Depends(require_any_auth)):
    """
    Hot path — Redis only. No DB write.
    Called every 3s by the Flutter runner app.
    """
    r = await get_redis()
    key = f"run:{payload.run_id}:loc"
    value = json.dumps({
        "lat": payload.lat,
        "lng": payload.lng,
        "speed": payload.speed,
        "bearing": payload.bearing,
        "last_seen": payload.timestamp,
    })
    await r.setex(key, 30, value)          # TTL 30s — auto-expires stale runners

    # Append point to session polyline (for finish)
    session_key = f"run:{payload.run_id}:session"
    session_raw = await r.get(session_key)
    if session_raw:
        session = json.loads(session_raw)
        session["polyline"].append([payload.lat, payload.lng])
        session["last_speed"] = payload.speed
        # Accumulate distance (simple haversine from last point)
        pts = session["polyline"]
        if len(pts) >= 2:
            session["distance_km"] = _accumulate_distance(pts)
        await r.set(session_key, json.dumps(session))   # no TTL — persists until finish

    return {"ok": True}


@app.post("/api/run/start", response_model=RunStartResponse)
async def run_start(token: str = Depends(require_any_auth)):
    """
    Creates a new run session. Returns run_id.
    Flutter stores this and sends it with every /api/run-update.
    """
    run_id = str(uuid_lib.uuid4())
    session_key = f"run:{run_id}:session"
    
    r = await get_redis()
    session = {
        "run_id": run_id,
        "user_id": token.get("sub", ""),          # extracted from JWT
        "status": "active",
        "started_at": datetime.utcnow().isoformat(),
        "polyline": [],                        # [[lat, lng], ...]
        "distance_km": 0.0,
        "last_speed": 0.0,
    }
    await r.set(session_key, json.dumps(session))
    return {"run_id": run_id}


@app.post("/api/run/finish")
async def run_finish(run_id: str, token: str = Depends(require_any_auth)):
    """
    1. Read session from Redis.
    2. Mark session finished.
    3. Fire-and-forget: call territory engine (Backend Engineer owns territory.py).
    4. Return immediate response to Flutter.
    """
    r = await get_redis()
    session_key = f"run:{run_id}:session"
    loc_key = f"run:{run_id}:loc"

    session_raw = await r.get(session_key)
    if not session_raw:
        raise HTTPException(status_code=404, detail="Run session not found")

    session = json.loads(session_raw)
    session["status"] = "finished"
    session["finished_at"] = datetime.utcnow().isoformat()
    await r.set(session_key, json.dumps(session))

    # Clean up live GPS key
    await r.delete(loc_key)

    # Hand off to Backend Engineer's territory pipeline (non-blocking)
    # territory.py exposes process_run(session: dict) as an async function
    # Import at top: from territory import process_run
    asyncio.create_task(_run_territory_pipeline(session))

    return {
        "ok": True,
        "run_id": run_id,
        "distance_km": round(session.get("distance_km", 0), 3),
        "duration_s": _calc_duration(session),
    }


async def _run_territory_pipeline(session: dict):
    """Called in background — does not block the HTTP response."""
    try:
        from territory import process_run
        result = await process_run(session)
        # Push territory_result over WS to the runner
        user_id = session.get("user_id", "")
        if user_id and user_id in active_connections:
            await active_connections[user_id].send_text(json.dumps({
                "type": "territory_result",
                "payload": result,
            }))
        log.info("Territory pipeline OK: run=%s cells=%s",
                 session.get("run_id"), result.get("cells_captured", 0))
    except Exception as e:
        log.error("[territory_pipeline] error: %s", e)


# ──────────────────────────────── WebSocket manager ──────────────────────────

# Add this near the top of main.py (module level):
active_connections: dict[str, WebSocket] = {}   # user_id → WebSocket

# ── WebSocket route ──
@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """
    Each runner connects here on app open.
    Receives:
      - position updates from nearby runners (radius 5km)
      - own live stats (every 5s)
      - territory_result after run finish
    """
    await websocket.accept()
    active_connections[user_id] = websocket

    stats_task = asyncio.create_task(_push_stats_loop(user_id, websocket))

    try:
        while True:
            # Keep connection alive; client sends pings
            data = await asyncio.wait_for(websocket.receive_text(), timeout=60)
            # Optional: handle client messages here (e.g. ping → pong)
            if data == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    finally:
        stats_task.cancel()
        active_connections.pop(user_id, None)


async def _push_stats_loop(user_id: str, websocket: WebSocket):
    """Push live run stats to the connected runner every 5 seconds."""
    while True:
        await asyncio.sleep(5)
        try:
            # Find the active run_id for this user
            run_id = await _get_active_run_id(user_id)
            if run_id:
                r = await get_redis()
                session_key = f"run:{run_id}:session"
                session_raw = await r.get(session_key)
                if session_raw:
                    session = json.loads(session_raw)
                    distance_km = session.get("distance_km", 0)
                    duration_s = _calc_duration(session)
                    pace = _calc_pace(distance_km, duration_s)
                    await websocket.send_text(json.dumps({
                        "type": "stats",
                        "payload": {
                            "distance_km": round(distance_km, 3),
                            "duration_s": duration_s,
                            "pace_min_km": pace,
                            "speed_ms": session.get("last_speed", 0),
                        }
                    }))\n                    # Push Strava sync status if running\n                    sync_status = await r.get(f"strava_sync:{user_id}:status")\n                    if sync_status == "syncing":\n                        await websocket.send_text(json.dumps({\n                            "type": "strava_sync_status",\n                            "payload": {"status": "syncing"},\n                        }))

            # Also push nearby runner positions
            nearby = await _get_nearby_runners(user_id, radius_km=5)
            for runner in nearby:
                await websocket.send_text(json.dumps({
                    "type": "position",
                    "payload": runner,
                }))
        except Exception:
            break   # WebSocket closed


async def _get_active_run_id(user_id: str) -> str | None:
    """Scan Redis for a session belonging to this user with status=active."""
    # Scan run:*:session keys — bounded by active runners only
    r = await get_redis()
    async for key in r.scan_iter("run:*:session"):
        raw = await r.get(key)
        if raw:
            s = json.loads(raw)
            if s.get("user_id") == user_id and s.get("status") == "active":
                return s["run_id"]
    return None


async def _get_nearby_runners(user_id: str, radius_km: float) -> list[dict]:
    """Return positions of all active runners within radius_km of user."""
    # Get this user's current position
    # Find their active run first
    my_run_id = await _get_active_run_id(user_id)
    if not my_run_id:
        return []

    r = await get_redis()
    my_loc_raw = await r.get(f"run:{my_run_id}:loc")
    if not my_loc_raw:
        return []

    my_loc = json.loads(my_loc_raw)
    my_lat, my_lng = my_loc["lat"], my_loc["lng"]

    nearby = []
    async for key in r.scan_iter("run:*:loc"):
        raw = await r.get(key)
        if not raw:
            continue
        loc = json.loads(raw)
        dist = _haversine(my_lat, my_lng, loc["lat"], loc["lng"])
        if dist <= radius_km:
            run_id = key.split(":")[1]  # key is already str (decode_responses=True)
            nearby.append({
                "run_id": run_id,
                "lat": loc["lat"],
                "lng": loc["lng"],
                "speed": loc.get("speed", 0),
                "bearing": loc.get("bearing", 0),
            })

    return nearby


# ═══════════════ OLD GPS INGESTION (DELETED — replaced by /api/run-update) ═══════════════
# OLD store_location and geofence functions removed as part of bus→run migration


# ═══════════════ SHARE SESSIONS ═══════════════════════════════════════════════


@app.post("/api/share", status_code=201, tags=["share"])
async def share_create(
    body: ShareCreateBody | None = None,
    claims: dict = Depends(require_driver),
) -> dict:
    """
    Driver creates a share session. Returns share_code, share_url, expires_at.
    The driver then connects to /ws/share/{share_code} to broadcast GPS.
    """
    r = await get_redis()
    driver_id = claims.get("sub", "")
    assigned_bus = claims.get("assigned_bus", driver_id)
    minutes = body.expires_in_minutes if body else 60
    session = await create_share_session(r, driver_id, assigned_bus, minutes)
    log.info("Share created by driver=%s code=%s", driver_id, session["share_code"])
    return session


@app.post("/api/share/{share_code}", tags=["share"])
async def share_join(
    share_code: str,
    claims: dict = Depends(require_any_auth),
) -> dict:
    """
    Parent joins an existing share session.
    Must be called before connecting to /ws/share/{share_code}.
    """
    role = claims.get("role", "")
    if role == "driver":
        raise HTTPException(status_code=403, detail="Drivers cannot join shares as parents")

    r = await get_redis()
    session = await validate_share_code(r, share_code)
    if not session:
        raise HTTPException(status_code=404, detail="Share session not found or expired")

    parent_id = claims.get("sub", "")
    total = await add_parent_to_session(r, share_code, parent_id)

    return {
        "status": "joined",
        "share_code": share_code,
        "driver_id": session["driver_id"],
        "parents_connected": total,
    }


@app.get("/api/share/{share_code}/status", tags=["share"])
async def share_status(
    share_code: str,
    claims: dict = Depends(require_any_auth),
) -> dict:
    """Check the status of a share session."""
    r = await get_redis()
    active_ws = ws_manager.client_count(share_code)
    status = await get_session_status(r, share_code, active_ws)
    if not status:
        raise HTTPException(status_code=404, detail="Share session not found or expired")
    return status


class TrackingStartBody(BaseModel):
    bus_number: str = Field("", min_length=0, max_length=64)
    duration_hours: float = Field(4.0, ge=0.5, le=24)


@app.post("/api/tracking/start", status_code=201, tags=["tracking"])
async def tracking_start(
    body: TrackingStartBody | None = None,
    claims: dict = Depends(require_driver),
) -> dict:
    """
    Driver starts a new tracking session. Returns tracking_code and expires_at.
    The driver_name is resolved from the JWT 'sub' claim + Redis user data.
    If bus_number is not provided, it falls back to the JWT's assigned_bus.
    """
    r = await get_redis()
    driver_id = claims.get("sub", "")
    bus_number = (body.bus_number if body and body.bus_number else "") or claims.get("assigned_bus", driver_id)
    duration_hours = body.duration_hours if body else 4.0

    # Resolve driver display name from Redis user data or profile
    driver_name = None
    user_data = await r.hgetall(f"user:{driver_id}:data")
    if user_data:
        def _d(v):
            return v.decode() if isinstance(v, bytes) else v
        decoded = {_d(k): _d(v) for k, v in user_data.items()}
        driver_name = decoded.get("display_name")
    if not driver_name:
        profile_name = await r.hget(f"driver:{driver_id}:profile", "name")
        if profile_name:
            driver_name = profile_name if isinstance(profile_name, str) else profile_name.decode()
    if not driver_name:
        driver_name = driver_id.replace("_", " ").title()

    try:
        result = await start_tracking(
            r,
            driver_id=driver_id,
            bus_number=bus_number,
            driver_name=driver_name,
            duration_hours=duration_hours,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    log.info("Tracking started: driver=%s bus=%s code=%s name=%s",
             driver_id, bus_number, result.get("tracking_code"), driver_name)
    return result


@app.post("/api/tracking/join/{tracking_code}", tags=["tracking"])
async def tracking_join(
    tracking_code: str,
    claims: dict = Depends(require_any_auth),
) -> dict:
    """
    Parent joins a tracking session by code. Returns session info
    (bus_number, driver_id, driver_name, connected_parents).
    """
    role = claims.get("role", "")
    if role == "driver":
        raise HTTPException(status_code=403, detail="Drivers cannot join tracking as parent")

    r = await get_redis()
    parent_id = claims.get("sub", "")
    result = await join_tracking(r, tracking_code, parent_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Invalid, expired, or full tracking session")
    return result


@app.post("/api/tracking/stop", tags=["tracking"])
async def tracking_stop(claims: dict = Depends(require_driver)) -> dict:
    """
    Driver stops broadcasting GPS. Notifies all connected parents via WebSocket.
    """
    r = await get_redis()
    driver_id = claims.get("sub", "")

    # Read tracking code using the same key that start_tracking() writes
    tracking_code = await r.get(f"driver:{driver_id}:active")
    if not tracking_code:
        raise HTTPException(status_code=404, detail="No active tracking session")

    code_str = tracking_code if isinstance(tracking_code, str) else tracking_code.decode()

    # Notify all connected parents via broadcaster
    broadcaster: TrackingBroadcaster = app.state.broadcaster
    await broadcaster.send_to_session(code_str, {
        "type": "ended",
        "reason": "driver_stopped",
    })

    # Delegate full cleanup to tracking_manager (Redis + PostgreSQL)
    await stop_tracking(r, driver_id)

    log.info("Tracking stopped by driver=%s code=%s", driver_id, code_str)
    return {"status": "stopped", "tracking_code": code_str}


@app.get("/api/tracking/status", tags=["tracking"])
async def tracking_status_endpoint(claims: dict = Depends(require_any_auth)) -> dict:
    """Return current tracking status for the authenticated user."""
    r = await get_redis()
    user_id = claims.get("sub", "")
    role = claims.get("role", "driver")
    return await get_tracking_status(r, user_id, role)



# ═══════════════ WEBSOCKET ═══════════════════════════════════════════════════


@app.websocket("/ws/share/{share_code}")
async def websocket_share(
    ws: WebSocket,
    share_code: str,
    token: str = Query(...),
) -> None:
    """
    WSS /ws/share/{share_code}?token=<JWT>

    Share-based live tracking (MVP mode). Both drivers and parents
    connect to the same share_code room. The driver sends position
    frames through the WebSocket; the backend relays them to all
    connected parents in the same room.

    Driver flow:
      1. POST /api/share → receive share_code
      2. Connect to /ws/share/{share_code} (JWT role=driver)
      3. Send JSON frames: { "lat": ..., "lng": ..., "speed": ..., "bearing": ... }

    Parent flow:
      1. POST /api/share/{share_code} → join session
      2. Connect to /ws/share/{share_code} (JWT role=parent)
      3. Receive position frames relayed from driver

    Push frame types (server → client):
      { type: "position", share_code, driver_id, bus_id, lat, lng, speed, bearing, ts }
      { type: "share_connected", share_code }
    """
    # URL‑decode token to handle '+' and '=' characters properly
    decoded_token = urllib.parse.unquote(token)
    try:
        claims = decode_token(decoded_token)
    except HTTPException:
        await ws.close(code=4001, reason="Unauthorized")
        return

    role = claims.get("role", "")
    username = claims.get("sub", "")

    if role not in ("driver", "parent", "admin"):
        await ws.close(code=4003, reason="Invalid role")
        return

    r = await get_redis()
    session = await validate_share_code(r, share_code)
    if not session:
        await ws.close(code=4004, reason="Share session not found or expired")
        return

    if role == "driver" and session.get("driver_id") != username:
        await ws.close(code=4003, reason="Not your share session")
        return

    await ws_manager.connect(ws, share_code)

    if role == "driver":
        await set_driver_connected(r, share_code, True)

    try:
        # State dump on connect — send latest known position
        if role in ("parent", "admin"):
            loc = await get_share_location(r, share_code)
            if loc:
                await ws.send_json({
                    "type":     "position",
                    "share_code": share_code,
                    "driver_id":  session.get("driver_id", ""),
                    "bus_id":     session.get("bus_id", ""),
                    "lat":        float(loc.get("lat", 0)),
                    "lng":        float(loc.get("lng", 0)),
                    "speed":      float(loc.get("speed", 0)),
                    "bearing":    float(loc.get("bearing", 0)),
                    "ts":         float(loc.get("ts", 0)),
                })
        else:
            await ws.send_json({
                "type": "share_connected",
                "share_code": share_code,
                "driver_id":  session.get("driver_id", ""),
                "bus_id":     session.get("bus_id", ""),
            })

        # Application-level heartbeat + position relay
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=25.0)

                if data == "ping":
                    await ws.send_text("pong")
                    continue

                # Driver → relay position to parents
                if role == "driver":
                    try:
                        msg = json.loads(data)
                        if "lat" in msg and "lng" in msg:
                            position_msg: dict[str, Any] = {
                                "type":       "position",
                                "share_code":  share_code,
                                "driver_id":   username,
                                "bus_id":      session.get("bus_id", username),
                                "lat":         msg["lat"],
                                "lng":         msg["lng"],
                                "speed":       msg.get("speed", 0),
                                "bearing":     msg.get("bearing", 0),
                                "ts":          msg.get("ts", time.time()),
                            }
                            await store_share_location(r, share_code, position_msg)
                            await ws_manager.broadcast(share_code, position_msg)
                    except json.JSONDecodeError:
                        pass  # ignore malformed JSON from driver

            except asyncio.TimeoutError:
                await ws.send_text("ping")

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.warning("WS share error code=%s: %s", share_code, exc)
    finally:
        if role == "driver":
            await set_driver_connected(r, share_code, False)
        await ws_manager.disconnect(ws, share_code)


# ═══════════════ REAL-TIME TRACKING (Agent 3) ════════════════════════════════


@app.websocket("/ws/track/{tracking_code}")
async def ws_track(
    websocket: WebSocket,
    tracking_code: str,
    token: str = Query(...),
) -> None:
    """
    WebSocket endpoint for parents to receive live GPS from a tracked bus.
    
    Query params:
      token: JWT access token (required)
    
    Server sends:
      {"type": "position", "bus_number": "A1", "lat": ..., "lng": ..., ...}
      {"type": "parents_count", "count": 3}
      {"type": "ended", "reason": "driver_stopped"}
      "pong"
    
    Client sends:
      "ping" → server responds with "pong"
    """
    # 1. Validate token – URL‑decode first
    token = urllib.parse.unquote(token)
    try:
        claims = decode_token(token)
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid token")
        return

    # 2. Validate tracking code
    tracking_code = tracking_code.strip().upper()
    r = await get_redis()
    info = await r.hgetall(f"tracking:{tracking_code}:info")
    if not info:
        await websocket.close(code=4004, reason="Tracking session not found")
        return

    # 3. Accept connection
    await websocket.accept()
    broadcaster: TrackingBroadcaster = app.state.broadcaster

    try:
        # 4. Register with broadcaster
        await broadcaster.register(tracking_code, websocket)

        # Send current parents count immediately
        parent_count = await r.scard(f"tracking:{tracking_code}:parents")
        await websocket.send_json({"type": "parents_count", "count": parent_count})

        # 5. Send current location immediately (if available)
        current_loc = await r.hgetall(f"tracking:{tracking_code}:location")
        if current_loc:
            def _d(v):
                return v.decode() if isinstance(v, bytes) else v
            loc = {_d(k): _d(v) for k, v in current_loc.items()}
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

        # 6. Message loop — handle client pings and detect disconnects
        while True:
            try:
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=90,  # 90s inactivity timeout
                )
                if data == "ping":
                    await broadcaster.handle_heartbeat(websocket)
                # Ignore other messages from parent (read-only connection)
            except asyncio.TimeoutError:
                # No message for 90s — check if session still active
                still_active = await r.exists(
                    f"tracking:{tracking_code}:info"
                )
                if not still_active:
                    await websocket.send_json({
                        "type": "ended",
                        "reason": "session_expired",
                    })
                    break
                # Session active, send keepalive
                try:
                    await websocket.send_text("ping")
                except Exception:
                    break

    except WebSocketDisconnect:
        log.info("WS client disconnected: code=%s", tracking_code)
    except Exception as exc:
        log.error("WS error: code=%s err=%s", tracking_code, exc)
    finally:
        await broadcaster.unregister(websocket)


# ═══════════════ NOTIFICATIONS ═══════════════════════════════════════════════


@app.post("/api/notifications/register", tags=["notifications"])
async def register_notification(
    body:   FCMRegisterBody,
    claims: dict = Depends(require_any_auth),
) -> dict[str, str]:
    r = await get_redis()
    await register_fcm_token(r, body.stop_id, body.fcm_token)
    return {"status": "registered", "stop_id": body.stop_id}


@app.delete("/api/notifications/unregister", tags=["notifications"])
async def unregister_notification(
    body:   FCMRegisterBody,
    claims: dict = Depends(require_any_auth),
) -> dict[str, str]:
    r = await get_redis()
    await unregister_fcm_token(r, body.stop_id, body.fcm_token)
    return {"status": "unregistered"}


# ═══════════════ TRIP REPLAY ═════════════════════════════════════════════════


@app.get("/api/trips/{bus_id}/replay", tags=["admin"])
async def trip_replay(
    bus_id:    str,
    date_from: datetime = Query(...),
    date_to:   datetime = Query(...),
    claims:    dict     = Depends(require_any_auth),
) -> list[dict]:
    """Return ordered GPS history for route-replay. Max window: 24h."""
    if claims.get("role") == "driver":
        raise HTTPException(status_code=403, detail="Drivers cannot access replay")
    if (date_to - date_from).total_seconds() > 86400:
        raise HTTPException(status_code=400, detail="Max replay window is 24 hours")
    try:
        return await get_trip_replay(bus_id, date_from, date_to)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}")


# ═══════════════ QUERY / UTILITY ═════════════════════════════════════════════


@app.get("/api/run/{run_id}/location", tags=["tracking"])
async def run_location(
    run_id: str,
    claims: dict = Depends(require_any_auth),
) -> dict[str, Any]:
    r = await get_redis()
    loc_raw = await r.get(f"run:{run_id}:loc")
    if not loc_raw:
        raise HTTPException(status_code=404, detail="Run not found or expired")
    loc = json.loads(loc_raw)
    return {"run_id": run_id, **loc}


@app.get("/api/bus/{bus_id}/eta", tags=["tracking"])
async def bus_eta(
    bus_id:   str,
    dest_lat: float = Query(..., ge=KTM_BBOX[1], le=KTM_BBOX[3]),
    dest_lng: float = Query(..., ge=KTM_BBOX[0], le=KTM_BBOX[2]),
    claims:   dict  = Depends(require_any_auth),
) -> ETAResult:
    loc = await get_bus_location(bus_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Bus offline")
    url = (
        f"{OSRM_HOST}/route/v1/driving/"
        f"{loc['lng']},{loc['lat']};{dest_lng},{dest_lat}"
        f"?overview=false&steps=false"
    )
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    if data.get("code") != "Ok":
        raise HTTPException(status_code=502, detail="OSRM routing failed")
    r = data["routes"][0]
    eta_dt = datetime.now(tz=timezone.utc) + timedelta(seconds=r["duration"])
    return ETAResult(
        bus_id=bus_id,
        route_id=loc.get("route_id", ""),
        distance_m=r["distance"],
        duration_s=r["duration"],
        eta_iso=eta_dt.isoformat(),
    )


@app.get("/api/geocode", tags=["utility"])
async def geocode(
    q:      str  = Query(..., min_length=2),
    claims: dict = Depends(require_any_auth),
) -> Any:
    async with httpx.AsyncClient(
        timeout=8.0,
        headers={"User-Agent": "KathmanduBusTracker/3.0"},
    ) as client:
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": q, "format": "json", "limit": 5,
                "viewbox": f"{KTM_BBOX[0]},{KTM_BBOX[3]},{KTM_BBOX[2]},{KTM_BBOX[1]}",
                "bounded": 1,
                "countrycodes": "np",
            },
        )
        resp.raise_for_status()
        return resp.json()


# ═══════════════ ROUTES & ASSIGNMENT ═════════════════════════════════════════


@app.get("/api/routes", tags=["routes"])
async def list_routes(claims: dict = Depends(require_any_auth)) -> list[dict]:
    """Return all routes with live bus counts and stop info (from PostgreSQL)."""
    routes = await db_get_all_routes()
    r = await get_redis()
    result = []
    for route in routes:
        route_id = route["id"]
        bus_ids = await r.smembers(f"route:{route_id}:buses")
        active_count = 0
        for bid in bus_ids:
            if await r.exists(f"bus:{bid}:loc"):
                active_count += 1
        result.append({
            **route,
            "stop_count": len(route.get("stops", [])),
            "total_buses": len(bus_ids),
            "active_buses": active_count,
        })
    return result


@app.get("/api/routes/{route_id}", tags=["routes"])
async def get_route_detail(
    route_id: str, claims: dict = Depends(require_any_auth)
) -> dict:
    """Return single route detail with live bus positions (from PostgreSQL)."""
    route = await db_get_route(route_id)
    if not route:
        raise HTTPException(status_code=404, detail="Route not found")
    r = await get_redis()
    bus_ids = await r.smembers(f"route:{route_id}:buses")
    buses = []
    for bid in bus_ids:
        loc = await get_bus_location(bid)
        if loc:
            buses.append({"bus_id": bid, **loc})
    return {**route, "buses": buses}


@app.get("/api/driver/assignment", tags=["driver"])
async def driver_assignment(claims: dict = Depends(require_driver)) -> dict:
    """Return the authenticated driver's bus/route assignment."""
    assigned_bus = claims.get("assigned_bus", "")
    assigned_route = claims.get("assigned_route", "")
    if assigned_bus and assigned_route:
        route = await db_get_route(assigned_route)
        return {
            "bus_id": assigned_bus,
            "route_id": assigned_route,
            "route_name": route["name"] if route else assigned_route,
        }
    username = claims.get("sub", "")
    r = await get_redis()
    assignment = await r.hgetall(f"driver:{username}:assignment")
    if not assignment:
        raise HTTPException(status_code=404, detail="No assignment found")
    route = await db_get_route(assignment.get("route_id", ""))
    return {
        "bus_id": assignment.get("bus_id", ""),
        "route_id": assignment.get("route_id", ""),
        "route_name": route["name"] if route else "",
    }


# ═══════════════ ADMIN ROUTES CRUD ═══════════════════════════════════════════


class RouteCreateBody(BaseModel):
    id:          str = Field(..., min_length=1, max_length=64)
    name:        str = Field(..., min_length=1)
    description: str = ""
    color:       str = "#1B5E20"
    school_lat:  float = 0
    school_lng:  float = 0


class StopCreateBody(BaseModel):
    stop_id:    str = Field(..., min_length=1)
    name:       str = Field(..., min_length=1)
    lat:        float
    lng:        float
    sort_order: int = 0


@app.post("/api/admin/routes", tags=["admin"])
async def admin_create_route(
    body: RouteCreateBody, claims: dict = Depends(require_any_auth)
) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return await db_create_route(body.model_dump())


@app.put("/api/admin/routes/{route_id}", tags=["admin"])
async def admin_update_route(
    route_id: str, body: RouteCreateBody, claims: dict = Depends(require_any_auth)
) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return await db_update_route(route_id, body.model_dump())


@app.delete("/api/admin/routes/{route_id}", tags=["admin"])
async def admin_delete_route(
    route_id: str, claims: dict = Depends(require_any_auth)
) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return await db_delete_route(route_id)


@app.post("/api/admin/routes/{route_id}/stops", tags=["admin"])
async def admin_add_stop(
    route_id: str, body: StopCreateBody, claims: dict = Depends(require_any_auth)
) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return await db_add_stop(route_id, body.model_dump())


@app.delete("/api/admin/routes/{route_id}/stops/{stop_id}", tags=["admin"])
async def admin_remove_stop(
    route_id: str, stop_id: str, claims: dict = Depends(require_any_auth)
) -> dict:
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return await db_remove_stop(route_id, stop_id)


# ═══════════════ ADMIN SEED ══════════════════════════════════════════════════


@app.post("/api/admin/seed", tags=["admin"])
async def seed_test_data(claims: dict = Depends(require_any_auth)) -> dict[str, str]:
    """
    Seeds Redis with demo assignments. Call once after first deploy.
    Requires admin JWT (get one via /api/auth/otp/* with role=admin).
    """
    if claims.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    r = await get_redis()
    pipe = r.pipeline()
    pipe.hset("driver:driver1:assignment",
              mapping={"bus_id": "BUS_001", "route_id": "route_1"})
    pipe.hset("driver:driver2:assignment",
              mapping={"bus_id": "BUS_002", "route_id": "route_2"})
    pipe.hset("driver:driver3:assignment",
              mapping={"bus_id": "BUS_003", "route_id": "route_3"})
    pipe.sadd("parent:parent1:routes", "route_1")
    pipe.sadd("parent:parent2:routes", "route_1", "route_2")
    pipe.sadd("parent:parent3:routes", "route_3")
    await pipe.execute()
    return {"status": "seeded", "drivers": 3, "parents": 3}

# ── New Backend API: Leaderboard, Territory, Competitions ────────────────────────

@app.get("/api/leaderboard", tags=["stats"])
async def leaderboard(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        f"""SELECT u.username, u.id, COUNT(c.h3_index) as cell_count
            FROM cells c
            JOIN users u ON u.id = c.owner_id
            GROUP BY u.id, u.username
            ORDER BY cell_count DESC
            LIMIT :limit""",
        {"limit": limit},
    )
    rows = result.fetchall()
    sample = "8a2a100d2dfffff"
    cell_area = h3.cell_area(sample, unit="km^2")
    leaders = []
    for i, row in enumerate(rows):
        leaders.append({
            "rank": i + 1,
            "username": row[0],
            "user_id": row[1],
            "cell_count": row[2],
            "km2": round(row[2] * cell_area, 4),
        })
    return {"leaderboard": leaders}

@app.get("/api/territory/{user_id}", tags=["territory"])
async def territory(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        "SELECT h3_index FROM cells WHERE owner_id = :uid",
        {"uid": user_id},
    )
    cells = [row[0] for row in result.fetchall()]
    return {"user_id": user_id, "cells": cells, "count": len(cells)}

@app.get("/api/competitions", tags=["competitions"])
async def competitions(db: AsyncSession = Depends(get_db), token: dict = Depends(require_any_auth)):
    result = await db.execute(
        """SELECT id, name, prize_description, prize_image_url, starts_at, ends_at, status
           FROM competitions
           WHERE status IN ('active', 'upcoming')
           ORDER BY ends_at ASC"""
    )
    rows = result.fetchall()
    # token is the JWT claims dict — subject is stored in 'sub'
    user_id = token.get('sub', '') if isinstance(token, dict) else str(token)
    comps = []
    for row in rows:
        entry_res = await db.execute(
            """SELECT km2 FROM competition_entries
               WHERE competition_id = :cid AND user_id = :uid
               ORDER BY created_at DESC LIMIT 1""",
            {"cid": row[0], "uid": user_id},
        )
        entry = entry_res.fetchone()
        comps.append({
            "id": row[0],
            "name": row[1],
            "prize_description": row[2],
            "prize_image_url": row[3],
            "starts_at": row[4].isoformat() if row[4] else None,
            "ends_at": row[5].isoformat() if row[5] else None,
            "status": row[6],
            "my_km2": entry[0] if entry else 0.0,
        })
    return {"competitions": comps}

# ═══════════════ STRAVA INTEGRATION ═════════════════════════════════════════======\n\n@app.get("/api/strava/sync-status", tags=["strava"])\nasync def strava_sync_status(claims: dict = Depends(require_any_auth)):\n    """Check if a Strava sync is currently running for this user."""\n    user_id = claims.get("sub", "")\n    r = await get_redis()\n    status = await r.get(f"strava_sync:{user_id}:status")\n    return {"syncing": status == "syncing"}

@app.get("/api/strava/auth-url", tags=["strava"])
async def strava_auth_url(claims: dict = Depends(require_any_auth)):
    """Return the Strava OAuth authorization URL for the current user."""
    user_id = claims.get("sub", "")
    url = get_auth_url(state=user_id)
    return {"auth_url": url}


@app.get("/api/strava/callback", tags=["strava"])
async def strava_callback(code: str, state: str, scope: str = ""):
    """Handle Strava OAuth callback, exchange code for tokens, and save connection."""
    user_id = state
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing state (user_id)")
    try:
        token_data = await exchange_token(code)
    except Exception as e:
        log.error("Strava token exchange failed: %s", e)
        raise HTTPException(status_code=502, detail="Strava token exchange failed")
    await save_strava_connection(user_id, token_data)
    log.info("Strava connected: user=%s athlete=%s", user_id, token_data.get("athlete", {}).get("id"))
    redirect_url = f"{STRAVA_APP_REDIRECT}?success=true&athlete_id={token_data.get('athlete', {}).get('id', '')}"
    return RedirectResponse(url=redirect_url)


@app.get("/api/strava/status", tags=["strava"])
async def strava_status(claims: dict = Depends(require_any_auth)):
    """Return connection status and profile for the current user."""
    user_id = claims.get("sub", "")
    return await get_strava_status(user_id)


@app.post("/api/strava/sync", tags=["strava"])\nasync def strava_sync(claims: dict = Depends(require_any_auth)):\n    """Manually trigger a sync of recent Strava activities for the user."""\n    user_id = claims.get("sub", "")\n    r = await get_redis()\n    # Set sync status (TTL 5 min)\n    await r.setex(f"strava_sync:{user_id}:status", 300, "syncing")\n    # Notify client start\n    if user_id in active_connections:\n        await active_connections[user_id].send_text(json.dumps({\n            "type": "strava_sync_status",\n            "payload": {"status": "syncing"},\n        }))\n    result = {}\n    try:\n        result = await sync_user_activities(user_id)\n    finally:\n        # Clear status\n        await r.delete(f"strava_sync:{user_id}:status")\n        # Notify client complete\n        if user_id in active_connections:\n            await active_connections[user_id].send_text(json.dumps({\n                "type": "strava_sync_status",\n                "payload": {"status": "complete", **(result if isinstance(result, dict) else {})},\n            }))\n    return result


@app.delete("/api/strava/disconnect", tags=["strava"])
async def strava_disconnect(claims: dict = Depends(require_any_auth)):
    """Revoke Strava access and clear stored tokens for the user."""
    user_id = claims.get("sub", "")
    token = await get_valid_token(user_id)
    if token:
        await deauthorize(token)
    await clear_strava_connection(user_id)
    log.info("Strava disconnected: user=%s", user_id)
    return {"ok": True}


# Strava webhook verification (GET) and event processing (POST)
@app.get("/api/strava/webhook", tags=["strava"])
async def strava_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """Validate Strava webhook subscription (GET verification)."""
    if hub_mode == "subscribe" and hub_verify_token == STRAVA_WEBHOOK_VERIFY_TOKEN:
        return {"hub.challenge": hub_challenge}
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/api/strava/webhook", tags=["strava"])
async def strava_webhook_event(request: Request):
    """Receive Strava webhook events (activity.create) and process asynchronously."""
    event = await request.json()
    log.info("Strava webhook event: %s", event)
    asyncio.create_task(handle_webhook_event(event))
    return {"ok": True}


# ═══════════════ Helper Functions ═══════════════════════════════════════════════

# Strava integration routes added earlier in the file



def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Returns distance in km between two lat/lng points."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _accumulate_distance(polyline: list[list]) -> float:
    """Sum haversine distance across all points in polyline."""
    total = 0.0
    for i in range(1, len(polyline)):
        total += _haversine(
            polyline[i-1][0], polyline[i-1][1],
            polyline[i][0],   polyline[i][1],
        )
    return total


def _calc_duration(session: dict) -> int:
    """Returns elapsed seconds since run started."""
    try:
        start = datetime.fromisoformat(session["started_at"])
        return int((datetime.utcnow() - start).total_seconds())
    except Exception:
        return 0


def _calc_pace(distance_km: float, duration_s: int) -> float:
    """Returns pace in min/km. Returns 0 if no distance yet."""
    if distance_km < 0.01 or duration_s < 1:
        return 0.0
    return round((duration_s / 60) / distance_km, 2)
