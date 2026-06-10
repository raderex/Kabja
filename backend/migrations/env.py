"""
Alembic environment configuration for async SQLAlchemy.
"""
import os
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Retrieve database URL from environment variables
DATABASE_URL = (
    f"postgresql+asyncpg://"
    f"{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ.get('POSTGRES_HOST','postgres')}:{os.environ.get('POSTGRES_PORT','5432')}/"
    f"{os.environ['POSTGRES_DB']}"
)

def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DB driver to be available.
    """
    context.configure(url=DATABASE_URL, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine

    connectable = create_async_engine(DATABASE_URL)

    async def do_run_migrations():
        async with connectable.connect() as connection:
            await connection.run_sync(lambda sync_conn: context.configure(connection=sync_conn, compare_type=True))
            async with connection.begin():
                await connection.run_sync(lambda _: context.run_migrations())

    asyncio.run(do_run_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
