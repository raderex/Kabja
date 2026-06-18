# AGENT: Backend Engineer — V2
> **Ship today. Test tonight.**
> You own: All FastAPI routes · PostgreSQL · Alembic · Strava OAuth · API completeness.
> The code is written. Your job is to fix what's broken, add what's missing, and make every endpoint return the exact shape the Flutter app needs.

---

## Context

The backend is 81.5% Python and largely written. The Flutter app has no Dart files yet — being built today. Every API response shape you define TODAY is what the Frontend Engineer will wire up to. Get it right the first time.

**Repo:** `https://github.com/raderex/Kabja`
**Your files:** `backend/main.py` · `backend/strava.py` · `backend/territory.py` · `backend/db.py` · `backend/migrations/`

---

## Task 1 — Add user registration endpoint (CRITICAL — missing)

The app currently has `POST /api/auth/login` but **no registration endpoint**. The Flutter app cannot create new users. Add this to `main.py`:

```python
class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""

class AuthResponse(BaseModel):
    access_token: str
    user_id: str
    username: str
    display_name: str

@app.post("/api/auth/register", response_model=AuthResponse)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Create new user. Returns JWT immediately — no email verification."""
    import hashlib, secrets

    # Check username taken
    result = await db.execute(
        "SELECT id FROM users WHERE username = :u", {"u": req.username}
    )
    if result.fetchone():
        raise HTTPException(status_code=409, detail="Username already taken")

    # Hash password (SHA-256 + salt — upgrade to bcrypt if time allows)
    salt = secrets.token_hex(16)
    pw_hash = hashlib.sha256(f"{salt}{req.password}".encode()).hexdigest()

    user_id = str(uuid_lib.uuid4())
    display = req.display_name or req.username

    async with db.begin():
        await db.execute("""
            INSERT INTO users (id, username, display_name, password_hash, password_salt, created_at)
            VALUES (:id, :u, :dn, :ph, :ps, now())
        """, {"id": user_id, "u": req.username, "dn": display, "ph": pw_hash, "ps": salt})

    token = _create_jwt(user_id, req.username)
    return AuthResponse(
        access_token=token,
        user_id=user_id,
        username=req.username,
        display_name=display,
    )
```

Also update the `POST /api/auth/login` to return `user_id` and `display_name` in the response — the Flutter app needs them on login:

```python
# Login response must include:
return AuthResponse(
    access_token=token,
    user_id=user["id"],
    username=user["username"],
    display_name=user.get("display_name", user["username"]),
)
```

---

## Task 2 — Add `display_name` and `password_hash` columns to users table

Create migration `backend/migrations/versions/003_user_auth_fields.py`:

```python
"""003_user_auth_fields

Revision ID: 003
Revises: 002
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('users', sa.Column('display_name', sa.Text, nullable=True))
    op.add_column('users', sa.Column('password_hash', sa.Text, nullable=True))
    op.add_column('users', sa.Column('password_salt', sa.Text, nullable=True))
    op.add_column('users', sa.Column('avatar_url', sa.Text, nullable=True))
    op.add_column('users', sa.Column('total_km2', sa.Float, server_default='0'))
    op.add_column('users', sa.Column('total_runs', sa.Integer, server_default='0'))
    op.add_column('users', sa.Column('streak_days', sa.Integer, server_default='0'))
    op.add_column('users', sa.Column('last_run_date', sa.Date, nullable=True))

def downgrade():
    for col in ['display_name','password_hash','password_salt','avatar_url',
                'total_km2','total_runs','streak_days','last_run_date']:
        op.drop_column('users', col)
```

Run it:
```bash
docker compose exec api alembic upgrade head
```

---

## Task 3 — Fix and verify every API endpoint response shape

The Frontend Engineer is building the Flutter UI today. Every endpoint must return EXACTLY the documented shape. Go through each one and verify/fix:

### `GET /health`
```json
{ "status": "ok", "version": "1.0.0" }
```

### `POST /api/auth/login`
```json
{
  "access_token": "eyJ...",
  "user_id": "uuid-string",
  "username": "aarav",
  "display_name": "Aarav KC"
}
```

### `POST /api/auth/register`
Same shape as login.

### `POST /api/run/start`
```json
{ "run_id": "uuid-string" }
```

