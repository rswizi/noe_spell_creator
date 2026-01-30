import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server.src.modules.wiki_db import Base, DATABASE_URL

config = context.config
fileConfig(config.config_file_name)

sync_url = os.environ.get("DATABASE_SYNC_URL")
if not sync_url:
    if DATABASE_URL.startswith("postgresql+asyncpg"):
        sync_url = DATABASE_URL.replace("+asyncpg", "+psycopg2")
    elif DATABASE_URL.startswith("sqlite+aiosqlite"):
        sync_url = DATABASE_URL.replace("sqlite+aiosqlite", "sqlite+pysqlite", 1)
    else:
        sync_url = DATABASE_URL
config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    raise RuntimeError("Offline migrations not supported.")
else:
    run_migrations_online()
