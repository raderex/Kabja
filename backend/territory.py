"""
backend/territory.py
Territory engine: converts a finished run polyline into claimed H3 hex cells.
Exported contract:  async def process_run(session: dict) -> dict
"""
import os
import json
import asyncio
import h3
import httpx
from datetime import datetime, timezone
from db import AsyncSessionLocal

H3_RESOLUTION = int(os.getenv('H3_RESOLUTION', '10'))
RING_BUFFER = int(os.getenv('TERRITORY_RING_BUFFER', '1'))
OSRM_HOST = os.getenv('OSRM_HOST', 'osrm')
OSRM_PORT = os.getenv('OSRM_PORT', '5000')

# Public entry point (called by Realtime Engineer)
async def process_run(session: dict) -> dict:
    """Process a finished run session.
    Input session dict:
      { run_id, user_id, polyline: [[lat,lng],...], distance_km, started_at, finished_at }
    Returns dict: { cells_captured: int, km2_captured: float, cells_lost: int }
    """
    polyline = session.get('polyline', [])
    run_id = session['run_id']
    user_id = session['user_id']
    if len(polyline) < 2:
        return {'cells_captured': 0, 'km2_captured': 0.0, 'cells_lost': 0}
    # 1. Snap to roads via OSRM
    snapped = await _snap_to_roads(polyline) or polyline
    # 2. Convert to H3 cells
    new_cells = _polyline_to_cells(snapped)
    # 3. Persist cells and compute captures
    cells_captured, cells_lost = await _claim_cells(run_id, user_id, new_cells, finished_at=session.get('finished_at'))
    # 4. Persist run record
    await _save_run(session, snapped, new_cells)
    km2 = _compute_km2(new_cells)
    return {'cells_captured': cells_captured, 'km2_captured': round(km2, 4), 'cells_lost': cells_lost}

# H3 conversion helpers
def _polyline_to_cells(polyline: list[list]) -> set[str]:
    cells: set[str] = set()
    for lat, lng in polyline:
        center = h3.geo_to_h3(lat, lng, H3_RESOLUTION)
        cells.add(center)
        cells.update(h3.k_ring(center, RING_BUFFER))
    return cells

def _compute_km2(cells: set[str]) -> float:
    if not cells:
        return 0.0
    sample = next(iter(cells))
    cell_area = h3.cell_area(sample, unit='km^2')
    return cell_area * len(cells)

# OSRM road-snap
async def _snap_to_roads(polyline: list[list]) -> list[list] | None:
    # OSRM expects lng,lat ordering
    coords = ';'.join(f"{lng},{lat}" for lat, lng in polyline)
    url = f'http://{OSRM_HOST}:{OSRM_PORT}/match/v1/foot/{coords}'
    params = {'overview': 'full', 'geometries': 'geojson', 'annotations': 'false'}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return None
            data = resp.json()
            if data.get('code') != 'Ok':
                return None
            geom = data['matchings'][0]['geometry']['coordinates']
            return [[lat, lng] for lng, lat in geom]
    except Exception as e:
        print(f"[territory] OSRM snap failed: {e}")
        return None

# DB persistence helpers
async def _claim_cells(run_id: str, user_id: str, cells: set[str], finished_at: str | None = None) -> tuple[int, int]:
    captured_from_others = 0
    async with AsyncSessionLocal() as db:
        async with db.begin():
            for cell_id in cells:
                result = await db.execute('SELECT owner_id, captured_at FROM cells WHERE h3_index = :h3', {'h3': cell_id})
                row = result.fetchone()
                if row is None:
                    await db.execute('INSERT INTO cells (h3_index, owner_id, captured_at, run_id) VALUES (:h3, :uid, now(), :rid)', {'h3': cell_id, 'uid': user_id, 'rid': run_id})
                elif row[0] != user_id:
                    # Only overwrite if this run finished AFTER the cell was captured.
                    # Prevents Strava imports of old runs from stealing recently-captured cells.
                    existing_captured_at = row[1]
                    if existing_captured_at is not None and finished_at:
                        from datetime import datetime as dt
                        try:
                            run_finished = dt.fromisoformat(finished_at.replace('Z', '+00:00'))
                            if run_finished <= existing_captured_at:
                                continue  # skip — cell was captured more recently
                        except (ValueError, TypeError):
                            pass  # if we can't parse, allow the overwrite
                    await db.execute('UPDATE cells SET owner_id=:uid, captured_at=now(), run_id=:rid WHERE h3_index=:h3', {'h3': cell_id, 'uid': user_id, 'rid': run_id})
                    captured_from_others += 1

            # Compute cells_lost: cells this user previously owned that were stolen
            # since their last run (owned by someone else now).
            lost_result = await db.execute(
                'SELECT COUNT(*) FROM cells WHERE run_id != :rid AND owner_id != :uid '
                'AND h3_index IN (SELECT h3_index FROM cells WHERE run_id IN '
                '(SELECT id FROM runs WHERE user_id = :uid AND id != :rid))',
                {'uid': user_id, 'rid': run_id}
            )
            cells_lost = lost_result.scalar() or 0

    return captured_from_others, cells_lost

async def _save_run(session: dict, snapped_polyline: list[list], cells: set[str]):
    # Ensure user exists
    user_id = session['user_id']
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute('INSERT INTO users (id, username, created_at) VALUES (:id, :username, now()) ON CONFLICT (id) DO NOTHING', {'id': user_id, 'username': session.get('username', user_id)})
            await db.execute('INSERT INTO runs (id, user_id, started_at, finished_at, distance_km, polyline, snapped_polyline, status, source) VALUES (:id, :uid, :started, :finished, :dist, :poly, :snapped, :status, :source) ON CONFLICT (id) DO NOTHING', {
                'id': session['run_id'],
                'uid': user_id,
                'started': session.get('started_at'),
                'finished': session.get('finished_at', datetime.utcnow().isoformat()),
                'dist': session.get('distance_km', 0),
                'poly': json.dumps(session.get('polyline', [])),
                'snapped': json.dumps(snapped_polyline),
                'status': 'finished',
                'source': session.get('source', 'kabja'),
            })
