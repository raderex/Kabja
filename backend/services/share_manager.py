"""
backend/services/share_manager.py
==================================
Share session management for link-based live tracking.

Replaces route-based tracking with temporary share-code-based system
for MVP testing. Driver generates a share code (e.g., ABC123D),
parents enter the code to join and receive real-time GPS.

PostgreSQL schema:
  share_sessions(id, share_code, driver_id, bus_id, created_at, expires_at, active)

Redis keys:
  share:{share_code}:info              HASH  {driver_id, bus_id, expires_at, driver_connected}
  share:{share_code}:parents           SET   {parent_id, ...}
  share:{share_code}:location          HASH  {lat, lng, speed, bearing, ts} TTL=30s
  driver:{driver_id}:active_share      STRING  share_code  TTL=expires_in
"""

from __future__ import annotations

import logging
import secrets
import string
import time
from datetime import datetime, timedelta, timezone

import redis.asyncio as aioredis

from services.trip_logger import get_pg_pool

log = logging.getLogger("bustrack.share")

SHARE_DEFAULT_MINUTES = 60
SHARE_MAX_MINUTES = 1440
SHARE_CODE_LENGTH = 6

SHARE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS share_sessions (
    id          SERIAL PRIMARY KEY,
    share_code  VARCHAR(10) UNIQUE NOT NULL,
    driver_id   VARCHAR(100) NOT NULL,
    bus_id      VARCHAR(100) NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL,
    active      BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_share_sessions_code ON share_sessions(share_code);
CREATE INDEX IF NOT EXISTS idx_share_sessions_driver ON share_sessions(driver_id);
"""


async def init_share_schema() -> None:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(SHARE_SCHEMA_SQL)
    log.info("share_sessions schema initialised ✓")


def generate_share_code(length: int = SHARE_CODE_LENGTH) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def create_share_session(
    r: aioredis.Redis,
    driver_id: str,
    bus_id: str,
    expires_in_minutes: int = SHARE_DEFAULT_MINUTES,
) -> dict:
    if expires_in_minutes < 1:
        expires_in_minutes = SHARE_DEFAULT_MINUTES
    if expires_in_minutes > SHARE_MAX_MINUTES:
        expires_in_minutes = SHARE_MAX_MINUTES

    for _ in range(10):
        share_code = generate_share_code()
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            existing = await conn.fetchval(
                "SELECT share_code FROM share_sessions WHERE share_code = $1 AND active = TRUE",
                share_code,
            )
            if not existing:
                break
    else:
        raise ValueError("Failed to generate unique share code")

    expires_at = datetime.now(tz=timezone.utc) + timedelta(minutes=expires_in_minutes)

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO share_sessions (share_code, driver_id, bus_id, expires_at) VALUES ($1, $2, $3, $4)",
            share_code, driver_id, bus_id, expires_at,
        )

    pipe = r.pipeline()
    pipe.hset(f"share:{share_code}:info", mapping={
        "driver_id": driver_id,
        "bus_id": bus_id,
        "expires_at": expires_at.isoformat(),
        "driver_connected": "0",
    })
    pipe.setex(f"driver:{driver_id}:active_share", expires_in_minutes * 60, share_code)
    await pipe.execute()

    log.info(
        "Share created: code=%s driver=%s bus=%s expires=%s",
        share_code, driver_id, bus_id, expires_at.isoformat(),
    )

    return {
        "share_code": share_code,
        "share_url": f"ktmbustrack://share/{share_code}",
        "expires_at": expires_at.isoformat(),
    }


async def validate_share_code(r: aioredis.Redis, share_code: str) -> dict | None:
    share_code = share_code.strip().upper()

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT share_code, driver_id, bus_id, expires_at, active
               FROM share_sessions
               WHERE share_code = $1 AND active = TRUE
               AND expires_at > NOW() AT TIME ZONE 'UTC'""",
            share_code,
        )
        if not row:
            return None
        return {
            "driver_id": row["driver_id"],
            "bus_id": row["bus_id"],
            "expires_at": row["expires_at"].isoformat(),
        }


async def add_parent_to_session(
    r: aioredis.Redis,
    share_code: str,
    parent_id: str,
) -> int:
    await r.sadd(f"share:{share_code}:parents", parent_id)
    count = await r.scard(f"share:{share_code}:parents")
    log.info("Parent joined share: code=%s parent=%s total=%d", share_code, parent_id, count)
    return count


async def remove_parent_from_session(
    r: aioredis.Redis,
    share_code: str,
    parent_id: str,
) -> int:
    await r.srem(f"share:{share_code}:parents", parent_id)
    return await r.scard(f"share:{share_code}:parents")


async def get_session_status(
    r: aioredis.Redis,
    share_code: str,
    active_ws_count: int = 0,
) -> dict | None:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT driver_id, bus_id, expires_at, active
               FROM share_sessions
               WHERE share_code = $1""",
            share_code,
        )
        if not row:
            return None
        if not row["active"]:
            return None

    parent_count = await r.scard(f"share:{share_code}:parents")

    return {
        "share_code": share_code,
        "driver_id": row["driver_id"],
        "bus_id": row["bus_id"],
        "active_parents": active_ws_count,
        "total_joined": parent_count,
        "expires_at": row["expires_at"].isoformat(),
    }


async def set_driver_connected(r: aioredis.Redis, share_code: str, connected: bool) -> None:
    await r.hset(f"share:{share_code}:info", "driver_connected", "1" if connected else "0")


async def is_driver_connected(r: aioredis.Redis, share_code: str) -> bool:
    val = await r.hget(f"share:{share_code}:info", "driver_connected")
    return val == "1"


async def get_active_share_for_driver(r: aioredis.Redis, driver_id: str) -> str | None:
    return await r.get(f"driver:{driver_id}:active_share")


async def store_share_location(r: aioredis.Redis, share_code: str, position: dict) -> None:
    await r.hset(f"share:{share_code}:location", mapping={
        "lat": str(position.get("lat", 0)),
        "lng": str(position.get("lng", 0)),
        "speed": str(position.get("speed", 0)),
        "bearing": str(position.get("bearing", 0)),
        "ts": str(position.get("ts", time.time())),
    })
    await r.expire(f"share:{share_code}:location", 30)


async def get_share_location(r: aioredis.Redis, share_code: str) -> dict | None:
    data = await r.hgetall(f"share:{share_code}:location")
    return data or None
