"""
backend/services/trip_logger.py
=================================
Persistent trip audit trail.

Every 60 seconds, a background task snapshots all active bus positions
from Redis and writes them to PostgreSQL `trip_history` (JSONB).

Schema:
  trip_history(id, bus_id, route_id, position JSONB, recorded_at TIMESTAMPTZ)

JSONB payload:
  {lat, lng, speed, bearing, accuracy, ts}

This enables:
  • Route replay (playback a full school run)
  • Delay auditing (did bus arrive on time?)
  • Parent transparency dashboard
  • Future PostGIS upgrade for spatial queries

PostGIS upgrade path (commented at bottom):
  When you add PostGIS, change position column to GEOMETRY(POINT, 4326)
  and use ST_MakePoint(lng, lat) for sub-metre spatial indexing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone

import asyncpg
import redis.asyncio as aioredis

log = logging.getLogger("bustrack.triplog")

SNAPSHOT_INTERVAL_SECONDS = 60

# ──────────────────────────────────────────────────────────────────────────────
#  PostgreSQL connection pool
# ──────────────────────────────────────────────────────────────────────────────

_pg_pool: asyncpg.Pool | None = None

PG_DSN = os.getenv(
    "DATABASE_URL",
    "postgresql://bustrack:bustrack@postgres:5432/bustrack",
)


async def get_pg_pool() -> asyncpg.Pool:
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(
            PG_DSN,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pg_pool


async def close_pg_pool() -> None:
    global _pg_pool
    if _pg_pool:
        await _pg_pool.close()
        _pg_pool = None


# ──────────────────────────────────────────────────────────────────────────────
#  Schema bootstrap — run once at startup
# ──────────────────────────────────────────────────────────────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS trip_history (
    id          BIGSERIAL PRIMARY KEY,
    bus_id      TEXT        NOT NULL,
    route_id    TEXT        NOT NULL,
    position    JSONB       NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for route replay queries: WHERE bus_id = $1 ORDER BY recorded_at
CREATE INDEX IF NOT EXISTS idx_trip_history_bus_time
    ON trip_history (bus_id, recorded_at DESC);

-- Index for daily audit: WHERE recorded_at::date = $1
CREATE INDEX IF NOT EXISTS idx_trip_history_date
    ON trip_history (recorded_at DESC);

-- ── PostGIS upgrade (uncomment after: CREATE EXTENSION postgis) ────────────
-- ALTER TABLE trip_history ADD COLUMN IF NOT EXISTS geom GEOMETRY(POINT, 4326);
-- CREATE INDEX IF NOT EXISTS idx_trip_history_geom ON trip_history USING GIST(geom);
-- UPDATE trip_history SET geom = ST_SetSRID(
--     ST_MakePoint((position->>'lng')::float, (position->>'lat')::float), 4326
-- ) WHERE geom IS NULL;
"""

TRIP_REPLAY_SQL = """
SELECT bus_id, route_id, position, recorded_at
FROM trip_history
WHERE bus_id = $1
  AND recorded_at >= $2
  AND recorded_at <  $3
ORDER BY recorded_at ASC;
"""


async def init_schema() -> None:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
    log.info("trip_history schema initialised ✓")


# ──────────────────────────────────────────────────────────────────────────────
#  Snapshot worker
# ──────────────────────────────────────────────────────────────────────────────

async def _take_snapshot(r: aioredis.Redis) -> int:
    """
    Scan Redis for all bus:*:loc keys, batch-insert into trip_history.
    Returns count of rows written.
    """
    now = datetime.now(tz=timezone.utc)
    rows: list[tuple] = []

    # SCAN is non-blocking and won't starve other Redis ops
    async for key in r.scan_iter("bus:*:loc"):
        loc = await r.hgetall(key)
        if not loc:
            continue

        bus_id = key.split(":")[1]
        route_id = loc.get("route_id", "unknown")

        position_json = json.dumps({
            "lat":      float(loc.get("lat", 0)),
            "lng":      float(loc.get("lng", 0)),
            "speed":    float(loc.get("speed", 0)),
            "bearing":  float(loc.get("bearing", 0)),
            "ts":       float(loc.get("ts", 0)),
        })

        rows.append((bus_id, route_id, position_json, now))

    if not rows:
        return 0

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO trip_history (bus_id, route_id, position, recorded_at)
            VALUES ($1, $2, $3::jsonb, $4)
            """,
            rows,
        )

    log.debug("Trip snapshot: %d rows at %s", len(rows), now.isoformat())
    return len(rows)


# ──────────────────────────────────────────────────────────────────────────────
#  Long-running background task (launched from FastAPI lifespan)
# ──────────────────────────────────────────────────────────────────────────────

async def trip_logger_loop(r: aioredis.Redis) -> None:
    """
    Runs forever.  Sleeps SNAPSHOT_INTERVAL_SECONDS between snapshots.
    Errors are caught and logged — never crash the main process.
    """
    log.info("Trip logger started (interval=%ds)", SNAPSHOT_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(SNAPSHOT_INTERVAL_SECONDS)
        try:
            count = await _take_snapshot(r)
            if count:
                log.info("Trip snapshot: %d active buses logged", count)
        except asyncpg.PostgresError as exc:
            log.error("PostgreSQL snapshot error: %s", exc)
        except Exception as exc:
            log.error("Trip logger unexpected error: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
#  Route replay query — exposed via API
# ──────────────────────────────────────────────────────────────────────────────

async def get_trip_replay(
    bus_id: str,
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """
    Fetch ordered position history for a bus between two timestamps.
    Used by the Admin Panel "Route Replay" feature.
    """
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(TRIP_REPLAY_SQL, bus_id, date_from, date_to)

    return [
        {
            "bus_id":      row["bus_id"],
            "route_id":    row["route_id"],
            "position":    json.loads(row["position"]),
            "recorded_at": row["recorded_at"].isoformat(),
        }
        for row in rows
    ]
