"""
backend/strava.py
Strava OAuth 2.0 + Activity Sync Service

Handles:
- OAuth authorization URL generation
- Token exchange (code → access_token + refresh_token)
- Token refresh (auto-refresh when expired)
- Activity fetching + import to territory engine
- Webhook event processing
"""
import os
import json
import time
import logging
from datetime import datetime, timezone

import httpx
from db import AsyncSessionLocal
from sqlalchemy import text

log = logging.getLogger("kabja.strava")

# ── Config ────────────────────────────────────────────────────────────────────

STRAVA_CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET", "")
STRAVA_REDIRECT_URI = os.environ.get("STRAVA_REDIRECT_URI", "")
STRAVA_WEBHOOK_VERIFY_TOKEN = os.environ.get("STRAVA_WEBHOOK_VERIFY_TOKEN", "kabja_strava_verify")
STRAVA_APP_REDIRECT = os.environ.get("STRAVA_APP_REDIRECT", "kabja://strava-callback")

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
STRAVA_DEAUTH_URL = "https://www.strava.com/oauth/deauthorize"

SCOPES = "read,activity:read_all"

# ── OAuth Flow ────────────────────────────────────────────────────────────────

def get_auth_url(state: str) -> str:
    """
    Build the Strava OAuth authorization URL.
    `state` should be the Kabja user_id (or a JWT) so we can map the callback.
    """
    params = {
        "client_id": STRAVA_CLIENT_ID,
        "redirect_uri": STRAVA_REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPES,
        "state": state,
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{STRAVA_AUTH_URL}?{qs}"


async def exchange_token(code: str) -> dict:
    """
    Exchange authorization code for access_token + refresh_token.
    Returns the full Strava token response including athlete profile.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
        })
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """
    Refresh an expired access token.
    Returns new access_token, refresh_token, expires_at.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(STRAVA_TOKEN_URL, data={
            "client_id": STRAVA_CLIENT_ID,
            "client_secret": STRAVA_CLIENT_SECRET,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        })
        resp.raise_for_status()
        return resp.json()


async def deauthorize(access_token: str) -> bool:
    """Revoke Strava access for a user."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(STRAVA_DEAUTH_URL, data={
                "access_token": access_token,
            })
            return resp.status_code == 200
    except Exception as e:
        log.warning("Strava deauth failed: %s", e)
        return False


# ── Token Management ──────────────────────────────────────────────────────────

async def get_valid_token(user_id: str) -> str | None:
    """
    Get a valid access token for a user.
    Auto-refreshes if expired. Updates DB with new tokens.
    Returns None if user has no Strava connection.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT strava_access_token, strava_refresh_token, strava_token_expires_at "
            "FROM users WHERE id = :uid"
        ), {"uid": user_id})
        row = result.fetchone()

        if not row or not row[0]:
            return None

        access_token, refresh_token, expires_at = row

        # Check if token is expired (with 5 min buffer)
        if expires_at and time.time() > (expires_at - 300):
            log.info("Strava token expired for user=%s, refreshing...", user_id)
            try:
                new_tokens = await refresh_access_token(refresh_token)
                access_token = new_tokens["access_token"]
                new_refresh = new_tokens.get("refresh_token", refresh_token)
                new_expires = new_tokens["expires_at"]

                async with db.begin():
                    await db.execute(text(
                        "UPDATE users SET "
                        "strava_access_token = :at, "
                        "strava_refresh_token = :rt, "
                        "strava_token_expires_at = :exp "
                        "WHERE id = :uid"
                    ), {
                        "at": access_token,
                        "rt": new_refresh,
                        "exp": new_expires,
                        "uid": user_id,
                    })
                log.info("Strava token refreshed for user=%s", user_id)
            except Exception as e:
                log.error("Strava token refresh failed for user=%s: %s", user_id, e)
                return None

        return access_token


