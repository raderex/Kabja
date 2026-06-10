"""
backend/db.py — async PostgreSQL connection via SQLAlchemy + asyncpg.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = (
    f"postgresql+asyncpg://"
    f"{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ.get('POSTGRES_HOST', 'postgres')}:"
    f"{os.environ.get('POSTGRES_PORT', '5432')}/"
    f"{os.environ['POSTGRES_DB']}"
)

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency. Use with: db: AsyncSession = Depends(get_db)"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Call on app startup to run Alembic migrations programmatically."""
    import subprocess
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd="/app",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[db] migration error:\n{result.stderr}")
    else:
        print(f"[db] migrations OK")