### `POST /api/run/finish`
```json
{
  "ok": true,
  "run_id": "uuid-string",
  "distance_km": 4.23,
  "duration_s": 1842,
  "cells_captured": 287,
  "km2_captured": 0.0431,
  "cells_lost": 12
}
```
Note: `cells_captured`, `km2_captured`, `cells_lost` must come from territory engine — not hardcoded.

### `GET /api/territory/{user_id}`
```json
{
  "user_id": "uuid",
  "cells": ["8a2a100d2dfffff", "8a2a100d2dfff1f"],
  "count": 2,
  "km2": 0.031
}
```

### `GET /api/leaderboard?limit=50`
```json
{
  "leaderboard": [
    { "rank": 1, "user_id": "uuid", "username": "aarav", "display_name": "Aarav KC", "km2": 12.4, "cell_count": 826, "streak_days": 7 }
  ]
}
```

### `GET /api/competitions`
```json
{
  "competitions": [
    {
      "id": 1,
      "name": "June Sprint",
      "prize_description": "Free month premium",
      "prize_image_url": "https://...",
      "starts_at": "2026-06-01T00:00:00Z",
      "ends_at": "2026-06-30T23:59:59Z",
      "status": "active",
      "my_km2": 0.43,
      "my_rank": 3,
      "total_participants": 24
    }
  ]
}
```

### `GET /api/profile/{user_id}`
**ADD THIS ENDPOINT — missing, Profile screen needs it:**
```python
@app.get("/api/profile/{user_id}")
async def get_profile(user_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute("""
        SELECT u.id, u.username, u.display_name, u.avatar_url,
               u.total_km2, u.total_runs, u.streak_days, u.created_at,
               COUNT(c.h3_index) as live_cell_count
        FROM users u
        LEFT JOIN cells c ON c.owner_id = u.id
        WHERE u.id = :uid
        GROUP BY u.id
    """, {"uid": user_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    # Strava connection status
    strava_result = await db.execute(
        "SELECT strava_athlete_id FROM users WHERE id = :uid", {"uid": user_id}
    )
    strava_row = strava_result.fetchone()
    strava_connected = bool(strava_row and strava_row[0])

    return {
        "user_id": row[0],
        "username": row[1],
        "display_name": row[2] or row[1],
        "avatar_url": row[3],
        "total_km2": round(row[4] or 0, 4),
        "total_runs": row[5] or 0,
        "streak_days": row[6] or 0,
        "joined_at": row[7].isoformat() if row[7] else None,
        "live_cell_count": row[8] or 0,
        "strava_connected": strava_connected,
    }
```

### `GET /api/strava/auth-url`
```json
{ "url": "https://www.strava.com/oauth/authorize?client_id=..." }
```

### `GET /api/strava/status`
```json
{
  "connected": true,
  "athlete_name": "Aarav KC",
  "athlete_id": 12345678,
  "profile_picture": "https://...",
  "last_sync": "2026-06-01T10:00:00Z"
}
```

---

## Task 4 — Seed a test user

Add a seed script so everyone can test immediately without manual DB insertion:

Create `scripts/seed_test_data.py`:
```python
#!/usr/bin/env python3
"""
Seed test users and a demo competition.
Run: docker compose exec api python /app/scripts/seed_test_data.py
"""
import asyncio
import sys
import os
sys.path.insert(0, '/app')

from db import AsyncSessionLocal

async def seed():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Test users
            users = [
                ("test-user-1", "testrunner", "Test Runner", "test123"),
                ("test-user-2", "aarav_kc", "Aarav KC", "test123"),
                ("test-user-3", "priya_rana", "Priya Rana", "test123"),
            ]
            for uid, username, display, pw in users:
                import hashlib, secrets
                salt = "testsalt123"
                pw_hash = hashlib.sha256(f"{salt}{pw}".encode()).hexdigest()
                await db.execute("""
                    INSERT INTO users (id, username, display_name, password_hash, password_salt, created_at)
                    VALUES (:id, :u, :dn, :ph, :ps, now())
                    ON CONFLICT (id) DO NOTHING
                """, {"id": uid, "u": username, "dn": display, "ph": pw_hash, "ps": salt})
                print(f"  ✓ User: {username} / test123")

            # Demo competition
            await db.execute("""
                INSERT INTO competitions (name, prize_description, prize_image_url, starts_at, ends_at, status)
                VALUES (
                    'June Sprint 2026',
                    'Winner gets free Kabja Premium for 3 months + featured on the app',
                    'https://placehold.co/800x400/EF9F27/000000?text=June+Sprint+Prize',
                    now(),
                    now() + interval '28 days',
                    'active'
                )
                ON CONFLICT DO NOTHING
            """)
            print("  ✓ Competition: June Sprint 2026")

    print("\n✓ Seed complete. Login: testrunner / test123")

asyncio.run(seed())
```