async def save_strava_connection(user_id: str, token_data: dict) -> None:
    """
    Save Strava OAuth tokens and athlete profile to the users table.
    Called after successful OAuth callback.
    """
    athlete = token_data.get("athlete", {})
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(text(
                "UPDATE users SET "
                "strava_athlete_id = :aid, "
                "strava_access_token = :at, "
                "strava_refresh_token = :rt, "
                "strava_token_expires_at = :exp, "
                "strava_scope = :scope, "
                "strava_connected_at = now(), "
                "strava_profile = :profile "
                "WHERE id = :uid"
            ), {
                "aid": athlete.get("id"),
                "at": token_data["access_token"],
                "rt": token_data["refresh_token"],
                "exp": token_data["expires_at"],
                "scope": SCOPES,
                "profile": json.dumps(athlete),
                "uid": user_id,
            })


async def clear_strava_connection(user_id: str) -> None:
    """Remove all Strava data for a user."""
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(text(
                "UPDATE users SET "
                "strava_athlete_id = NULL, "
                "strava_access_token = NULL, "
                "strava_refresh_token = NULL, "
                "strava_token_expires_at = NULL, "
                "strava_scope = NULL, "
                "strava_connected_at = NULL, "
                "strava_profile = NULL "
                "WHERE id = :uid"
            ), {"uid": user_id})


# ── Activity Import ───────────────────────────────────────────────────────────

async def fetch_activities(access_token: str, after: int = 0, page: int = 1, per_page: int = 30) -> list[dict]:
    """
    Fetch activities from Strava API.
    Filters to Run/Walk/Hike types only.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"after": after, "page": page, "per_page": per_page},
        )
        resp.raise_for_status()
        activities = resp.json()

        # Filter to run/walk/hike types only
        valid_types = {"Run", "Walk", "Hike", "TrailRun", "VirtualRun"}
        return [a for a in activities if a.get("type") in valid_types]


async def fetch_activity_detail(access_token: str, activity_id: int) -> dict:
    """Fetch full detail (including polyline) for a single activity."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{STRAVA_API_BASE}/activities/{activity_id}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"include_all_efforts": "false"},
        )
        resp.raise_for_status()
        return resp.json()


async def import_activity(user_id: str, activity: dict) -> dict | None:
    """
    Import a single Strava activity into Kabja's territory system.

    1. Check if already imported
    2. Decode the polyline
    3. Call territory.process_run() to claim cells
    4. Record in strava_imported_activities
    Returns the territory result or None if skipped.
    """
    import polyline as polyline_lib # pip install polyline
    from territory import process_run

    activity_id = activity["id"]

    async with AsyncSessionLocal() as db:
        # Check if already imported
        result = await db.execute(text(
            "SELECT 1 FROM strava_imported_activities WHERE strava_activity_id = :aid"
        ), {"aid": activity_id})
        if result.fetchone():
            return None # already imported

        # Decode polyline from summary_polyline
        encoded = activity.get("map", {}).get("summary_polyline")
        if not encoded:
            log.warning("Activity %s has no polyline, skipping", activity_id)
            return None

        coords = polyline_lib.decode(encoded) # returns [(lat, lng), ...]
        polyline_points = [[lat, lng] for lat, lng in coords]

        if len(polyline_points) < 2:
            return None

        # Build session dict for territory engine
        import uuid as uuid_lib
        run_id = str(uuid_lib.uuid4())
        session = {
            "run_id": run_id,
            "user_id": user_id,
            "polyline": polyline_points,
            "distance_km": activity.get("distance", 0) / 1000.0,
            "started_at": activity.get("start_date"),
            "finished_at": activity.get("start_date"), # approximate
            "source": "strava",
        }

        # Process through territory engine
        try:
            result = await process_run(session)
        except Exception as e:
            log.error("Territory processing failed for Strava activity %s: %s", activity_id, e)
            return None

        # Record the import
        async with AsyncSessionLocal() as db:
            async with db.begin():
                await db.execute(text("""
                INSERT INTO strava_imported_activities
                (strava_activity_id, user_id, run_id, activity_name, activity_type,
                distance_km, moving_time_s, start_date)
                VALUES (:aid, :uid, :rid, :name, :type, :dist, :time, :start)
                ON CONFLICT (strava_activity_id) DO NOTHING
                """), {
                    "aid": activity_id,
                    "uid": user_id,
                    "rid": run_id,
                    "name": activity.get("name", ""),
                    "type": activity.get("type", ""),
                    "dist": activity.get("distance", 0) / 1000.0,
                    "time": activity.get("moving_time", 0),
                    "start": activity.get("start_date"),
                })

        log.info("Imported Strava activity %s → run %s (%s cells)",
                activity_id, run_id, result.get("cells_captured", 0))
        # ── Push real-time notification to connected user via WebSocket
        try:
            from main import active_connections
            if user_id in active_connections:
                await active_connections[user_id].send_text(json.dumps({
                    "type": "strava_sync",
                    "payload": {
                        "activity_name": activity.get("name", "Strava Activity"),
                        "activity_type": activity.get("type", "Run"),
                        "cells_captured": result.get("cells_captured", 0),
                        "km2_captured": result.get("km2_captured", 0.0),
                        "distance_km": activity.get("distance", 0) / 1000.0,
                        "source": "strava",
                        "strava_activity_id": activity_id,
                    },
                }))
        except Exception as e:
            log.warning("Failed to push strava_sync WS: %s", e)
        return result


