"""
backend/services/geofence.py
=============================
Geofencing service — checks bus proximity to student stops and fires
push notifications when the bus enters a radius.

Haversine implementation:
  distance = 2r · arcsin(√(sin²(Δφ/2) + cos φ₁ · cos φ₂ · sin²(Δλ/2)))

Notification backend: Firebase Cloud Messaging (FCM) v1 API.
Currently a mock that logs; swap _send_fcm_notification() for real
FCM HTTP v1 calls when you have a service account key.

Redis keys consumed:
  bus:{bus_id}:loc            — live bus position
  stop:{stop_id}:students     — SET of FCM tokens of subscribed students
  geofence:{bus_id}:{stop_id} — sentinel key (TTL=120s) to suppress repeat alerts
"""

from __future__ import annotations

import logging
import math
import os
import time
from dataclasses import dataclass

import httpx
import redis.asyncio as aioredis

log = logging.getLogger("bustrack.geofence")

GEOFENCE_RADIUS_METRES = 500       # trigger threshold
GEOFENCE_COOLDOWN_SECONDS = 120    # suppress re-trigger for 2 min per bus+stop pair


# ──────────────────────────────────────────────────────────────────────────────
#  Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StopCoord:
    stop_id: str
    name: str
    lat: float
    lng: float


# Static stop registry — replace with DB/Redis lookup in production
# Format: route_id → list of stops in order
STOP_REGISTRY: dict[str, list[StopCoord]] = {
    "route_1": [
        StopCoord("r1_s1", "Baneshwor Chowk",       27.6934, 85.3423),
        StopCoord("r1_s2", "Koteshwor",              27.6867, 85.3521),
        StopCoord("r1_s3", "Patan Dhoka",            27.6710, 85.3195),
        StopCoord("r1_s4", "Patan School Gate",      27.6678, 85.3213),
    ],
    "route_2": [
        StopCoord("r2_s1", "Boudha Stupa",           27.7215, 85.3622),
        StopCoord("r2_s2", "Chabahil",               27.7132, 85.3541),
        StopCoord("r2_s3", "Little Angels Gate",     27.7050, 85.3410),
    ],
    "route_3": [
        StopCoord("r3_s1", "Balaju Bus Park",        27.7372, 85.2980),
        StopCoord("r3_s2", "Samakhushi",             27.7298, 85.3120),
        StopCoord("r3_s3", "Budhanilkantha School",  27.7912, 85.3620),
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
#  Haversine formula
# ──────────────────────────────────────────────────────────────────────────────

_EARTH_RADIUS_M = 6_371_000.0   # metres


def haversine_metres(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Returns great-circle distance in metres between two WGS-84 points.
    All inputs in decimal degrees.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ──────────────────────────────────────────────────────────────────────────────
#  FCM notification
# ──────────────────────────────────────────────────────────────────────────────

FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")   # set in .env for production
FCM_API_URL = "https://fcm.googleapis.com/fcm/send"


async def _send_fcm_notification(
    fcm_tokens: list[str],
    bus_id: str,
    stop_name: str,
    distance_m: float,
) -> None:
    """
    Sends FCM push notification.
    Currently a MOCK — logs to console.
    Production: replace the log.info with the httpx.post block below.
    """
    title = "🚌 Bus Arriving Soon!"
    body = f"Bus {bus_id} is {int(distance_m)}m away from {stop_name}. Get ready!"

    log.info(
        "[FCM MOCK] → %d device(s) | bus=%s stop=%s dist=%.0fm",
        len(fcm_tokens), bus_id, stop_name, distance_m,
    )
    log.info("[FCM MOCK] title=%r body=%r", title, body)

    # ── Uncomment below for real FCM (Legacy HTTP API) ─────────────────────
    # if not FCM_SERVER_KEY:
    #     log.warning("FCM_SERVER_KEY not set — skipping real push")
    #     return
    # payload = {
    #     "registration_ids": fcm_tokens,
    #     "notification": {"title": title, "body": body, "sound": "default"},
    #     "data": {"bus_id": bus_id, "stop_name": stop_name, "type": "arrival_alert"},
    #     "android": {"priority": "high"},
    #     "apns": {"headers": {"apns-priority": "10"}},
    # }
    # async with httpx.AsyncClient(timeout=6.0) as client:
    #     resp = await client.post(
    #         FCM_API_URL,
    #         json=payload,
    #         headers={
    #             "Authorization": f"key={FCM_SERVER_KEY}",
    #             "Content-Type": "application/json",
    #         },
    #     )
    #     log.info("FCM response: %s %s", resp.status_code, resp.text)


# ──────────────────────────────────────────────────────────────────────────────
#  Main geofence check — called after each GPS ping
# ──────────────────────────────────────────────────────────────────────────────

async def check_geofences(
    r: aioredis.Redis,
    bus_id: str,
    route_id: str,
    bus_lat: float,
    bus_lng: float,
) -> list[dict]:
    """
    Check all stops on this route.  For each stop within GEOFENCE_RADIUS_METRES:
      1. Check cooldown sentinel in Redis to avoid spamming the same alert.
      2. Fetch subscribed FCM tokens for that stop.
      3. Fire notification.
      4. Set cooldown key.

    Returns list of triggered geofence events (for WebSocket broadcast).
    """
    stops = STOP_REGISTRY.get(route_id, [])
    events: list[dict] = []

    for stop in stops:
        dist = haversine_metres(bus_lat, bus_lng, stop.lat, stop.lng)

        if dist > GEOFENCE_RADIUS_METRES:
            continue

        # Cooldown check — avoid re-sending for the same bus+stop pair
        cooldown_key = f"geofence:{bus_id}:{stop.stop_id}"
        if await r.exists(cooldown_key):
            continue

        # Get subscribed FCM tokens for this stop
        raw_tokens = await r.smembers(f"stop:{stop.stop_id}:fcm_tokens")
        fcm_tokens = list(raw_tokens) if raw_tokens else []

        # Fire notification
        await _send_fcm_notification(fcm_tokens, bus_id, stop.name, dist)

        # Set cooldown
        await r.setex(cooldown_key, GEOFENCE_COOLDOWN_SECONDS, "1")

        event = {
            "type": "geofence_alert",
            "bus_id": bus_id,
            "stop_id": stop.stop_id,
            "stop_name": stop.name,
            "distance_m": round(dist, 1),
            "triggered_at": time.time(),
        }
        events.append(event)
        log.info(
            "Geofence triggered: bus=%s stop=%s dist=%.0fm",
            bus_id, stop.stop_id, dist,
        )

    return events


# ──────────────────────────────────────────────────────────────────────────────
#  Helper to register a parent's FCM token for a stop
# ──────────────────────────────────────────────────────────────────────────────

async def register_fcm_token(r: aioredis.Redis, stop_id: str, token: str) -> None:
    """Called from POST /api/notifications/register endpoint."""
    await r.sadd(f"stop:{stop_id}:fcm_tokens", token)
    log.info("FCM token registered for stop=%s", stop_id)


async def unregister_fcm_token(r: aioredis.Redis, stop_id: str, token: str) -> None:
    await r.srem(f"stop:{stop_id}:fcm_tokens", token)
