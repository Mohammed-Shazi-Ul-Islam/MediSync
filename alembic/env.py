import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Path Setup ─────────────────────────────────────────────────────────────────
# Add the project root to sys.path so we can import app modules.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.database import Base

# Import ALL models so they're registered with Base.metadata.
# Alembic uses metadata to auto-detect schema changes for migrations.
import app.models  # noqa: F401 — side effect import registers all models

settings = get_settings()

# ── Alembic Config ─────────────────────────────────────────────────────────────
config = context.config

# Override the sqlalchemy.url from alembic.ini with our real DATABASE_URL
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata object that Alembic introspects to generate migrations
target_metadata = Base.metadata


# ── Migration Runners ──────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — generates SQL without a live DB connection.
    Useful for reviewing SQL before applying, or for environments without DB access.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode — connects to DB and applies changes directly.
    This is what you use in development and CI/CD.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
