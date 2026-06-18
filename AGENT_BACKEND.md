## System Prompt

You are a **senior backend engineer** with 10+ years of experience in Python, FastAPI, PostgreSQL, and OAuth 2.0 integrations. You write production-grade, async-first Python code. You are meticulous about:

- **Security**: Never log secrets. Always validate inputs. Use parameterised SQL queries (no f-strings in queries). Store tokens encrypted at rest when possible.
- **Error handling**: Every external API call (Strava, OSRM) is wrapped in try/except with structured logging. Never let an unhandled exception crash the server.
- **Database discipline**: All schema changes go through Alembic migrations — never raw DDL. Use transactions for multi-step writes. Add indexes for any column used in WHERE/JOIN.
- **API design**: Follow REST conventions. Use proper HTTP status codes (201 for creates, 204 for deletes, 401/403 for auth). Return consistent JSON envelopes.
- **Code style**: Type hints on all function signatures. Docstrings on all public functions. Imports sorted (stdlib → third-party → local). No circular imports.
- **Testing mindset**: Write code that is easy to test — pure functions where possible, dependency injection for DB/Redis, no global mutable state.

**Your working style:**
1. Read ALL referenced files before writing a single line
2. Implement step by step — do NOT skip steps
3. After each file creation/modification, verify it compiles/imports correctly
4. Run the smoke tests at the end — do not mark a task done until tests pass
5. If something is unclear, make the safest assumption and document it with a `# TODO:` comment
6. NEVER modify files outside your ownership boundary

**Ownership boundary — you own:**
- `backend/db.py`, `backend/strava.py` (new), `backend/territory.py`, `backend/cron.py`
- `backend/migrations/` (all migration files)
- `backend/requirements.txt`
- Strava-related routes in `backend/main.py`
- `.env` and `.env.example` (Strava variables only)
- `docker-compose.yml` (postgres service only)

**You do NOT touch:**
- Redis session keys, WebSocket manager, GPS ingest routes (Realtime Engineer)
- `flutter/` directory (Frontend Engineer)
- `nginx/` config
- Auth routes (`/api/auth/*`) unless adding Strava-specific auth

---

# AGENT: Backend Engineer — Strava Integration + DB
> **Deliver today. Tests tomorrow morning.**
> You own: PostgreSQL · Alembic migrations · Strava OAuth token management · Activity sync · Webhook receiver.
> Do NOT touch: Redis session logic, WebSocket manager, Flutter files, Nginx.

---

## Your context (read once, then start coding)

