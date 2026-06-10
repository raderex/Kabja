"""
backend/cron.py
Competition snapshot job — runs hourly to capture territory stats.
"""
import asyncio
import os
import httpx
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import AsyncSessionLocal

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT = os.getenv('TELEGRAM_ADMIN_CHAT_ID')

async def snapshot_competitions():
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Find active competitions that have just ended
            result = await db.execute("""
                SELECT id, name FROM competitions
                WHERE status = 'active' AND ends_at <= now()
            """)
            ended = result.fetchall()
            for comp_id, comp_name in ended:
                # Mark as ended
                await db.execute("UPDATE competitions SET status='ended' WHERE id=:id", {'id': comp_id})
                # Snapshot territory per user
                cells_res = await db.execute("""
                    SELECT owner_id, COUNT(*) as cell_count
                    FROM cells
                    GROUP BY owner_id
                    ORDER BY cell_count DESC
                """)
                rows = cells_res.fetchall()
                # Compute km2 per cell using H3 sample area
                import h3 as _h3
                sample = "8a2a100d2dfffff"
                cell_area = _h3.cell_area(sample, unit='km^2')
                for owner_id, cell_count in rows:
                    km2 = round(cell_count * cell_area, 4)
                    await db.execute("""
                        INSERT INTO competition_entries (competition_id, user_id, cell_count, km2, created_at)
                        VALUES (:cid, :uid, :cc, :km2, now())
                    """, {'cid': comp_id, 'uid': owner_id, 'cc': cell_count, 'km2': km2})
                # Notify winner via Telegram
                if rows:
                    winner_id, winner_cells = rows[0]
                    winner_km2 = round(winner_cells * cell_area, 4)
                    message = f"🏆 Competition '{comp_name}' ended! Winner: {winner_id} with {winner_km2} km²"
                    await _telegram_notify(message)

async def _telegram_notify(message: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        print(f"[cron] Telegram not configured – would send: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={'chat_id': TELEGRAM_CHAT, 'text': message})

async def main():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(snapshot_competitions, 'interval', hours=1, id='snapshot')
    scheduler.start()
    print('[cron] Scheduler started – checking competitions every hour')
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == '__main__':
    asyncio.run(main())