async def sync_user_activities(user_id: str, max_pages: int = 3) -> dict:
    """
    Sync recent Strava activities for a user.
    Returns summary: { imported: int, skipped: int, total_cells: int }
    """
    access_token = await get_valid_token(user_id)
    if not access_token:
        return {"error": "No Strava connection"}

    imported = 0
    skipped = 0
    total_cells = 0

    for page in range(1, max_pages + 1):
        activities = await fetch_activities(access_token, page=page)
        if not activities:
            break

        for activity in activities:
            # Get full detail for polyline
            try:
                detail = await fetch_activity_detail(access_token, activity["id"])
                result = await import_activity(user_id, detail)
                if result:
                    imported += 1
                    total_cells += result.get("cells_captured", 0)
                else:
                    skipped += 1
            except Exception as e:
                log.warning("Failed to import activity %s: %s", activity["id"], e)
                skipped += 1

    return {"imported": imported, "skipped": skipped, "total_cells": total_cells}


# ── Webhook Processing ────────────────────────────────────────────────────────

async def handle_webhook_event(event: dict) -> None:
    """
    Process incoming Strava webhook event.
    We only care about activity.create events.
    """
    object_type = event.get("object_type")
    aspect_type = event.get("aspect_type")
    athlete_id = event.get("owner_id")
    activity_id = event.get("object_id")

    if object_type != "activity" or aspect_type != "create":
        return # ignore non-activity events

    # Find user by strava_athlete_id
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT id FROM users WHERE strava_athlete_id = :aid"
        ), {"aid": athlete_id})
        row = result.fetchone()
        if not row:
            log.warning("Webhook: no user found for athlete_id=%s", athlete_id)
            return
        user_id = row[0]

    # Get valid token and fetch the activity
    access_token = await get_valid_token(user_id)
    if not access_token:
        log.warning("Webhook: no valid token for user=%s", user_id)
        return

    try:
        detail = await fetch_activity_detail(access_token, activity_id)
        result = await import_activity(user_id, detail)
        if result:
            log.info("Webhook: auto-imported activity %s for user %s", activity_id, user_id)
    except Exception as e:
        log.error("Webhook: failed to process activity %s: %s", activity_id, e)


async def get_strava_status(user_id: str) -> dict:
    """Return Strava connection status for a user."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(
            "SELECT strava_athlete_id, strava_connected_at, strava_profile, strava_scope "
            "FROM users WHERE id = :uid"
        ), {"uid": user_id})
        row = result.fetchone()

        if not row or not row[0]:
            return {"connected": False}

        profile = {}
        if row[2]:
            try:
                profile = json.loads(row[2])
            except Exception:
                pass

        # Count imported activities
        count_result = await db.execute(text(
            "SELECT COUNT(*) FROM strava_imported_activities WHERE user_id = :uid"
        ), {"uid": user_id})
        count = count_result.scalar() or 0

        return {
            "connected": True,
            "athlete_id": row[0],
            "connected_at": row[1].isoformat() if row[1] else None,
            "scope": row[3],
            "profile": {
                "firstname": profile.get("firstname", ""),
                "lastname": profile.get("lastname", ""),
                "profile_pic": profile.get("profile", ""),
                "city": profile.get("city", ""),
                "country": profile.get("country", ""),
            },
            "imported_activities": count,
        }