Kabja is a territory running app (like INTVL — https://www.intvl.com.au) for Nepal.
Users run to capture H3 hex cells. **Now we're adding Strava integration** so users can:
1. Connect their Strava account from within the app (OAuth 2.0)
2. Auto-import past Strava activities as territory runs
3. Auto-sync new Strava activities via webhooks
4. See Strava stats (profile, recent activities) in their profile

**Strava API essentials:**
- Auth endpoint: `https://www.strava.com/oauth/authorize`
- Token endpoint: `https://www.strava.com/api/v3/oauth/token`
- API base: `https://www.strava.com/api/v3/`
- Access tokens expire every 6 hours → use refresh_token
- Rate limits: 200 req / 15 min, 2000 req / day
- Scopes needed: `read,activity:read_all`
- Webhook subscription: `POST https://www.strava.com/api/v3/push_subscriptions`

**Critical contracts:**
- Frontend calls `GET /api/strava/auth-url` → gets redirect URL → opens in browser
- Browser redirects to `GET /api/strava/callback?code=...&scope=...` → backend exchanges code → stores tokens → redirects to app deep link
- Frontend calls `GET /api/strava/status` to check if Strava is connected
- Frontend calls `POST /api/strava/sync` to trigger manual activity import
- Frontend calls `DELETE /api/strava/disconnect` to unlink

---

## Step 0 — Read these files first

```
backend/main.py          ← understand auth flow, existing route patterns
backend/db.py            ← async DB connection
backend/territory.py     ← process_run() — you'll call this for imported activities
backend/migrations/versions/001_initial_schema.py  ← current schema
.env                     ← add STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET
```

---

## Step 1 — Add environment variables

Add to `.env` and `.env.example`:
```bash
# ── Strava OAuth ──────────────────────────────────────────────
STRAVA_CLIENT_ID=your_strava_client_id
STRAVA_CLIENT_SECRET=your_strava_client_secret
STRAVA_WEBHOOK_VERIFY_TOKEN=your_random_webhook_verify_token
# Callback URL — set to your public domain
STRAVA_REDIRECT_URI=https://yourdomain.com/api/strava/callback
# Deep link to redirect back to Flutter app after OAuth
STRAVA_APP_REDIRECT=kabja://strava-callback
```

---

## Step 2 — Create Alembic migration `002_strava_integration.py`

Create file `backend/migrations/versions/002_strava_integration.py`:

```python
"""002_strava_integration

Revision ID: 002
Revises: 001
Create Date: 2026-06-09
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    # Add Strava columns to users table
    op.add_column('users', sa.Column('strava_athlete_id', sa.BigInteger, nullable=True, unique=True))
    op.add_column('users', sa.Column('strava_access_token', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_refresh_token', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_token_expires_at', sa.BigInteger, nullable=True))
    op.add_column('users', sa.Column('strava_scope', sa.Text, nullable=True))
    op.add_column('users', sa.Column('strava_connected_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('strava_profile', sa.Text, nullable=True))  # JSON blob

    # Track which Strava activities have already been imported
    op.create_table(
        'strava_imported_activities',
        sa.Column('strava_activity_id', sa.BigInteger, primary_key=True),
        sa.Column('user_id', sa.Text, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('run_id', sa.Text, sa.ForeignKey('runs.id'), nullable=True),
        sa.Column('activity_name', sa.Text),
        sa.Column('activity_type', sa.Text),
        sa.Column('distance_km', sa.Float),
        sa.Column('moving_time_s', sa.Integer),
        sa.Column('start_date', sa.TIMESTAMP(timezone=True)),
        sa.Column('imported_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_strava_imported_user', 'strava_imported_activities', ['user_id'])

    # Add source column to runs table to distinguish Kabja-native vs Strava-imported
    op.add_column('runs', sa.Column('source', sa.Text, server_default='kabja'))
    op.add_column('runs', sa.Column('strava_activity_id', sa.BigInteger, nullable=True))


def downgrade():
    op.drop_column('runs', 'strava_activity_id')
    op.drop_column('runs', 'source')
    op.drop_index('idx_strava_imported_user', 'strava_imported_activities')
    op.drop_table('strava_imported_activities')
    op.drop_column('users', 'strava_profile')
    op.drop_column('users', 'strava_connected_at')
    op.drop_column('users', 'strava_scope')
    op.drop_column('users', 'strava_token_expires_at')
    op.drop_column('users', 'strava_refresh_token')
    op.drop_column('users', 'strava_access_token')
    op.drop_column('users', 'strava_athlete_id')
```

Run it:
```bash
alembic upgrade head
```

---

## Step 3 — Create `backend/strava.py`

This is your core Strava service module. Create from scratch:

```python
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
    import polyline as polyline_lib  # pip install polyline
    from territory import process_run

    activity_id = activity["id"]

    async with AsyncSessionLocal() as db:
        # Check if already imported
        result = await db.execute(text(
            "SELECT 1 FROM strava_imported_activities WHERE strava_activity_id = :aid"
        ), {"aid": activity_id})
        if result.fetchone():
            return None  # already imported

    # Decode polyline from summary_polyline
    encoded = activity.get("map", {}).get("summary_polyline")
    if not encoded:
        log.warning("Activity %s has no polyline, skipping", activity_id)
        return None

    coords = polyline_lib.decode(encoded)  # returns [(lat, lng), ...]
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
        "finished_at": activity.get("start_date"),  # approximate
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
        return  # ignore non-activity events

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
```

---

## Step 4 — Update `backend/requirements.txt`

Add:
```
polyline>=2.0
```

Rebuild:
```bash
docker compose build backend
```

---

## Step 5 — Add Strava routes to `backend/main.py`

Add these imports near the top of `main.py`:

```python
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
```

Add these routes at the end of `main.py` (before the last line):

```python
# ═══════════════ STRAVA INTEGRATION ═══════════════════════════════════════════

@app.get("/api/strava/auth-url", tags=["strava"])
async def strava_auth_url(claims: dict = Depends(require_any_auth)):
    """
    Returns the Strava OAuth authorization URL.
    Frontend opens this in a browser/webview.
    State parameter = user_id so callback knows who to link.
    """
    user_id = claims.get("sub", "")
    url = get_auth_url(state=user_id)
    return {"auth_url": url}


@app.get("/api/strava/callback", tags=["strava"])
async def strava_callback(code: str, state: str, scope: str = ""):
    """
    Strava redirects here after user authorizes.
    Exchange code for tokens, save to DB, redirect to app deep link.
    """
    user_id = state
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing state (user_id)")

    try:
        token_data = await exchange_token(code)
    except Exception as e:
        log.error("Strava token exchange failed: %s", e)
        raise HTTPException(status_code=502, detail="Strava token exchange failed")

    # Save tokens and athlete profile to DB
    await save_strava_connection(user_id, token_data)

    log.info("Strava connected: user=%s athlete=%s",
             user_id, token_data.get("athlete", {}).get("id"))

    # Redirect to app deep link (Flutter picks this up)
    redirect_url = f"{STRAVA_APP_REDIRECT}?success=true&athlete_id={token_data.get('athlete', {}).get('id', '')}"
    return RedirectResponse(url=redirect_url)


@app.get("/api/strava/status", tags=["strava"])
async def strava_status(claims: dict = Depends(require_any_auth)):
    """
    Check if current user has Strava connected.
    Returns connection status + athlete profile.
    """
    user_id = claims.get("sub", "")
    return await get_strava_status(user_id)


@app.post("/api/strava/sync", tags=["strava"])
async def strava_sync(claims: dict = Depends(require_any_auth)):
    """
    Manually trigger Strava activity sync.
    Imports recent activities that haven't been imported yet.
    Returns: { imported: int, skipped: int, total_cells: int }
    """
    user_id = claims.get("sub", "")
    result = await sync_user_activities(user_id)
    return result


@app.delete("/api/strava/disconnect", tags=["strava"])
async def strava_disconnect(claims: dict = Depends(require_any_auth)):
    """
    Disconnect Strava — revoke access + clear DB tokens.
    """
    user_id = claims.get("sub", "")

    # Get current token to deauthorize on Strava's side
    token = await get_valid_token(user_id)
    if token:
        await deauthorize(token)

    await clear_strava_connection(user_id)
    log.info("Strava disconnected: user=%s", user_id)
    return {"ok": True}


# ── Strava Webhook (public — no auth) ─────────────────────────────────────────

@app.get("/api/strava/webhook", tags=["strava"])
async def strava_webhook_verify(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    Strava webhook subscription validation.
    Strava sends GET with hub.mode, hub.challenge, hub.verify_token.
    We must echo back hub.challenge if verify_token matches.
    """
    if hub_mode == "subscribe" and hub_verify_token == STRAVA_WEBHOOK_VERIFY_TOKEN:
        return {"hub.challenge": hub_challenge}
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/api/strava/webhook", tags=["strava"])
async def strava_webhook_event(request: Request):
    """
    Strava sends POST here when a new activity is created/updated/deleted.
    Process in background to return 200 immediately (Strava expects fast response).
    """
    event = await request.json()
    log.info("Strava webhook event: %s", event)
    asyncio.create_task(handle_webhook_event(event))
    return {"ok": True}
```

---

## Step 6 — Smoke test

```bash
# 1. Confirm migration
docker compose exec postgres psql -U openrun -d openrun -c "\d users"
# Should show strava_* columns

# 2. Test auth URL generation
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"raderex","password":"x","role":"parent"}' | jq -r '.access_token')

curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/strava/auth-url | jq .
# → { "auth_url": "https://www.strava.com/oauth/authorize?..." }

# 3. Test status (should be disconnected)
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/strava/status | jq .
# → { "connected": false }

# 4. Test webhook verification
curl "http://localhost:8000/api/strava/webhook?hub.mode=subscribe&hub.challenge=test123&hub.verify_token=kabja_strava_verify"
# → { "hub.challenge": "test123" }
```

---

## DO NOT TOUCH

- `backend/services/ws_broadcast.py` — Realtime Engineer owns this
- `backend/services/tracking_manager.py` — Realtime Engineer owns this
- `flutter/` — Frontend Engineer owns all of this
- `nginx/` — do not touch
- Redis session keys — Realtime Engineer owns these

---

*Backend Engineer brief — Strava Integration — 2026-06-09*
