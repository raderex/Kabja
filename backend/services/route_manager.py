"""
backend/services/route_manager.py
==================================
Dynamic route & stop management — PostgreSQL backed.

Replaces the hardcoded ROUTE_REGISTRY and STOP_REGISTRY with
database-backed CRUD so admins can add/edit/delete routes and stops
from the API (or a future admin panel).

Tables:
  routes(id, name, description, color, school_lat, school_lng, created_at)
  stops(id, route_id FK, stop_id, name, lat, lng, sort_order, created_at)

On startup, seeds default data if tables are empty.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from services.trip_logger import get_pg_pool

log = logging.getLogger("bustrack.routes")

# ──────────────────────────────────────────────────────────────────────────────
#  Schema
# ──────────────────────────────────────────────────────────────────────────────

CREATE_ROUTES_SQL = """
CREATE TABLE IF NOT EXISTS routes (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '#1B5E20',
    school_lat  DOUBLE PRECISION NOT NULL DEFAULT 0,
    school_lng  DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stops (
    id          BIGSERIAL PRIMARY KEY,
    route_id    TEXT NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    stop_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    lat         DOUBLE PRECISION NOT NULL,
    lng         DOUBLE PRECISION NOT NULL,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(route_id, stop_id)
);

CREATE INDEX IF NOT EXISTS idx_stops_route ON stops(route_id, sort_order);
"""

# Default seed data (same as the old hardcoded registries)
DEFAULT_ROUTES = [
    {
        "id": "route_1",
        "name": "Baneshwor → Patan School",
        "description": "Via Koteshwor and Patan Dhoka",
        "color": "#1B5E20",
        "school_lat": 27.7172,
        "school_lng": 85.3240,
        "stops": [
            ("r1_s1", "Baneshwor Chowk",  27.6934, 85.3423, 1),
            ("r1_s2", "Koteshwor",         27.6867, 85.3521, 2),
            ("r1_s3", "Patan Dhoka",       27.6710, 85.3195, 3),
            ("r1_s4", "Patan School Gate", 27.6678, 85.3213, 4),
        ],
    },
    {
        "id": "route_2",
        "name": "Boudha → Little Angels",
        "description": "Via Chabahil",
        "color": "#0D47A1",
        "school_lat": 27.6913,
        "school_lng": 85.3420,
        "stops": [
            ("r2_s1", "Boudha Stupa",       27.7215, 85.3622, 1),
            ("r2_s2", "Chabahil",            27.7132, 85.3541, 2),
            ("r2_s3", "Little Angels Gate",  27.7050, 85.3410, 3),
        ],
    },
    {
        "id": "route_3",
        "name": "Balaju → Budhanilkantha",
        "description": "Via Samakhushi",
        "color": "#E65100",
        "school_lat": 27.7041,
        "school_lng": 85.3145,
        "stops": [
            ("r3_s1", "Balaju Bus Park",       27.7372, 85.2980, 1),
            ("r3_s2", "Samakhushi",             27.7298, 85.3120, 2),
            ("r3_s3", "Budhanilkantha School",  27.7912, 85.3620, 3),
        ],
    },
]

# ──────────────────────────────────────────────────────────────────────────────
#  In-memory fallback — returned when PostgreSQL is unavailable or empty.
#  The app must NEVER show an empty route list.
# ──────────────────────────────────────────────────────────────────────────────

FALLBACK_ROUTES: list[dict[str, Any]] = [
    {
        "id": "route_1",
        "name": "Baneshwor → Patan School",
        "description": "Via Koteshwor and Patan Dhoka",
        "color": "#1B5E20",
        "school_lat": 27.7172,
        "school_lng": 85.3240,
        "stops": [
            {"stop_id": "r1_s1", "name": "Baneshwor Chowk",  "lat": 27.6934, "lng": 85.3423},
            {"stop_id": "r1_s2", "name": "Koteshwor",         "lat": 27.6867, "lng": 85.3521},
            {"stop_id": "r1_s3", "name": "Patan Dhoka",       "lat": 27.6710, "lng": 85.3195},
            {"stop_id": "r1_s4", "name": "Patan School Gate", "lat": 27.6678, "lng": 85.3213},
        ],
    },
    {
        "id": "route_2",
        "name": "Boudha → Little Angels",
        "description": "Via Chabahil",
        "color": "#0D47A1",
        "school_lat": 27.6913,
        "school_lng": 85.3420,
        "stops": [
            {"stop_id": "r2_s1", "name": "Boudha Stupa",      "lat": 27.7215, "lng": 85.3622},
            {"stop_id": "r2_s2", "name": "Chabahil",           "lat": 27.7132, "lng": 85.3541},
            {"stop_id": "r2_s3", "name": "Little Angels Gate", "lat": 27.7050, "lng": 85.3410},
        ],
    },
    {
        "id": "route_3",
        "name": "Balaju → Budhanilkantha",
        "description": "Via Samakhushi",
        "color": "#E65100",
        "school_lat": 27.7041,
        "school_lng": 85.3145,
        "stops": [
            {"stop_id": "r3_s1", "name": "Balaju Bus Park",      "lat": 27.7372, "lng": 85.2980},
            {"stop_id": "r3_s2", "name": "Samakhushi",            "lat": 27.7298, "lng": 85.3120},
            {"stop_id": "r3_s3", "name": "Budhanilkantha School", "lat": 27.7912, "lng": 85.3620},
        ],
    },
]



# ──────────────────────────────────────────────────────────────────────────────

async def init_route_schema() -> None:
    """Create tables and seed default data if empty."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(CREATE_ROUTES_SQL)
        count = await conn.fetchval("SELECT COUNT(*) FROM routes")
        if count == 0:
            log.info("Seeding default routes and stops...")
            for route in DEFAULT_ROUTES:
                await conn.execute(
                    """INSERT INTO routes (id, name, description, color, school_lat, school_lng)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT (id) DO NOTHING""",
                    route["id"], route["name"], route["description"],
                    route["color"], route["school_lat"], route["school_lng"],
                )
                for stop_id, name, lat, lng, order in route["stops"]:
                    await conn.execute(
                        """INSERT INTO stops (route_id, stop_id, name, lat, lng, sort_order)
                           VALUES ($1, $2, $3, $4, $5, $6)
                           ON CONFLICT (route_id, stop_id) DO NOTHING""",
                        route["id"], stop_id, name, lat, lng, order,
                    )
            log.info("Default routes seeded ✓")
    log.info("Route schema initialised ✓")


# ──────────────────────────────────────────────────────────────────────────────
#  Read
# ──────────────────────────────────────────────────────────────────────────────

async def get_all_routes() -> list[dict[str, Any]]:
    """Return all routes with stops. Falls back to in-memory data if DB unavailable or empty."""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            routes = await conn.fetch(
                "SELECT id, name, description, color, school_lat, school_lng FROM routes ORDER BY id"
            )
            if not routes:
                log.warning("Routes table is empty — returning in-memory fallback")
                return FALLBACK_ROUTES
            result = []
            for r in routes:
                stops = await conn.fetch(
                    "SELECT stop_id, name, lat, lng FROM stops WHERE route_id = $1 ORDER BY sort_order",
                    r["id"],
                )
                result.append({
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "color": r["color"],
                    "school_lat": r["school_lat"],
                    "school_lng": r["school_lng"],
                    "stops": [dict(s) for s in stops],
                })
            return result
    except Exception as exc:
        log.warning("PostgreSQL unavailable for get_all_routes — using fallback: %s", exc)
        return FALLBACK_ROUTES


async def get_route(route_id: str) -> dict[str, Any] | None:
    """Return a single route with stops. Falls back to in-memory data if DB unavailable."""
    try:
        pool = await get_pg_pool()
        async with pool.acquire() as conn:
            r = await conn.fetchrow(
                "SELECT id, name, description, color, school_lat, school_lng FROM routes WHERE id = $1",
                route_id,
            )
            if not r:
                # DB row missing — try fallback
                return next((x for x in FALLBACK_ROUTES if x["id"] == route_id), None)
            stops = await conn.fetch(
                "SELECT stop_id, name, lat, lng FROM stops WHERE route_id = $1 ORDER BY sort_order",
                route_id,
            )
            return {**dict(r), "stops": [dict(s) for s in stops]}
    except Exception as exc:
        log.warning("PostgreSQL unavailable for get_route(%s) — using fallback: %s", route_id, exc)
        return next((x for x in FALLBACK_ROUTES if x["id"] == route_id), None)


async def get_stops_for_route(route_id: str) -> list[dict]:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT stop_id, name, lat, lng FROM stops WHERE route_id = $1 ORDER BY sort_order",
            route_id,
        )
        return [dict(r) for r in rows]