Run it:
```bash
docker compose exec api python /app/scripts/seed_test_data.py
```

---

## Task 5 — Update streak logic in `POST /api/run/finish`

After a run finishes successfully, update the user's streak:

```python
async def _update_user_streak(user_id: str, db: AsyncSession):
    """Increment streak if ran today, reset if gap > 1 day."""
    from datetime import date, timedelta
    result = await db.execute(
        "SELECT last_run_date, streak_days FROM users WHERE id = :uid",
        {"uid": user_id}
    )
    row = result.fetchone()
    if not row:
        return

    today = date.today()
    last_run = row[0]
    streak = row[1] or 0

    if last_run is None or last_run < today - timedelta(days=1):
        new_streak = 1  # Reset
    elif last_run == today - timedelta(days=1):
        new_streak = streak + 1  # Continue
    else:
        new_streak = streak  # Already ran today

    await db.execute("""
        UPDATE users SET last_run_date = :today, streak_days = :s,
        total_runs = total_runs + 1
        WHERE id = :uid
    """, {"today": today, "s": new_streak, "uid": user_id})
```

Call `await _update_user_streak(user_id, db)` inside the `run/finish` route after the territory engine fires.

---

## Task 6 — Verify Strava OAuth flow works

Open `backend/strava.py` and trace through the full OAuth flow:

```
1. GET /api/strava/auth-url
   → Builds: https://www.strava.com/oauth/authorize?client_id=...&redirect_uri=...&scope=activity:read_all
   → Must return: { "url": "https://..." }

2. GET /api/strava/callback?code=...&state=...
   → Exchanges code for tokens
   → Stores in users table: strava_athlete_id, strava_access_token, strava_refresh_token, strava_token_expiry
   → Redirects to: kabja://strava-callback?status=success&user_id=...
   → Must NOT redirect to kabja://strava-callback?status=error (breaks the deep link)

3. POST /api/strava/sync
   → Fetches activities from Strava API
   → Calls process_run() for each activity
   → Pushes strava_sync WS message for each completed activity
```

If any of these are broken, the Strava section of the profile screen will be dead. Fix before handing off.

---

## Task 7 — CORS configuration

The Flutter web build (for testing in browser) needs CORS. Verify this is in `main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # tighten to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Without this, any browser-based test will fail with CORS errors.

---

## Task 8 — Full API smoke test

Run this after everything above is done:

```bash
BASE="http://localhost:8000"

# Health
curl -s $BASE/health | python3 -m json.tool

# Register
curl -s -X POST $BASE/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"smoketest","password":"abc123","display_name":"Smoke Test"}' | python3 -m json.tool

# Login
TOKEN=$(curl -s -X POST $BASE/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testrunner","password":"test123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Profile
USER_ID=$(curl -s -X POST $BASE/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testrunner","password":"test123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['user_id'])")
curl -s "$BASE/api/profile/$USER_ID" | python3 -m json.tool

# Leaderboard
curl -s "$BASE/api/leaderboard" | python3 -m json.tool

# Competitions
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/competitions" | python3 -m json.tool

# Territory (empty for new user — that's correct)
curl -s "$BASE/api/territory/$USER_ID" | python3 -m json.tool

# Strava auth URL
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/strava/auth-url" | python3 -m json.tool

echo "All done."
```

Every call must return HTTP 200 with valid JSON. No 500s, no 404s.

---

## Deliverables checklist

```
□ POST /api/auth/register works, returns token + user_id
□ POST /api/auth/login returns token + user_id + display_name
□ GET /api/profile/{user_id} exists and returns full profile
□ Migration 003 runs clean (display_name, password_hash, streak fields)
□ Seed script creates testrunner / test123
□ run/finish returns cells_captured + km2_captured + cells_lost (real values)
□ Strava auth-url returns valid URL
□ Strava callback redirects correctly to kabja:// deep link
□ CORS middleware added
□ Full smoke test passes with zero 500s
□ Streak updates on run finish
```

---

*Backend Engineer — Kabja V2 — 2026-06-02*