async def get_school_coords() -> dict[str, tuple[float, float]]:
    """Return route_id → (school_lat, school_lng) for ETA computation."""
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, school_lat, school_lng FROM routes")
        return {r["id"]: (r["school_lat"], r["school_lng"]) for r in rows}


# ──────────────────────────────────────────────────────────────────────────────
#  CRUD — Admin
# ──────────────────────────────────────────────────────────────────────────────

async def create_route(data: dict[str, Any]) -> dict:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO routes (id, name, description, color, school_lat, school_lng)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            data["id"], data["name"], data.get("description", ""),
            data.get("color", "#1B5E20"),
            data.get("school_lat", 0), data.get("school_lng", 0),
        )
    return {"status": "created", "route_id": data["id"]}


async def update_route(route_id: str, data: dict[str, Any]) -> dict:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE routes SET name=$2, description=$3, color=$4,
               school_lat=$5, school_lng=$6 WHERE id=$1""",
            route_id, data["name"], data.get("description", ""),
            data.get("color", "#1B5E20"),
            data.get("school_lat", 0), data.get("school_lng", 0),
        )
    return {"status": "updated", "route_id": route_id}


async def delete_route(route_id: str) -> dict:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM routes WHERE id = $1", route_id)
    return {"status": "deleted", "route_id": route_id}


async def add_stop(route_id: str, data: dict[str, Any]) -> dict:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO stops (route_id, stop_id, name, lat, lng, sort_order)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (route_id, stop_id) DO UPDATE
               SET name=$3, lat=$4, lng=$5, sort_order=$6""",
            route_id, data["stop_id"], data["name"],
            data["lat"], data["lng"], data.get("sort_order", 0),
        )
    return {"status": "added", "stop_id": data["stop_id"]}


async def remove_stop(route_id: str, stop_id: str) -> dict:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM stops WHERE route_id = $1 AND stop_id = $2",
            route_id, stop_id,
        )
    return {"status": "removed", "stop_id": stop_id}
